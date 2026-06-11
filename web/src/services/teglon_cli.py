"""Unified command-line interface for Teglon-O4.

A single front door for the whole pipeline so you no longer have to run
`load_map.py` / `extract_tiles.py` / `plot_teglon.py` by hand:

    teglon run S230529ay            # load map -> extract tiles -> plot, in one shot
    teglon load-map S230529ay       # individual stages
    teglon extract S230529ay
    teglon plot S230529ay
    teglon load-obs S230529ay --tile-file my_obs.ecsv
    teglon efficiency S230529ay --model-type kne
    teglon bootstrap                # build a fresh DB (dust + GLADE + detectors + grids)

The database connection is resolved from environment variables first (see
`web/src/utilities/Database_Helpers.py`), so the same command works inside the
Docker network (DATABASE_HOST=gw_db) or from the host (DATABASE_HOST=127.0.0.1,
DATABASE_PORT=53306) with no port-forwarding.
"""

import argparse
import json
import os
import subprocess
import sys
import time


# --- repo-root awareness -----------------------------------------------------
# Stage logic and the existing scripts use paths relative to the repo root
# (e.g. './web/events/{GWID}', './Settings.ini'). Make sure we run from there
# regardless of where `teglon` was invoked.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def _ensure_repo_root():
    if os.path.isdir(os.path.join(REPO_ROOT, "web")):
        os.chdir(REPO_ROOT)


def _banner(msg):
    print("\n" + "=" * 70)
    print(msg)
    print("=" * 70 + "\n", flush=True)


def _run_script(rel_path, extra_args):
    """Run one of the standalone (non-method) scripts as a subprocess from the
    repo root, inheriting the current environment (incl. DATABASE_* overrides)."""
    cmd = [sys.executable, rel_path] + list(extra_args)
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=REPO_ROOT, env=env)


# --- pure helpers (no DB / network / side effects; unit-tested) ---------------
def event_dir(gw_id, healpix_dir="./web/events/{GWID}"):
    """Resolve an event's working directory from the {GWID} template."""
    return healpix_dir.replace("{GWID}", gw_id)


def build_delete_map_sql(map_id):
    """Return the ordered SQL statements that remove a single HealpixMap by id.

    Mirrors web/src/utilities/delete_map.py exactly (BackupTables -> lock ->
    DeleteMap -> unlock). Pure: builds strings only, runs nothing."""
    map_id = int(map_id)
    create_baks = "CALL BackupTables(%d);" % map_id
    lock_tables = (
        "LOCK TABLE HealpixMap WRITE, HealpixPixel WRITE, HealpixPixel_Completeness WRITE, "
        "HealpixPixel_Galaxy_Weight WRITE, ObservedTile WRITE, ObservedTile_HealpixPixel WRITE, "
        "StaticTile_HealpixPixel WRITE, HealpixMap_bak WRITE, HealpixPixel_bak WRITE, "
        "HealpixPixel_Completeness_bak WRITE, HealpixPixel_Galaxy_Weight_bak WRITE, "
        "ObservedTile_bak WRITE, ObservedTile_HealpixPixel_bak WRITE, StaticTile_HealpixPixel_bak WRITE;"
    )
    delete_map = "CALL DeleteMap(%d);" % map_id
    unlock_tables = "UNLOCK TABLES;"
    return [create_baks, lock_tables, delete_map, unlock_tables]


def plan_event_file_deletion(directory):
    """List existing paths under `directory` (all files plus the directory itself),
    sorted. Inspects only the filesystem -- safe to call on anything."""
    paths = []
    if os.path.isdir(directory):
        for root, _dirs, files in os.walk(directory):
            for f in files:
                paths.append(os.path.join(root, f))
        paths.append(directory)
    return sorted(paths)


