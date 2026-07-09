#!/usr/bin/env python
"""Detection-efficiency figure over ANY TWO free parameters of a redback transient model.

Generalizes the two-component-specific `plot_kne2_detection_efficiency.py`: the model's free
parameters are DISCOVERED from the `.prob` ECSV columns (everything except `Prob`), which are
written by `model_detection_efficiency_redback_transients.py`. So this plots detectability for
*any* redback model -- one-/two-/three-component kilonovae, afterglows, SNe -- with no code
changes. Choose the two axes with --x / --y (must be columns in the .prob file).

Collapsing the other free parameters (`--reduce`):
  * scatter (default) -- use every model as an (x, y, Prob) point. Correct for PRIOR-SAMPLED
    banks (n_sim draws): the off-axis parameters are marginalised by the sampling itself.
  * max / mean       -- aggregate Prob over models sharing an (x, y) cell. For GRIDDED banks.
  * fix              -- keep only the slice where each off-axis equals a fixed gridded value.

Ejecta-physics overlays (kinetic-energy contours, NS binding-energy "unphysical" region,
AT2017gfo markers) are drawn only when --x is velocity-like and --y is mass-like.

Run with the redback venv (has astropy + matplotlib):
    ../redback_env/bin/python plot_redback_detection_efficiency.py \\
        --prob-glob '<event>/model_detection/*/Detection_Redback_*.prob' \\
        --x vej_1 --y mej_1 --out fig.png
"""
from __future__ import annotations
import argparse
import glob
import re
from collections import defaultdict

import numpy as np
import astropy.constants as const
from astropy.table import Table, vstack
from scipy.interpolate import griddata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors, ticker
import matplotlib.patheffects as pe

C_CGS = const.c.cgs.value
M_SUN_CGS = const.M_sun.cgs.value
G_CGS = const.G.cgs.value
R_NS_CGS = 20e5  # 20 km

# AT2017gfo components (Villar+2017): (label, velocity, mass, colour)
DEFAULT_REFERENCE_KNE = [
    ("AT2017gfo\nblue", 0.256, 0.023, "deepskyblue"),
    ("AT2017gfo\nred", 0.149, 0.050, "red"),
]

_BASE_SYMBOL = {
    "mej": r"M_{\rm ej}", "mass": r"M_{\rm ej}",
    "vej": r"\beta_{\rm ej}", "velocity": r"\beta_{\rm ej}",
    "kappa": r"\kappa", "temperature_floor": r"T_{\rm floor}",
    "redshift": r"z", "theta_obs": r"\theta_{\rm obs}", "E": r"E", "n": r"n",
}
_BASE_UNIT = {
    "mej": r"\,(M_\odot)", "mass": r"\,(M_\odot)", "kappa": r"\,({\rm cm^2\,g^{-1}})",
    "temperature_floor": r"\,({\rm K})", "n": r"\,({\rm cm^{-3}})",
}


def axis_label(name):
    """Nice LaTeX for known params (with component index), else the raw column name."""
    m = re.match(r"(.+?)_(\d+)$", name)
    base, idx = (m.group(1), m.group(2)) if m else (name, None)
    sym = _BASE_SYMBOL.get(base)
    if sym is None:
        return name.replace("_", r"\_")
    if idx:
        sym = sym + (r"_{%s}" % idx) if "_" not in sym else re.sub(r"}", r",%s}" % idx, sym, count=1)
    return (r"$%s%s$" % (sym, _BASE_UNIT.get(base, ""))).replace("$$", "$")


def is_velocity(name):
    return bool(re.search(r"vej|velocity|beta", name, re.I))


def is_mass(name):
    return bool(re.search(r"mej|mass", name, re.I))


def load_prob_tables(glob_pattern):
    files = sorted(glob.glob(glob_pattern))
    if not files:
        raise SystemExit(f"No .prob files match {glob_pattern!r}")
    tables = [Table.read(f, format="ascii.ecsv") for f in files]
    t = vstack(tables, metadata_conflicts="silent") if len(tables) > 1 else tables[0]
    if "Prob" not in t.colnames:
        raise SystemExit(f"No 'Prob' column in .prob; columns: {t.colnames}")
    params = [c for c in t.colnames if c != "Prob"]
    print(f"Loaded {len(files)} file(s), {len(t)} models; free parameters: {params}")
    return t, params


def nearest_grid_value(values, target):
    uniq = np.unique(values)
    return float(uniq[np.argmin(np.abs(uniq - target))])


