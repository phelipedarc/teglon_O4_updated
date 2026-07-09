#!/usr/bin/env python
"""
simulate_observed_tiles.py

Simulate ~N observation pointings (ObservedTile rows + ObservedTile_HealpixPixel
junction rows) covering the highest-probability region of an existing GW HealpixMap,
so that web/src/analysis/model_detection_efficiency.py has data to work with.

This MIRRORS the real ingestion path in
    web/src/ingestion/load_observed_tiles.py
using the same Tile/Detector objects and the same DB helpers.

Defaults target: HealpixMap id=2 (S190425z, NSIDE=256), Detector SWOPE id=55,
Band 'SDSS r' id=19.

RUN INSIDE THE TEGLON CONTAINER (cwd /app, PYTHONPATH=/app). Because only the repo
is bind-mounted at /app, drop this file somewhere under the repo (e.g. /app) and run:

  cd /mnt/nvmeold1/teglon_install/teglon_O4_updated
  docker compose -p teglon_install --env-file docker/.env -f docker/docker-compose.yml \
      run --rm --entrypoint python teglon_cli /app/simulate_observed_tiles.py \
      --n_tiles 60 --dry_run

Remove --dry_run to actually INSERT. See the cleanup SQL at the bottom of this file.
"""

import os
import csv
import time
import optparse

import numpy as np
import healpy as hp

def ensure_teglon_on_path(explicit_root=None):
    """Put the TEGLON app root (the dir containing web/src) on sys.path so this drop-in script
    imports TEGLON's internals WITHOUT living inside the package. Order: --teglon_root ->
    $TEGLON_ROOT -> already importable (container PYTHONPATH=/app) -> walk up from cwd/script dir."""
    import sys
    marker = os.path.join("web", "src", "utilities", "Database_Helpers.py")
    ok = lambda r: bool(r) and os.path.exists(os.path.join(r, marker))
    for cand in (explicit_root, os.environ.get("TEGLON_ROOT")):
        if ok(cand):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            return cand
    for p in list(sys.path):
        if ok(p):
            return p
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = start
        for _ in range(8):
            if ok(d):
                if d not in sys.path:
                    sys.path.insert(0, d)
                return d
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    raise ImportError("Could not locate the TEGLON app root (dir containing web/src). Run inside "
                      "the container (PYTHONPATH=/app), pass --teglon_root, or set TEGLON_ROOT.")