def normalize_geometry_args(geometry, width=None, height=None, radius=None):
    """Validate detector-geometry arguments and return the kwargs add_detector wants.
    Raises ValueError on an invalid combination."""
    if geometry == "rectangle":
        if width is None or height is None:
            raise ValueError("rectangle geometry requires --width and --height")
        return {"detector_geometry": "rectangle", "detector_width": width,
                "detector_height": height, "detector_radius": None}
    if geometry == "circle":
        if radius is None:
            raise ValueError("circle geometry requires --radius")
        return {"detector_geometry": "circle", "detector_width": None,
                "detector_height": None, "detector_radius": radius}
    if geometry in (None, "polygon", "footprint"):
        # Use the Treasure Map footprint polygon as-is.
        return {"detector_geometry": None, "detector_width": None,
                "detector_height": None, "detector_radius": None}
    raise ValueError("Unknown geometry: %r (use rectangle, circle, or polygon)" % geometry)


def build_setup_steps(skip_glade=False, skip_init=False, skip_pickles=False, is_debug=True):
    """Ordered (label, argv) list for the one-time install, matching the documented
    sequence: GLADE upload -> initialize_teglon (all flags) -> build_init_pickles. Pure."""
    steps = []
    if not skip_glade:
        steps.append((
            "Upload GLADE galaxy catalog",
            [os.path.join("web", "src", "utilities", "bulk_upload_glade.py")],
        ))
    if not skip_init:
        init = [os.path.join("web", "src", "utilities", "initialize_teglon.py")]
        if is_debug:
            init.append("--is_debug")
        init += [
            "--build_skydistances", "--build_skypixels", "--build_detectors",
            "--build_TM_detectors", "--build_bands", "--build_MWE",
            "--build_galaxy_skypixel_associations", "--build_completeness",
            "--compose_completeness", "--build_static_grids",
        ]
        steps.append(("Initialize Teglon core tables", init))
    if not skip_pickles:
        steps.append((
            "Build pickle caches",
            [os.path.join("web", "src", "utilities", "build_init_pickles.py"),
             "--build_skypixels_pickle", "--build_ebv_pickle",
             "--build_composed_completeness_pickle"],
        ))
    return steps


def reweighted_output_path(gw_id, healpix_dir, healpix_file):
    """Path of the exported galaxy-reweighted (4D) skymap for an event."""
    return os.path.join(event_dir(gw_id, healpix_dir),
                        "%s_4D_reweighted_%s" % (gw_id, healpix_file))


def reconstruct_reweighted_map(pixel_rows, nside, prob_index=4, pixindex_index=2):
    """Build a full-sky probability array from HealpixPixel/Completeness DB rows.

    Each row places `row[prob_index]` (NetPixelProb) at HEALPix index
    `row[pixindex_index]` (Pixel_Index). Mirrors plot_teglon's map_4d_pix
    reconstruction. Uses numpy only (npix = 12*nside^2), so it is unit-testable
    without healpy or a database."""
    import numpy as np

    nside = int(nside)
    npix = 12 * nside * nside
    arr = np.zeros(npix)
    for r in pixel_rows:
        idx = int(r[pixindex_index])
        if 0 <= idx < npix:
            arr[idx] = float(r[prob_index])
    return arr


# Area of the full sky in square degrees ( = 4*pi sr ). One HEALPix pixel is this
# divided by npix, which equals healpy.nside2pixarea(nside, degrees=True) exactly
# but needs no healpy import (keeps `credible_areas` unit-testable on the host).
_FULL_SKY_DEG2 = 4.0 * 180.0 * 180.0 / 3.141592653589793  # 41252.961249419...


def credible_areas(prob, levels=(0.5, 0.9, 0.99)):
    """Credible-region areas (sq deg) of a HEALPix probability map.

    For each level L, returns the area of the smallest set of pixels whose summed
    probability reaches L. The map is normalized to unit total first, so the result
    is a proper credible region regardless of the map's absolute normalization
    (e.g. a galaxy-reweighted map whose pixels sum to < 1). numpy-only, so it is
    unit-testable without healpy. Uses the same method (and the same pixel area) as
    `compare`, so the values agree with the reported credible areas.
    """
    import numpy as np

    p = np.nan_to_num(np.asarray(prob, dtype=float), nan=0.0)
    total = float(p.sum())
    if total > 0:
        p = p / total
    pix_area_deg2 = _FULL_SKY_DEG2 / p.size
    cumulative = np.cumsum(np.sort(p)[::-1])  # descending cumulative probability
    return {lev: float(np.sum(cumulative <= lev)) * pix_area_deg2 for lev in levels}


