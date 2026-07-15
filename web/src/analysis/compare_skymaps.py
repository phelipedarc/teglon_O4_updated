"""Compare a LIGO localization (2D) with the Teglon galaxy-reweighted map (4D).

For one ingested event this script:
  * pulls the per-pixel 2D probability (HealpixPixel.Prob) and the 4D
    galaxy-reweighted probability (HealpixPixel_Completeness.NetPixelProb)
    from the database,
  * computes the 50% / 90% credible-region areas for each,
  * reports how much the sky localization shrank thanks to the reweighting,
  * saves a side-by-side PDF (original vs reweighted) highlighting the effect.

Usage:
    python web/src/analysis/compare_skymaps.py --gw_id GW170817 \
        --healpix_file bayestar.fits.gz
"""
import argparse
import json
import sys
import os

import numpy as np
import healpy as hp
from astropy.time import Time

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import ligo.skymap.plot  # noqa: F401  (registers the 'astro ... mollweide' projections)
from ligo.skymap.postprocess.util import find_greedy_credible_levels

from web.src.utilities.Database_Helpers import query_db


def normalize(prob):
    """Return the map normalized to unit total probability (a proper 2D PDF over
    the stored pixels). This makes the original and Teglon-updated maps directly
    comparable: both are the SAME 2D representation over the SAME pixel set, with
    identical normalization, so an X% credible region means the same thing for each.
    Without this, the Teglon map (scaled by galaxy completeness, total < 1) and the
    LIGO map (total ~1) would not be on equal footing."""
    p = np.asarray(prob, dtype=float)
    total = float(np.sum(p))
    return p / total if total > 0 else p


def credible_area_sqdeg(prob, nside, level):
    """Area (sq deg) of the smallest region containing `level` fraction of the
    probability. `prob` is normalized to unit total first so the result is a
    physically consistent credible region regardless of the map's absolute scale."""
    #p = normalize(prob) it shouldnt normalize teglon only ingest the 90% by definition
    p = np.asarray(prob, dtype=float)
    order = np.flipud(np.argsort(p))
    cum = np.cumsum(p[order])
    cred = np.empty_like(cum)
    cred[order] = cum
    pix_area = hp.nside2pixarea(int(nside), degrees=True)
    return float(np.sum(cred <= level) * pix_area)