def project_to_plane(t, xaxis, yaxis, params, reduce_mode, fix):
    """Collapse to the (xaxis, yaxis) plane. Returns points (N,2), values (N,), handling dict."""
    off = [a for a in params if a not in (xaxis, yaxis)]
    x = np.asarray(t[xaxis], float)
    y = np.asarray(t[yaxis], float)
    prob = np.asarray(t["Prob"], float)

    if reduce_mode == "scatter" or not off:
        return np.column_stack([x, y]), prob, {a: "marginalised (sampled)" for a in off}

    if reduce_mode == "fix":
        mask = np.ones(len(t), bool)
        handling = {}
        for a in off:
            col = np.asarray(t[a], float)
            fv = nearest_grid_value(col, fix.get(a, float(np.median(col))))
            handling[a] = f"fixed≈{fv:.3g}"
            mask &= np.isclose(col, fv)
        return np.column_stack([x[mask], y[mask]]), prob[mask], handling

    agg = defaultdict(list)
    for xi, yi, pi in zip(x, y, prob):
        agg[(xi, yi)].append(pi)
    pts, vals = [], []
    for (xi, yi), pl in agg.items():
        pts.append((xi, yi))
        vals.append(np.max(pl) if reduce_mode == "max" else np.mean(pl))
    return np.asarray(pts), np.asarray(vals), {a: reduce_mode for a in off}


def bound_mass(beta):
    return ((5.0 * R_NS_CGS * C_CGS ** 2) / (3.0 * G_CGS)) * \
           (1.0 / np.sqrt(1.0 - beta ** 2) - 1.0) / M_SUN_CGS


def _line_artists(cs):
    try:
        return cs.collections            # mpl < 3.8
    except AttributeError:
        return [cs]                      # mpl >= 3.10


def add_ejecta_overlays(ax, gx, gy, xmin, xmax, ymin, ymax, reference_kne):
    # kinetic-energy contours
    gamma = 1.0 / np.sqrt(1.0 - np.clip(gx, 0, 0.999) ** 2)
    ke = gy * (gamma - 1.0) * M_SUN_CGS * C_CGS ** 2
    lv = [1e49, 1e50, 1e51, 1e52]
    cs = ax.contour(gx, gy, ke, levels=lv, colors="white", linewidths=1.2,
                    locator=ticker.LogLocator(), zorder=60)
    for a in _line_artists(cs):
        a.set_path_effects([pe.withStroke(linewidth=2.5, foreground="black")])
    lbls = ax.clabel(cs, inline=True, fontsize=11,
                     fmt={l: rf"$10^{{{int(np.log10(l))}}}$ erg" for l in lv})
    plt.setp(lbls, path_effects=[pe.withStroke(linewidth=2.5, foreground="black")])
    # NS binding-energy unphysical region: mass ABOVE the curve exceeds NS binding energy.
    # Fill from the curve up to a high ceiling; the axes are clamped to the data afterward, so
    # this only shows where the curve actually dips into the plotted range.
    bm = bound_mass(gx[0])
    ceiling = max(1.0, ymax * 10.0)
    ax.fill_between(gx[0], bm, ceiling, color="0.5", zorder=50)
    ax.plot(gx[0], bm, "--", color="black", lw=1.5, zorder=51)
    # reference KNe
    for label, vej, mej, colour in reference_kne:
        if xmin <= vej <= xmax and ymin <= mej <= ymax:
            ax.plot(vej, mej, "*", mfc=colour, mec="black", ms=22, mew=1.5, zorder=99)
            ax.annotate(label, (vej, mej), fontsize=11, color="white", ha="center",
                        path_effects=[pe.withStroke(linewidth=6, foreground="black")], zorder=99)