def check_info_skymap(skymap_fits_file, levels=(0.5, 0.9, 0.99)):
    """Read a HEALPix skymap FITS and return its credible-region areas (sq deg).

    Reads the PROB column (field 0) with healpy and computes the areas for `levels`
    (default 50%, 90%, 99%). Works on both an original LIGO localization map and the
    Teglon galaxy-reweighted map exported by `trigger`. Returns
    {file, nside, npix, areas={level: area_sqdeg}}.
    """
    import healpy as hp

    prob = hp.read_map(skymap_fits_file, field=0)
    npix = len(prob)
    return {
        "file": skymap_fits_file,
        "nside": int(hp.npix2nside(npix)),
        "npix": int(npix),
        "areas": credible_areas(prob, levels=levels),
    }


# --- pipeline stages (call Teglon methods directly) --------------------------
def _teglon():
    # Imported lazily so `teglon --help` is fast and does not require the DB.
    from web.src.services.teglon import Teglon

    return Teglon()


def cmd_load_map(args):
    _teglon().load_map(
        gw_id=args.gw_id,
        healpix_dir=args.healpix_dir,
        healpix_file=args.healpix_file,
        analysis_mode=args.analysis_mode,
        clobber=args.clobber,
        skip_swope=args.skip_swope,
        skip_thacher=args.skip_thacher,
        skip_t80=args.skip_t80,
        skip_newfirm=args.skip_newfirm,
        t_0_override=getattr(args, "t0", None),
    )
    return 0


def cmd_extract(args):
    _teglon().extract_tiles(
        gw_id=args.gw_id,
        healpix_dir=args.healpix_dir,
        healpix_file=args.healpix_file,
        tele=args.tele,
        band=args.band,
        extinct=args.extinct,
        prob_type=args.prob_type,
        cum_prob=args.cum_prob,
        num_tiles=args.num_tiles,
        min_ra=args.min_ra,
        max_ra=args.max_ra,
        min_dec=args.min_dec,
        max_dec=args.max_dec,
    )
    return 0


def cmd_plot(args):
    _teglon().plot_teglon(
        gw_id=args.gw_id,
        healpix_dir=args.healpix_dir,
        healpix_file=args.healpix_file,
        tele=args.tele,
        band=args.band,
        extinct=args.extinct,
        tile_file=args.tile_file,
        num_tiles=args.num_tiles,
        cum_prob_outer=args.cum_prob_outer,
        cum_prob_inner=args.cum_prob_inner,
    )
    return 0


def cmd_run(args):
    """Full planning pipeline for one GW event: load -> extract -> plot.

    Synchronous equivalent of teglon_worker_tasks.load_map_batch_process (no Celery)."""
    t = _teglon()

    _banner("[1/3] Loading map for %s ..." % args.gw_id)
    t.load_map(
        gw_id=args.gw_id,
        healpix_dir=args.healpix_dir,
        healpix_file=args.healpix_file,
        analysis_mode=args.analysis_mode,
        clobber=args.clobber,
        skip_swope=args.skip_swope,
        skip_thacher=args.skip_thacher,
        skip_t80=args.skip_t80,
        skip_newfirm=args.skip_newfirm,
        t_0_override=getattr(args, "t0", None),
    )

    _banner("[2/3] Extracting tiles for %s ..." % args.gw_id)
    t.extract_tiles(
        gw_id=args.gw_id,
        healpix_dir=args.healpix_dir,
        healpix_file=args.healpix_file,
        tele=args.tele,
        extinct=args.extinct,
        prob_type=args.prob_type,
        cum_prob=args.cum_prob,
        num_tiles=args.num_tiles,
    )

    if not args.no_plot:
        _banner("[3/3] Plotting %s ..." % args.gw_id)
        t.plot_teglon(
            gw_id=args.gw_id,
            healpix_dir=args.healpix_dir,
            healpix_file=args.healpix_file,
        )
    else:
        print("[3/3] Skipping plot (--no-plot).")

    _banner("Done. Output is in %s" % args.healpix_dir.replace("{GWID}", args.gw_id))
    return 0