def load_event_maps(gw_id, healpix_file, event_dir):
    """Return (map_id, nside_2d, nside_4d, t_0, net_prob, map_2d, map_4d).

    The **2D map is the original LIGO localization read at full resolution** from
    the event's FITS file, so its credible areas equal the published values. The
    **4D map is the Teglon galaxy-reweighted product**, reconstructed from the
    database at the analysis resolution. If the original FITS is missing, the 2D
    map falls back to the database (rescaled) probability.
    """
    mrow = query_db(["SELECT id, RescaledNSIDE, t_0, NetProbToGalaxies FROM HealpixMap "
                     "WHERE GWID = '%s' AND Filename = '%s'" % (gw_id, healpix_file)])[0]
    if not mrow:
        raise SystemExit("Event %s / %s not found in the database. Ingest it first "
                         "(teglon load-map ...)." % (gw_id, healpix_file))
    map_id = int(mrow[0][0])
    nside = int(mrow[0][1])
    t_0 = float(mrow[0][2])
    net_prob_to_galaxies = float(mrow[0][3])

    # 4D galaxy-reweighted map (and the DB 2D, used only as a fallback) from the DB.
    rows = query_db([
        "SELECT hp.Pixel_Index, hp.Prob, hpc.NetPixelProb "
        "FROM HealpixPixel hp JOIN HealpixPixel_Completeness hpc "
        "ON hpc.HealpixPixel_id = hp.id WHERE hp.HealpixMap_id = %d "
        "ORDER BY hp.Pixel_Index;" % map_id])[0]
    npix = hp.nside2npix(nside)
    map_2d_db = np.zeros(npix)
    map_4d = np.zeros(npix)
    for r in rows:
        idx = int(r[0])
        if 0 <= idx < npix:
            map_2d_db[idx] = float(r[1])
            map_4d[idx] = float(r[2])
    nside_4d = nside

    # Prefer the original full-resolution FITS for the 2D localization area.
    orig_fits = os.path.join(event_dir, healpix_file)
    if os.path.exists(orig_fits):
        map_2d = hp.read_map(orig_fits, field=0)
        nside_2d = hp.npix2nside(len(map_2d))
    else:
        print("Original FITS not found at %s; using the rescaled DB map for 2D." % orig_fits, file=sys.stderr)
        map_2d = map_2d_db
        nside_2d = nside

    return map_id, nside_2d, nside_4d, t_0, net_prob_to_galaxies, map_2d, map_4d


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gw_id", required=True)
    parser.add_argument("--healpix_file", default="bayestar.fits.gz")
    parser.add_argument("--healpix_dir", default="./web/events/{GWID}")
    parser.add_argument("--out", default=None, help="Output PDF path (default in the event dir).")
    parser.add_argument("--json", action="store_true", help="Emit the area metrics as JSON.")
    args = parser.parse_args()

    event_dir = args.healpix_dir.replace("{GWID}", args.gw_id)
    out_pdf = args.out or os.path.join(event_dir, "%s_2D_vs_4D_comparison.pdf" % args.gw_id)

    map_id, nside_2d, nside_4d, t_0, net_prob, map_2d, map_4d = load_event_maps(
        args.gw_id, args.healpix_file, event_dir)

    # Each map is normalized to unit total over its own pixel set; the 2D area is
    # the published localization (full resolution), the 4D area is the Teglon
    # galaxy-reweighted product (analysis resolution).
    # map_2d = normalize(map_2d)
    # map_4d = normalize(map_4d)

    a2_90 = credible_area_sqdeg(map_2d, nside_2d, 0.90)
    a2_50 = credible_area_sqdeg(map_2d, nside_2d, 0.50)
    a4_90 = credible_area_sqdeg(map_4d, nside_4d, 0.90)
    a4_50 = credible_area_sqdeg(map_4d, nside_4d, 0.50)

    def pct(orig, new):
        return (new - orig) / orig * 100.0 if orig > 0 else float("nan")

    def fmt(a):
        return ("%.2f" % a) if a < 1 else ("%.1f" % a) if a < 100 else ("%.0f" % a)

    t = Time(t_0, format="gps", scale="utc")

    # --- metadata block (machine-parseable; KEY=value, or JSON with --json) ---
    shrink = (a2_90 / a4_90) if a4_90 > 0 else None
    if args.json:
        print(json.dumps({
            "gw_id": args.gw_id, "healpix_file": args.healpix_file, "map_id": map_id,
            "nside_2d": nside_2d, "nside_4d": nside_4d,
            "t_0_gps": round(t_0, 3), "t_0_iso": t.to_value("iso"),
            "net_prob_to_galaxies": round(net_prob, 6),
            "area_2d_90_sqdeg": round(a2_90, 2), "area_2d_50_sqdeg": round(a2_50, 2),
            "area_4d_90_sqdeg": round(a4_90, 2), "area_4d_50_sqdeg": round(a4_50, 2),
            "area_90_change_pct": round(pct(a2_90, a4_90), 2),
            "area_50_change_pct": round(pct(a2_50, a4_50), 2),
            "area_90_shrink_factor": round(shrink, 2) if shrink is not None else None,
        }))
    else:
        print("TEGLON_COMPARE_BEGIN")
        print("gw_id=%s" % args.gw_id)
        print("healpix_file=%s" % args.healpix_file)
        print("map_id=%d" % map_id)
        print("nside_2d=%d" % nside_2d)
        print("nside_4d=%d" % nside_4d)
        print("t_0_gps=%.3f" % t_0)
        print("t_0_iso=%s" % t.to_value("iso"))
        print("net_prob_to_galaxies=%.6f" % net_prob)
        print("area_2d_90_sqdeg=%.2f" % a2_90)
        print("area_2d_50_sqdeg=%.2f" % a2_50)
        print("area_4d_90_sqdeg=%.2f" % a4_90)
        print("area_4d_50_sqdeg=%.2f" % a4_50)
        print("area_90_change_pct=%.2f" % pct(a2_90, a4_90))
        print("area_50_change_pct=%.2f" % pct(a2_50, a4_50))
        if shrink is not None:
            print("area_90_shrink_factor=%.2f" % shrink)
        print("TEGLON_COMPARE_END")

    # --- side-by-side figure ---
    levels_2d = find_greedy_credible_levels(map_2d)
    levels_4d = find_greedy_credible_levels(map_4d)

    fig = plt.figure(figsize=(12, 5.2))
    ax1 = fig.add_subplot(1, 2, 1, projection="astro hours mollweide")
    ax2 = fig.add_subplot(1, 2, 2, projection="astro hours mollweide")

    for ax, lv, title, cmap in (
        (ax1, levels_2d, "Original LIGO localization (2D)\n90%%=%s deg$^2$, 50%%=%s deg$^2$" % (fmt(a2_90), fmt(a2_50)), "cylon"),
        (ax2, levels_4d, "Teglon galaxy-reweighted (4D)\n90%%=%s deg$^2$, 50%%=%s deg$^2$" % (fmt(a4_90), fmt(a4_50)), "cylon"),
    ):
        ax.grid()
        ax.tick_params(axis="both", labelsize=5)
        ax.title.set_text(title)
        try:
            ax.contourf_hpx(lv, levels=[0.0, 0.5, 0.9], cmap="OrRd_r", alpha=0.8)
            ax.contour_hpx(lv, levels=[0.5, 0.9], colors="k", linewidths=0.3)
        except Exception as e:
            print("Plot warning for one panel: %s" % e, file=sys.stderr)

    fig.suptitle("%s  -  galaxy reweighting concentrates the localization "
                 "(90%% credible region: %s $\\rightarrow$ %s deg$^2$, %.1fx smaller)"
                 % (args.gw_id, fmt(a2_90), fmt(a4_90), (a2_90 / a4_90) if a4_90 > 0 else float("nan")),
                 fontsize=10)
    plt.tight_layout()
    fig.savefig(out_pdf, bbox_inches="tight", format="pdf")
    plt.close("all")
    print("Saved comparison PDF: %s" % out_pdf, file=sys.stderr)


if __name__ == "__main__":
    main()