def make_figure(points, values, xaxis, yaxis, args, handling):
    xmin, xmax = points[:, 0].min(), points[:, 0].max()
    ymin, ymax = points[:, 1].min(), points[:, 1].max()

    def mesh(lo, hi, scale):
        lo = lo if lo > 0 else max(hi * 1e-6, 1e-12)
        return (np.logspace(np.log10(lo), np.log10(hi), 400) if scale == "log"
                else np.linspace(lo, hi, 400))
    gx, gy = np.meshgrid(mesh(xmin, xmax, args.xscale), mesh(ymin, ymax, args.yscale))
    grid_prob = np.nan_to_num(griddata(points, values, (gx, gy), method="linear", rescale=True), nan=0.0)
    pct = grid_prob * 100.0
    vmax = max(values.max() * 100.0, 1e-9)
    print(f"Max detection probability on plane: {vmax:.3g}%")

    fig, ax = plt.subplots(figsize=(9, 8), dpi=args.dpi)
    ax.set_xscale(args.xscale)
    ax.set_yscale(args.yscale)

    norm = colors.Normalize(0.0, vmax)
    cf = ax.contourf(gx, gy, pct, levels=np.linspace(0, vmax, 200), cmap="inferno", norm=norm, zorder=10)
    try:
        cf.set_edgecolor("face")
    except Exception:
        pass

    if args.levels:
        lv = [x * 100.0 for x in args.levels if x * 100.0 < vmax]
        if lv:
            cs = ax.contour(gx, gy, pct, levels=lv, colors="mediumturquoise", linewidths=2.0, zorder=70)
            for a in _line_artists(cs):
                a.set_path_effects([pe.withStroke(linewidth=3.0, foreground="black")])
            lbls = ax.clabel(cs, inline=True, fontsize=12, fmt=lambda v: f"{v:g}%")
            plt.setp(lbls, path_effects=[pe.withStroke(linewidth=3.0, foreground="black")])

    if is_velocity(xaxis) and is_mass(yaxis):
        add_ejecta_overlays(ax, gx, gy, xmin, xmax, ymin, ymax, args.reference_kne)

    # points overlay (so the sampling is visible)
    if args.show_points:
        ax.scatter(points[:, 0], points[:, 1], s=8, c="white", edgecolors="black",
                   linewidths=0.3, alpha=0.5, zorder=80)

    # clamp to the data range so the physics overlays don't blow up the view
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)

    sm = plt.cm.ScalarMappable(norm=norm, cmap="inferno")
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, fraction=0.05, pad=0.02)
    cb.set_label("Probability to detect (%)", fontsize=16)
    cb.ax.tick_params(labelsize=13)

    ax.set_xlabel(axis_label(xaxis), fontsize=18)
    ax.set_ylabel(axis_label(yaxis), fontsize=18)
    ax.tick_params(labelsize=14)
    if handling:
        modes = sorted(set(handling.values()))
        how = modes[0] if len(modes) == 1 else "collapsed"
        subtitle = f"{len(handling)} other free param(s) {how}"
    else:
        subtitle = ""
    ax.set_title("\n".join(s for s in (args.event_label, subtitle) if s), fontsize=12)

    fig.savefig(args.out, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {args.out}")


def parse_fix(items):
    out = {}
    for it in items or []:
        k, v = it.split("=")
        out[k.strip()] = float(v)
    return out


def parse_reference(items):
    if items is None:
        return list(DEFAULT_REFERENCE_KNE)
    out = []
    for it in items:
        p = it.split(",")
        out.append((p[0], float(p[1]), float(p[2]), p[3] if len(p) > 3 else "white"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prob-glob", required=True, help="glob for input .prob ECSV file(s)")
    ap.add_argument("--out", default="redback_detection_efficiency.png")
    ap.add_argument("--x", dest="xaxis", required=True, help="free-param column for the x-axis")
    ap.add_argument("--y", dest="yaxis", required=True, help="free-param column for the y-axis")
    ap.add_argument("--reduce", default="scatter", choices=["scatter", "max", "mean", "fix"])
    ap.add_argument("--fix", nargs="*", help="off-axis fixes for --reduce fix, e.g. mej_2=0.03")
    ap.add_argument("--levels", type=float, nargs="*", default=[0.01, 0.05, 0.10, 0.30],
                    help="probability contour levels as fractions (0.05 = 5%%)")
    ap.add_argument("--xscale", default="log", choices=["log", "linear"])
    ap.add_argument("--yscale", default="log", choices=["log", "linear"])
    ap.add_argument("--event-label", default="")
    ap.add_argument("--add-kne", nargs="*", help="reference KN 'label,vej,mej[,colour]' (repeatable)")
    ap.add_argument("--show-points", action="store_true", help="overlay the sampled models")
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    args.fix = parse_fix(args.fix)
    args.reference_kne = parse_reference(args.add_kne)

    t, params = load_prob_tables(args.prob_glob)
    for ax_name in (args.xaxis, args.yaxis):
        if ax_name not in params:
            raise SystemExit(f"--x/--y '{ax_name}' is not a free parameter. Choose from: {params}")
    if args.xaxis == args.yaxis:
        raise SystemExit("--x and --y must differ")

    points, values, handling = project_to_plane(t, args.xaxis, args.yaxis, params, args.reduce, args.fix)
    if len(points) < 4:
        raise SystemExit(f"Only {len(points)} points after projection; need >=4 to interpolate.")
    print(f"Plane {args.xaxis} x {args.yaxis}: {len(points)} points; off-axes -> {handling}")
    make_figure(points, values, args.xaxis, args.yaxis, args, handling)


if __name__ == "__main__":
    main()