# --- wrappers around standalone scripts --------------------------------------
def cmd_load_obs(args):
    extra = [
        "--gw_id", args.gw_id,
        "--healpix_file", args.healpix_file,
        "--healpix_dir", args.healpix_dir,
        "--tile_dir", args.tile_dir,
        "--tile_file", args.tile_file,
    ]
    return _run_script(os.path.join("web", "src", "ingestion", "load_observed_tiles.py"), extra)


def cmd_efficiency(args):
    extra = [
        "--gw_id", args.gw_id,
        "--healpix_file", args.healpix_file,
        "--healpix_dir", args.healpix_dir,
        "--model_type", args.model_type,
        "--num_cpu", str(args.num_cpu),
    ]
    if args.clobber:
        extra.append("--clobber")
    return _run_script(
        os.path.join("web", "src", "analysis", "model_detection_efficiency.py"), extra
    )


def cmd_compare(args):
    extra = [
        "--gw_id", args.gw_id,
        "--healpix_file", args.healpix_file,
        "--healpix_dir", args.healpix_dir,
    ]
    if args.out:
        extra += ["--out", args.out]
    return _run_script(os.path.join("web", "src", "analysis", "compare_skymaps.py"), extra)


def cmd_skymap_info(args):
    """Print the 50%, 90% and 99% credible-region areas of a skymap FITS, computed
    directly from the file with healpy. Works on the original LIGO map and the
    Teglon reweighted map."""
    info = check_info_skymap(args.skymap_fits_file, levels=(0.5, 0.9, 0.99))
    print("SKYMAP_INFO_BEGIN")
    print("file=%s" % info["file"])
    print("nside=%d" % info["nside"])
    print("npix=%d" % info["npix"])
    for lev in (0.5, 0.9, 0.99):
        print("area_%d_sqdeg=%.2f" % (int(round(lev * 100)), info["areas"][lev]))
    print("SKYMAP_INFO_END")
    return 0


# --- fresh-build bootstrap ---------------------------------------------------
def cmd_bootstrap(args):
    """Build a fresh DB from scratch: dust -> GLADE -> detectors -> static grids.

    The schema, stored procedures and users are loaded automatically by the
    `db_init/*.sql` mounts when the MySQL container first starts, so this only
    has to populate the science data.
    """
    if not args.skip_dust:
        _banner("[bootstrap] Initializing SFD dust map (ebv.pkl) ...")
        rc = _run_script(os.path.join("web", "src", "utilities", "initialize_dust.py"), [])
        if rc != 0:
            print("Dust initialization failed (rc=%s). Aborting." % rc)
            return rc

    if not args.skip_galaxies:
        _banner("[bootstrap] Uploading GLADE galaxy catalog ...")
        rc = _run_script(os.path.join("web", "src", "utilities", "bulk_upload_glade.py"), [])
        if rc != 0:
            print("GLADE upload failed (rc=%s). Aborting." % rc)
            return rc

    if args.instruments_config:
        if not os.path.exists(args.instruments_config):
            print("Instruments config not found: %s" % args.instruments_config)
            return 1
        with open(args.instruments_config) as fh:
            instruments = json.load(fh)

        t = _teglon()
        for inst in instruments:
            _banner("[bootstrap] Adding detector + static grid: %s" % inst.get("name", "?"))
            t.add_detector(
                tm_detector_id=inst["tm_detector_id"],
                min_dec=inst.get("min_dec", -90.0),
                max_dec=inst.get("max_dec", 90.0),
                detector_geometry=inst.get("detector_geometry"),
                detector_width=inst.get("detector_width"),
                detector_height=inst.get("detector_height"),
                detector_radius=inst.get("detector_radius"),
            )
            # add_static_grid needs the Teglon detector id; it is looked up by the
            # script normally. We pass the prefix and the TM id resolves on the
            # detector just inserted.
            t.add_static_grid(
                teglon_detector_id=inst["teglon_detector_id"],
                detector_prefix=inst["detector_prefix"],
            )
    else:
        print(
            "\nNo --instruments-config provided: dust + GLADE are loaded, but no\n"
            "detectors/static grids were created. Provide a JSON file (see\n"
            "docs/bootstrap.md and Settings.example.ini) describing each instrument,\n"
            "or add them individually with the existing add_detector.py /\n"
            "add_static_grid.py scripts."
        )
    _banner("[bootstrap] Done.")
    return 0