def main():
    parser = optparse.OptionParser()
    parser.add_option('--healpix_map_id', default=2, type='int',
                      help='HealpixMap.id to simulate pointings for (default 2 = S190425z NSIDE 256).')
    parser.add_option('--nside', default=256, type='int',
                      help='NSIDE of the map. MUST equal the map RescaledNSIDE (256 for map 2).')
    parser.add_option('--detector_id', default=55, type='int', help='Detector.id (default 55 = SWOPE).')
    parser.add_option('--band_id', default=19, type='int', help='Band.id (default 19 = SDSS r).')
    parser.add_option('--n_tiles', default=60, type='int', help='Number of pointings to simulate.')
    parser.add_option('--position_angle', default=0.0, type='float', help='Tile position angle (deg).')
    parser.add_option('--mag_lim', default=21.0, type='float', help='Limiting magnitude for each tile.')
    parser.add_option('--merger_mjd', default=58598.346134259256, type='float',
                      help='Merger MJD (default S190425z). Tile MJDs are placed within the '
                           '[mjd_after_min, mjd_after_max]-day window after this.')
    parser.add_option('--mjd_after_min', default=1.0, type='float',
                      help='Earliest tile MJD, in days after merger.')
    parser.add_option('--mjd_after_max', default=3.0, type='float',
                      help='Latest tile MJD, in days after merger (e.g. 2.0 => observe only the '
                           'first 2 days).')
    parser.add_option('--field_prefix', default='REDBACK_SIM_', type='str',
                      help='FieldName prefix (used by the cleanup SQL).')
    parser.add_option('--order_by', default='prob', type='str',
                      help="Tile-center ranking: 'prob' (HealpixPixel.Prob, 2D) or "
                           "'netprob' (HealpixPixel_Completeness.NetPixelProb, 4D).")
    parser.add_option('--min_pixel_separation', default=3, type='int',
                      help='Minimum HEALPix ring-neighbour spacing between chosen tile centers '
                           '(>=1). Prevents all tiles landing on adjacent pixels.')
    parser.add_option('--dry_run', action='store_true', default=False,
                      help='Compute everything and print, but do NOT insert.')
    parser.add_option('--teglon_root', default='', type='str',
                      help='TEGLON app root (dir containing web/src); only needed if not '
                           'auto-resolvable via PYTHONPATH or $TEGLON_ROOT.')
    options, _ = parser.parse_args()

    # Resolve TEGLON and import its internals lazily (keeps this script separable / drop-in).
    ensure_teglon_on_path(options.teglon_root)
    from web.src.objects.Detector import Detector
    from web.src.objects.Tile import Tile
    from web.src.utilities.Database_Helpers import query_db, batch_insert, bulk_upload

    MAP_ID = options.healpix_map_id
    NSIDE = options.nside
    DETECTOR_ID = options.detector_id
    BAND_ID = options.band_id

    # -----------------------------------------------------------------------
    # 1. Load the Detector exactly like load_observed_tiles.py:123-135
    # -----------------------------------------------------------------------
    detector_select = ("SELECT id, Name, Deg_width, Deg_height, Deg_radius, Area, "
                       "MinDec, MaxDec, ST_AsText(Poly) FROM Detector WHERE id=%s")
    det_row = query_db([detector_select % DETECTOR_ID])[0][0]
    detector_name = det_row[1]
    detector_poly = Detector.get_detector_vertices_from_teglon_db(det_row[8])
    detector = Detector(detector_name, detector_poly, detector_id=int(det_row[0]))
    print("Detector: %s (id=%s) area=%.4f sqdeg radius_proxy=%.4f" %
          (detector.name, detector.id, detector.area, detector.radius_proxy))

    # -----------------------------------------------------------------------
    # 2. Load map pixels. Key by Pixel_Index -> (HealpixPixel.id, N128_SkyPixel_id).
    #    This is the resolution the junction needs: junction.HealpixPixel_id is the
    #    HealpixPixel PRIMARY KEY (id), NOT the healpy Pixel_Index.
    #    (Same idea as load_observed_tiles.py:112-120 -> map_pixel_dict[p][0].)
    # -----------------------------------------------------------------------
    # EBV comes from SkyPixel_EBV keyed by N128_SkyPixel_id (HealpixPixel has no EBV
    # column; load_observed_tiles.py gets EBV from the ebv.pkl pickle keyed by the N128
    # pixel index -- this join reproduces the same value straight from the DB).
    if options.order_by.lower() == 'netprob':
        pix_sql = ("SELECT hp.id, hp.Pixel_Index, hp.N128_SkyPixel_id, hp.Prob, "
                   "ebv.EBV, hpc.NetPixelProb "
                   "FROM HealpixPixel hp "
                   "JOIN HealpixPixel_Completeness hpc ON hpc.HealpixPixel_id = hp.id "
                   "JOIN SkyPixel_EBV ebv ON ebv.N128_SkyPixel_id = hp.N128_SkyPixel_id "
                   "WHERE hp.HealpixMap_id = %s")
        rank_col = 5
    else:
        pix_sql = ("SELECT hp.id, hp.Pixel_Index, hp.N128_SkyPixel_id, hp.Prob, ebv.EBV "
                   "FROM HealpixPixel hp "
                   "JOIN SkyPixel_EBV ebv ON ebv.N128_SkyPixel_id = hp.N128_SkyPixel_id "
                   "WHERE hp.HealpixMap_id = %s")
        rank_col = 3
    rows = query_db([pix_sql % MAP_ID])[0]
    print("Loaded %s map pixels." % len(rows))

    # Pixel_Index -> HealpixPixel.id  (used to build junction rows)
    pixidx_to_hpid = {}
    # Pixel_Index -> N128_SkyPixel_id  (used for the ObservedTile.N128_SkyPixel_id column)
    pixidx_to_n128id = {}
    # Pixel_Index -> EBV (for the ObservedTile.EBV column)
    pixidx_to_ebv = {}
    for r in rows:
        pi = int(r[1])
        pixidx_to_hpid[pi] = int(r[0])
        pixidx_to_n128id[pi] = int(r[2])
        pixidx_to_ebv[pi] = float(r[4])

    # -----------------------------------------------------------------------
    # 3. Pick tile centers: top-ranked pixels, spaced apart so tiles don't all
    #    stack on adjacent pixels. Greedy: walk pixels in descending rank and
    #    accept a center only if it is >= min_pixel_separation rings from every
    #    already-accepted center.
    # -----------------------------------------------------------------------
    ranked = sorted(rows, key=lambda r: float(r[rank_col]), reverse=True)
    chosen_pix_indices = []
    accepted_vecs = []
    sep_rad = np.radians(options.min_pixel_separation * hp.nside2resol(NSIDE, arcmin=True) / 60.0)
    for r in ranked:
        if len(chosen_pix_indices) >= options.n_tiles:
            break
        pi = int(r[1])
        v = hp.pix2vec(NSIDE, pi)
        ok = True
        for av in accepted_vecs:
            # angular sep between unit vectors
            dot = np.clip(np.dot(v, av), -1.0, 1.0)
            if np.arccos(dot) < sep_rad:
                ok = False
                break
        if ok:
            chosen_pix_indices.append(pi)
            accepted_vecs.append(v)
    print("Selected %s tile-center pixels (requested %s)." %
          (len(chosen_pix_indices), options.n_tiles))

    # -----------------------------------------------------------------------
    # 4. Build ObservedTile insert rows + collect enclosed pixels per tile.
    #    Column order/values mirror load_observed_tiles.py:250-283.
    #    Coord POINT is (Dec, RA-180) and Poly is Tile.query_polygon_string,
    #    both in the DB's lat/lon SRS convention (see Teglon_Shape.create_query_polygon_string).
    # -----------------------------------------------------------------------
    insert_observed_tile = '''
        INSERT INTO
            ObservedTile (Source, Detector_id, FieldName, RA, _Dec, Coord, Poly, EBV, N128_SkyPixel_id, Band_id,
            MJD, Exp_Time, Mag_Lim, HealpixMap_id, PositionAngle, x0, x0_err, a, a_err, n, n_err)
        VALUES (%s, %s, %s, %s, %s, ST_PointFromText(%s, 4326), ST_GEOMFROMTEXT(%s, 4326), %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s)
    '''

    obs_tile_insert_data = []
    # Parallel list: enclosed HealpixPixel.id list (already resolved) for each tile,
    # in the SAME order as obs_tile_insert_data, so we can zip after we learn tile ids.
    enclosed_hpids_per_tile = []

    rng = np.random.default_rng(42)
    for i, pi in enumerate(chosen_pix_indices):
        ra, dec = hp.pix2ang(NSIDE, pi, lonlat=True)
        ra = float(ra)
        dec = float(dec)

        # N128 SkyPixel id + EBV: reuse the map pixel's own values (identical result to
        # hp.ang2pix(128, ra, dec) -> N128_dict lookup, but avoids the pickle dependency).
        n128_id = pixidx_to_n128id[pi]
        tile_ebv = pixidx_to_ebv[pi]

        # Build the Tile and compute enclosed NSIDE-256 pixel indices (query_polygon).
        t = Tile(ra, dec, detector, NSIDE, position_angle_deg=options.position_angle)
        enclosed_idx = list(t.enclosed_pixel_indices)

        # Resolve enclosed Pixel_Index -> HealpixPixel.id, but ONLY for pixels that
        # exist in THIS (partial) map. Map 2 is partial (201378/786432), so a tile at
        # the probability edge can enclose off-map pixels -> guard with .get().
        # (load_observed_tiles.py:329 does map_pixel_dict[p][0] with no guard and would
        #  KeyError on a partial map; we guard here.)
        hp_ids = []
        for p in enclosed_idx:
            hpid = pixidx_to_hpid.get(int(p))
            if hpid is not None:
                hp_ids.append(hpid)
        if len(hp_ids) == 0:
            # Nothing on-map for this tile; skip it (shouldn't happen for top-prob centers)
            print("  [skip] tile %s at (%.3f, %.3f): no enclosed pixels on map." % (i, ra, dec))
            continue

        mjd = float(options.merger_mjd + options.mjd_after_min +
                    (options.mjd_after_max - options.mjd_after_min) * rng.random())  # obs window
        field_name = "%s%d" % (options.field_prefix, i)

        row = (
            'REDBACK_SIM',          # Source
            detector.id,            # Detector_id
            field_name,             # FieldName
            ra,                     # RA
            dec,                    # _Dec
            "POINT(%s %s)" % (dec, ra - 180.0),   # Coord (Dec, RA-180) - MySQL lat/lon
            t.query_polygon_string, # Poly (MULTIPOLYGON in lat/lon SRS)
            tile_ebv,               # EBV
            n128_id,                # N128_SkyPixel_id (references SkyPixel.id, NSIDE 128)
            BAND_ID,                # Band_id
            mjd,                    # MJD
            None,                   # Exp_Time
            options.mag_lim,        # Mag_Lim
            MAP_ID,                 # HealpixMap_id
            options.position_angle, # PositionAngle
            None, None, None, None, None, None,  # x0, x0_err, a, a_err, n, n_err
        )
        obs_tile_insert_data.append(row)
        enclosed_hpids_per_tile.append(hp_ids)

    print("Prepared %s ObservedTile rows; total enclosed junction rows = %s" %
          (len(obs_tile_insert_data), sum(len(x) for x in enclosed_hpids_per_tile)))

    if options.dry_run:
        print("\n*** DRY RUN *** no inserts performed.")
        print("First tile sample:")
        if obs_tile_insert_data:
            s = obs_tile_insert_data[0]
            print("  FieldName=%s RA=%.4f Dec=%.4f MJD=%.4f MagLim=%s N128id=%s enclosed_hpids=%s"
                  % (s[2], s[3], s[4], s[10], s[12], s[8], enclosed_hpids_per_tile[0]))
        return 0

    if len(obs_tile_insert_data) == 0:
        print("Nothing to insert. Exiting.")
        return 0

    # -----------------------------------------------------------------------
    # 5. INSERT the ObservedTile rows (same helper as load_observed_tiles.py:286).
    # -----------------------------------------------------------------------
    print("Inserting %s ObservedTile rows..." % len(obs_tile_insert_data))
    batch_insert(insert_observed_tile, obs_tile_insert_data)

    # -----------------------------------------------------------------------
    # 6. Recover the ids of the rows we just inserted (same trick as
    #    load_observed_tiles.py:290-298: newest N ids, ascending).
    # -----------------------------------------------------------------------
    select_inserted = '''
        WITH NewINSERT AS (
            SELECT id FROM ObservedTile ORDER BY id DESC LIMIT %s
        )
        SELECT id FROM NewINSERT ORDER BY id ASC;
    '''
    inserted_ids = query_db([select_inserted % len(obs_tile_insert_data)])[0]
    inserted_ids = [int(r[0]) for r in inserted_ids]
    assert len(inserted_ids) == len(obs_tile_insert_data), "id recovery count mismatch!"

    # -----------------------------------------------------------------------
    # 7. Build the junction (ObservedTile_id, HealpixPixel_id, HealpixMap_id) and
    #    bulk-load via CSV -> LOAD DATA LOCAL INFILE, exactly like
    #    load_observed_tiles.py:307-366. CSV must live under /app (bind-mounted).
    # -----------------------------------------------------------------------
    tile_pixel_data = []
    for ot_id, hp_ids in zip(inserted_ids, enclosed_hpids_per_tile):
        for hpid in hp_ids:
            tile_pixel_data.append((ot_id, hpid, MAP_ID))
    print("Junction rows to load: %s" % len(tile_pixel_data))

    csv_path = "/app/%s_sim_tile_pixel_upload.csv" % detector.name.replace("/", "_")
    with open(csv_path, 'w') as f:
        w = csv.writer(f)
        for d in tile_pixel_data:
            w.writerow(d)

    ot_hp_upload_sql = ("LOAD DATA LOCAL INFILE '%s' "
                        "INTO TABLE ObservedTile_HealpixPixel "
                        "FIELDS TERMINATED BY ',' "
                        "LINES TERMINATED BY '\n' "
                        "(ObservedTile_id, HealpixPixel_id, HealpixMap_id);")
    ok = bulk_upload(ot_hp_upload_sql % csv_path)
    if not ok:
        print("Bulk upload FAILED. ObservedTile rows are inserted but junction is incomplete!")
        print("Run the cleanup SQL to remove partial sim data.")
        return 1

    try:
        os.remove(csv_path)
    except OSError:
        pass

    print("DONE. Inserted %s tiles + %s junction rows for map %s (FieldName LIKE '%s%%')." %
          (len(inserted_ids), len(tile_pixel_data), MAP_ID, options.field_prefix))
    print("Inserted ObservedTile id range: %s .. %s" % (min(inserted_ids), max(inserted_ids)))
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    print("Elapsed: %.1fs" % (time.time() - t0))
    raise SystemExit(rc)