# --- new feature commands ----------------------------------------------------
def cmd_delete_event(args):
    """Clean a GW event from the DB and/or the filesystem. DRY-RUN by default:
    nothing is removed unless --yes is given."""
    from web.src.utilities.Database_Helpers import query_db

    map_ids = []
    if not args.files_only:
        if args.healpix_file:
            sel = ("SELECT id, Filename FROM HealpixMap WHERE GWID = '%s' AND Filename = '%s'"
                   % (args.gw_id, args.healpix_file))
        else:
            sel = "SELECT id, Filename FROM HealpixMap WHERE GWID = '%s'" % args.gw_id
        rows = query_db([sel])[0]
        map_ids = [(int(r[0]), r[1]) for r in rows]

    directory = event_dir(args.gw_id, args.healpix_dir)
    files = [] if args.db_only else plan_event_file_deletion(directory)

    _banner("Delete plan for event %s" % args.gw_id)
    print("Database maps to remove (%d):" % len(map_ids))
    for mid, fn in map_ids:
        print("  - HealpixMap id=%d  (%s)" % (mid, fn))
    if not args.db_only:
        print("\nFiles/dirs to remove under %s (%d):" % (directory, len(files)))
        for p in files[:20]:
            print("  - %s" % p)
        if len(files) > 20:
            print("  ... and %d more" % (len(files) - 20))

    if not args.yes:
        print("\nDRY RUN -- nothing was deleted. Re-run with --yes to execute.")
        return 0

    if not args.files_only:
        for mid, fn in map_ids:
            print("Deleting HealpixMap id=%d ..." % mid)
            for q in build_delete_map_sql(mid):
                query_db([q], commit=True)
    if not args.db_only and os.path.isdir(directory):
        import shutil
        print("Removing directory %s ..." % directory)
        shutil.rmtree(directory)

    _banner("Deleted event %s." % args.gw_id)
    return 0


def cmd_add_telescope(args):
    """Register a new telescope/detector (e.g. LSST / Vera Rubin) from its Treasure
    Map id, and optionally build its all-sky static tile grid."""
    geo = normalize_geometry_args(args.geometry, args.width, args.height, args.radius)
    t = _teglon()
    _banner("Adding detector (TM id=%s) ..." % args.tm_detector_id)
    t.add_detector(tm_detector_id=args.tm_detector_id, min_dec=args.min_dec,
                   max_dec=args.max_dec, **geo)

    if args.teglon_detector_id is not None and args.prefix is not None:
        _banner("Building static grid for Teglon detector id=%s ..." % args.teglon_detector_id)
        t.add_static_grid(teglon_detector_id=args.teglon_detector_id, detector_prefix=args.prefix)
    else:
        print("\nDetector added. To build its static tile grid, re-run with "
              "--teglon-detector-id <DB id> --prefix <letter> (the DB id is the new "
              "Detector.id; check it with `./teglon dbshell`).")
    return 0


def cmd_setup(args):
    """One-time complete Teglon initialization. DRY-RUN by default: prints the plan;
    add --run to execute (can take ~2-3 hours)."""
    steps = build_setup_steps(skip_glade=args.skip_glade, skip_init=args.skip_init,
                              skip_pickles=args.skip_pickles, is_debug=not args.no_debug)
    _banner("Teglon one-time setup plan (%d steps)" % len(steps))
    for i, (label, argv) in enumerate(steps, 1):
        print("  [%d] %s" % (i, label))
        print("        python %s" % " ".join(argv))

    if not args.run:
        print("\nDRY RUN -- nothing was executed. Re-run with --run to perform setup.")
        return 0

    for i, (label, argv) in enumerate(steps, 1):
        _banner("[setup %d/%d] %s" % (i, len(steps), label))
        rc = _run_script(argv[0], argv[1:])
        if rc != 0:
            print("Step failed (rc=%s): %s. Aborting." % (rc, label))
            return rc
    _banner("Setup complete.")
    return 0


def cmd_trigger(args):
    """Triggering pipeline: ingest + galaxy-reweight a GW skymap and export the
    updated (4D) HEALPix probability map to a FITS file."""
    t = _teglon()
    if not args.no_ingest:
        _banner("[trigger] Ingesting + reweighting %s ..." % args.gw_id)
        t.load_map(gw_id=args.gw_id, healpix_dir=args.healpix_dir,
                   healpix_file=args.healpix_file, clobber=not args.no_clobber,
                   analysis_mode=args.analysis_mode, t_0_override=getattr(args, "t0", None))

    _banner("[trigger] Exporting reweighted skymap ...")
    from web.src.utilities.Database_Helpers import query_db
    import healpy as hp

    sel_map = ("SELECT id, RescaledNSIDE FROM HealpixMap WHERE GWID = '%s' AND Filename = '%s'"
               % (args.gw_id, args.healpix_file))
    mrow = query_db([sel_map])[0][0]
    map_id = int(mrow[0])
    nside = int(mrow[1])

    sel_pix = (
        "SELECT hp.id, hp.HealpixMap_id, hp.Pixel_Index, hp.Prob, hpc.NetPixelProb "
        "FROM HealpixPixel hp JOIN HealpixPixel_Completeness hpc ON hpc.HealpixPixel_id = hp.id "
        "WHERE hp.HealpixMap_id = %d ORDER BY hp.Pixel_Index;" % map_id
    )
    rows = query_db([sel_pix])[0]
    arr = reconstruct_reweighted_map(rows, nside, prob_index=4, pixindex_index=2)

    out_path = reweighted_output_path(args.gw_id, args.healpix_dir, args.healpix_file)
    hp.write_map(out_path, arr, overwrite=True)
    _banner("[trigger] Reweighted skymap written: %s" % out_path)
    return 0


# --- argument wiring ---------------------------------------------------------
def _add_common_event_args(p):
    p.add_argument("gw_id", help="LIGO superevent name, e.g. S230529ay")
    p.add_argument("--healpix-dir", dest="healpix_dir", default="./web/events/{GWID}",
                   help="Directory holding the healpix file. Default: ./web/events/{GWID}")
    p.add_argument("--healpix-file", dest="healpix_file", default="bayestar.fits.gz",
                   help="Healpix filename. Default: bayestar.fits.gz")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="teglon",
        description="Teglon-O4: gravitational-wave follow-up observation planner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p = sub.add_parser("run", help="Full pipeline for a GW event: load -> extract -> plot")
    _add_common_event_args(p)
    p.add_argument("--tele", default="a",
                   help="Telescope: s,t,n,t80,nf,a(ll). Default: a")
    p.add_argument("--extinct", type=float, default=0.5, help="Max extinction (mag). Default: 0.5")
    p.add_argument("--prob-type", dest="prob_type", default="4D", choices=["4D", "2D"],
                   help="Probability type. Default: 4D")
    p.add_argument("--cum-prob", dest="cum_prob", type=float, default=0.9,
                   help="Cumulative probability to cover (0.2-0.95). Default: 0.9")
    p.add_argument("--num-tiles", dest="num_tiles", type=int, default=1000,
                   help="Top N tiles per telescope. Default: 1000")
    p.add_argument("--analysis-mode", dest="analysis_mode", action="store_true",
                   help="Load map at native resolution (no rescale).")
    p.add_argument("--no-clobber", dest="clobber", action="store_false", default=True,
                   help="Do not replace an existing (gw_id, healpix_file) in the DB.")
    p.add_argument("--no-plot", dest="no_plot", action="store_true", help="Skip the plot stage.")
    p.add_argument("--t0", dest="t0", type=float, default=None,
                   help="Event GPS time. Use with a pre-placed local skymap to skip GraceDB "
                        "(required for non-superevents like GW170817).")
    p.add_argument("--skip-swope", dest="skip_swope", action="store_true")
    p.add_argument("--skip-thacher", dest="skip_thacher", action="store_true")
    p.add_argument("--skip-t80", dest="skip_t80", action="store_true")
    p.add_argument("--skip-newfirm", dest="skip_newfirm", action="store_true")
    p.set_defaults(func=cmd_run)

    # load-map
    p = sub.add_parser("load-map", help="Download + ingest a healpix map into the DB")
    _add_common_event_args(p)
    p.add_argument("--analysis-mode", dest="analysis_mode", action="store_true")
    p.add_argument("--no-clobber", dest="clobber", action="store_false", default=True)
    p.add_argument("--t0", dest="t0", type=float, default=None,
                   help="Event GPS time. Use with a pre-placed local skymap to skip GraceDB "
                        "(required for non-superevents like GW170817).")
    p.add_argument("--skip-swope", dest="skip_swope", action="store_true")
    p.add_argument("--skip-thacher", dest="skip_thacher", action="store_true")
    p.add_argument("--skip-t80", dest="skip_t80", action="store_true")
    p.add_argument("--skip-newfirm", dest="skip_newfirm", action="store_true")
    p.set_defaults(func=cmd_load_map)

    # extract
    p = sub.add_parser("extract", help="Extract ranked tile lists from an ingested map")
    _add_common_event_args(p)
    p.add_argument("--tele", default="a")
    p.add_argument("--band", default="r", help="Band (g,r,i,z,I,J). Default: r")
    p.add_argument("--extinct", type=float, default=0.5)
    p.add_argument("--prob-type", dest="prob_type", default="4D", choices=["4D", "2D"])
    p.add_argument("--cum-prob", dest="cum_prob", type=float, default=0.9)
    p.add_argument("--num-tiles", dest="num_tiles", type=int, default=1000)
    p.add_argument("--min-ra", dest="min_ra", type=float, default=-1.0)
    p.add_argument("--max-ra", dest="max_ra", type=float, default=-1.0)
    p.add_argument("--min-dec", dest="min_dec", type=float, default=-1.0)
    p.add_argument("--max-dec", dest="max_dec", type=float, default=-1.0)
    p.set_defaults(func=cmd_extract)

    # plot
    p = sub.add_parser("plot", help="Plot probability map + tiles for a GW event")
    _add_common_event_args(p)
    p.add_argument("--tele", default="a")
    p.add_argument("--band", default="r")
    p.add_argument("--extinct", type=float, default=0.5)
    p.add_argument("--tile-file", dest="tile_file", default="{FILENAME}")
    p.add_argument("--num-tiles", dest="num_tiles", type=int, default=-1)
    p.add_argument("--cum-prob-outer", dest="cum_prob_outer", type=float, default=0.9)
    p.add_argument("--cum-prob-inner", dest="cum_prob_inner", type=float, default=0.5)
    p.set_defaults(func=cmd_plot)

    # load-obs
    p = sub.add_parser("load-obs", help="Ingest community/observed tiles into the DB")
    _add_common_event_args(p)
    p.add_argument("--tile-dir", dest="tile_dir", default="./web/events/{GWID}/observed_tiles")
    p.add_argument("--tile-file", dest="tile_file", required=True,
                   help="File of observed tiles to import.")
    p.set_defaults(func=cmd_load_obs)

    # efficiency
    p = sub.add_parser("efficiency", help="Model transient detection efficiency for an event")
    _add_common_event_args(p)
    p.add_argument("--model-type", dest="model_type", default="kne", help="e.g. kne, grb. Default: kne")
    p.add_argument("--num-cpu", dest="num_cpu", type=int, default=5)
    p.add_argument("--clobber", action="store_true")
    p.set_defaults(func=cmd_efficiency)

    # compare
    p = sub.add_parser("compare",
                       help="Side-by-side 2D vs 4D (galaxy-reweighted) skymap PDF + area metrics")
    _add_common_event_args(p)
    p.add_argument("--out", default=None, help="Output PDF path (default: in the event dir).")
    p.set_defaults(func=cmd_compare)

    # skymap-info
    p = sub.add_parser("skymap-info",
                       help="50/90/99%% credible-region areas of a skymap FITS (healpy)")
    p.add_argument("skymap_fits_file",
                   help="Path to a HEALPix skymap FITS (original LIGO map or a Teglon reweighted map).")
    p.set_defaults(func=cmd_skymap_info)

    # bootstrap
    p = sub.add_parser("bootstrap", help="Build a fresh DB: dust + GLADE (+ optional detectors)")
    p.add_argument("--instruments-config", dest="instruments_config", default=None,
                   help="JSON file describing instruments (detectors + static grids) to create.")
    p.add_argument("--skip-dust", dest="skip_dust", action="store_true")
    p.add_argument("--skip-galaxies", dest="skip_galaxies", action="store_true")
    p.set_defaults(func=cmd_bootstrap)

    # delete-event
    p = sub.add_parser("delete-event",
                       help="Clean a GW event from the DB and files (dry-run unless --yes)")
    _add_common_event_args(p)
    p.add_argument("--yes", action="store_true", help="Actually perform the deletion (otherwise dry-run).")
    p.add_argument("--db-only", dest="db_only", action="store_true", help="Only remove DB records, keep files.")
    p.add_argument("--files-only", dest="files_only", action="store_true", help="Only remove files, keep DB records.")
    p.set_defaults(func=cmd_delete_event, healpix_file=None)

    # add-telescope
    p = sub.add_parser("add-telescope", help="Register a new telescope (e.g. LSST/Vera Rubin)")
    p.add_argument("--tm-detector-id", dest="tm_detector_id", type=int, required=True,
                   help="Treasure Map instrument id for the telescope.")
    p.add_argument("--geometry", default="polygon", choices=["rectangle", "circle", "polygon"],
                   help="FOV geometry. Default: polygon (use the Treasure Map footprint).")
    p.add_argument("--width", type=float, default=None, help="FOV width (deg); rectangle only.")
    p.add_argument("--height", type=float, default=None, help="FOV height (deg); rectangle only.")
    p.add_argument("--radius", type=float, default=None, help="FOV radius (deg); circle only.")
    p.add_argument("--min-dec", dest="min_dec", type=float, default=-90.0)
    p.add_argument("--max-dec", dest="max_dec", type=float, default=90.0)
    p.add_argument("--teglon-detector-id", dest="teglon_detector_id", type=int, default=None,
                   help="DB Detector.id of the new detector; if given with --prefix, also build its static grid.")
    p.add_argument("--prefix", default=None, help="Field-name prefix for the static grid (e.g. 'L').")
    p.set_defaults(func=cmd_add_telescope)

    # setup
    p = sub.add_parser("setup", help="One-time complete initialization (dry-run unless --run)")
    p.add_argument("--run", action="store_true", help="Actually execute setup (otherwise print the plan).")
    p.add_argument("--skip-glade", dest="skip_glade", action="store_true")
    p.add_argument("--skip-init", dest="skip_init", action="store_true")
    p.add_argument("--skip-pickles", dest="skip_pickles", action="store_true")
    p.add_argument("--no-debug", dest="no_debug", action="store_true",
                   help="Omit the --is_debug flag from initialize_teglon.")
    p.set_defaults(func=cmd_setup)

    # trigger
    p = sub.add_parser("trigger",
                       help="Ingest + reweight a skymap and export the updated 4D HEALPix map")
    _add_common_event_args(p)
    p.add_argument("--no-ingest", dest="no_ingest", action="store_true",
                   help="Skip load-map; just export from an already-ingested event.")
    p.add_argument("--no-clobber", dest="no_clobber", action="store_true",
                   help="Do not replace an existing (gw_id, healpix_file) when ingesting.")
    p.add_argument("--analysis-mode", dest="analysis_mode", action="store_true")
    p.add_argument("--t0", dest="t0", type=float, default=None,
                   help="Event GPS time. Use with a pre-placed local skymap to skip GraceDB "
                        "(required for non-superevents like GW170817).")
    p.set_defaults(func=cmd_trigger)

    return parser


def main(argv=None):
    _ensure_repo_root()
    parser = build_parser()
    args = parser.parse_args(argv)
    start = time.time()
    rc = args.func(args)
    print("\n[teglon %s] total execution time: %.1fs" % (args.command, time.time() - start))
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
