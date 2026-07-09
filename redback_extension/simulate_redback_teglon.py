#!/usr/bin/env python
"""simulate_redback_teglon.py — model-agnostic redback -> TEGLON model-bank generator.

Give the name of *any* redback photometric model; this draws N_SIM samples from its
DEFAULT redback prior and writes each as a TEGLON-format ECSV .dat file (30 columns:
time + 29 bands, absolute AB magnitude, redback-native comment), binned into numbered
folders — a drop-in model bank for TEGLON's model_detection_efficiency analysis.

Why sampling (not a grid): redback models can have many parameters (e.g.
three_component_kilonova_model has ~13); a regular grid is infeasible, N_SIM prior draws
are not. Parameters + prior are introspected from redback at runtime, so this works for
any model without code changes.

Absolute magnitude: redback returns *apparent* AB mag (redshift-aware, Planck18). We pin
`redshift` to a small z_ref and subtract the distance modulus -> rest-frame absolute mag;
TEGLON applies the real distance/extinction downstream (exactly as for the villar KNe).

Run with the redback venv:
    ../redback_env/bin/python simulate_redback_teglon.py three_component_kilonova_model \\
        --n-sim 2000 --outdir ../../teglon_O4/web/models/kne_3comp
"""
from __future__ import annotations
import argparse
import inspect
import logging
import os
import re
import sys

import numpy as np

from astropy.table import Table

# --- TEGLON light-curve schema + band map (self-contained; identical to the engine) ---
BAND_COLS = [
    "swift_uvot_uvw2", "swift_uvot_uvm2", "swift_uvot_uvw1", "swift_uvot_U",
    "swift_uvot_B", "swift_uvot_V", "swift_uvot_W",
    "johnson_U", "johnson_B", "johnson_V", "johnson_R", "johnson_I",
    "sdss_u", "sdss_g", "sdss_r", "sdss_i", "sdss_z",
    "PS1_g", "PS1_r", "PS1_i", "PS1_z", "PS1_Y", "PS1_w",
    "ATLAS_c", "ATLAS_o",
    "ukirt_J", "ukirt_H", "ukirt_K",
    "Clear",
]
ALL_COLS = ["time"] + BAND_COLS
# TEGLON band -> redback/sncosmo bandpass (redback 1.17 filters.csv); UKIRT~2MASS, Clear~gaia::G.
BAND_TO_SNCOSMO = {
    "swift_uvot_uvw2": "uvot::uvw2", "swift_uvot_uvm2": "uvot::uvm2",
    "swift_uvot_uvw1": "uvot::uvw1", "swift_uvot_U": "uvot::u",
    "swift_uvot_B": "uvot::b", "swift_uvot_V": "uvot::v", "swift_uvot_W": "uvot::white",
    "johnson_U": "bessellux", "johnson_B": "bessellb", "johnson_V": "bessellv",
    "johnson_R": "bessellr", "johnson_I": "besselli",
    "sdss_u": "sdssu", "sdss_g": "sdssg", "sdss_r": "sdssr", "sdss_i": "sdssi", "sdss_z": "sdssz",
    "PS1_g": "ps1::g", "PS1_r": "ps1::r", "PS1_i": "ps1::i", "PS1_z": "ps1::z",
    "PS1_Y": "ps1::y", "PS1_w": "ps1::w",
    "ATLAS_c": "atlasc", "ATLAS_o": "atlaso",
    "ukirt_J": "2massj", "ukirt_H": "2massh", "ukirt_K": "2massks",
    "Clear": "gaia::G",
}


def build_time_grid(tmin, tmax, ntime):
    """Log-spaced rest-frame time grid (matches the villar KNe: 0.001-150 d, 401 pts)."""
    return np.logspace(np.log10(tmin), np.log10(tmax), ntime)


def absolute_mag_lightcurves(fn, params, times, mu):
    """{band_col: absolute-mag array} for one parameter set; one redback call per band.
    Non-emitting / undefined epochs -> 99.0 (finite, undetectable)."""
    t = np.clip(np.asarray(times, dtype=float), 1e-3, None)  # redback KN undefined at t<=0
    out = {}
    for bcol in BAND_COLS:
        app = np.asarray(fn(t, output_format="magnitude", bands=[BAND_TO_SNCOSMO[bcol]], **params),
                         dtype=float)
        absmag = app - mu
        out[bcol] = np.where(np.isfinite(absmag), absmag, 99.0)
    return out


def write_teglon_dat(path, times, band_data, comment_meta):
    """Write one ECSV .dat in TEGLON's exact format (30 cols, comment-meta list)."""
    data = [np.asarray(times, dtype=float)] + \
           [np.asarray(band_data[b], dtype=float) for b in BAND_COLS]
    tab = Table(data, names=ALL_COLS)
    tab.meta["comment"] = comment_meta
    tab.write(path, overwrite=True, format="ascii.ecsv")


def resolve_model(name, all_models_dict):
    """Return (canonical_name, fn); accept a name with or without the _model suffix."""
    for candidate in (name, name + "_model"):
        if candidate in all_models_dict:
            return candidate, all_models_dict[candidate]
    near = sorted(m for m in all_models_dict if name.replace("_model", "") in m)
    raise SystemExit(f"Unknown redback model {name!r}. Closest matches:\n  " +
                     "\n  ".join(near[:12] or ["(none)"]))


def model_param_names(fn):
    """Parameters the model function accepts, excluding `time` and **kwargs."""
    return [p.name for p in inspect.signature(fn).parameters.values()
            if p.name != "time" and p.kind != p.VAR_KEYWORD]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="redback model name, e.g. three_component_kilonova_model")
    ap.add_argument("--outdir", required=True, help="output root (numbered subdirs created inside)")
    ap.add_argument("--n-sim", type=int, default=2000, help="number of prior samples to simulate")
    ap.add_argument("--prefix", default=None, help="filename prefix (default: model name sans _model)")
    ap.add_argument("--z-ref", type=float, default=1e-3, help="reference redshift for abs-mag conversion")
    ap.add_argument("--tmin", type=float, default=1e-3)
    ap.add_argument("--tmax", type=float, default=150.0)
    ap.add_argument("--ntime", type=int, default=401)
    ap.add_argument("--bin-size", type=int, default=50, help="files per numbered subdir")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for reproducible sampling")
    ap.add_argument("--limit", type=int, default=0, help="cap sims (validation); 0 = use --n-sim")
    args = ap.parse_args()

    for noisy in ("redback", "bilby", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    import redback  # noqa: F401
    from redback.model_library import all_models_dict
    from redback.priors import get_priors
    from astropy.cosmology import Planck18

    model, fn = resolve_model(args.model, all_models_dict)
    prior = get_priors(model=model)
    sig_params = model_param_names(fn)

    n = args.limit or args.n_sim
    np.random.seed(args.seed)
    samples = prior.sample(n)                       # {name: array(n)}
    if "redshift" in sig_params:                    # pin redshift -> absolute mag
        samples["redshift"] = np.full(n, args.z_ref)

    sampled = [p for p in sig_params if p in samples]
    defaulted = [p for p in sig_params if p not in samples]
    mu = float(Planck18.distmod(args.z_ref).value)
    times = build_time_grid(args.tmin, args.tmax, args.ntime)
    prefix = args.prefix or re.sub(r"_model$", "", model)

    print(f"model={model}  n_sim={n}  z_ref={args.z_ref}  mu={mu:.3f}")
    print(f"sampled from prior: {sampled}")
    if defaulted:
        print(f"using redback defaults for: {defaulted}")

    os.makedirs(args.outdir, exist_ok=True)
    for i in range(n):
        params = {k: float(samples[k][i]) for k in sampled}
        band_data = absolute_mag_lightcurves(fn, params, times, mu)
        comment = [f"type = {model}"] + [f"{k} = {params[k]}" for k in sampled]
        sub = os.path.join(args.outdir, str(i // args.bin_size + 1))
        os.makedirs(sub, exist_ok=True)
        write_teglon_dat(os.path.join(sub, f"{prefix}_{i:05d}.dat"), times, band_data, comment)
        if i % 50 == 0 or i == n - 1:
            print(f"  [{i + 1}/{n}] {prefix}_{i:05d}.dat")
    print(f"Done. {n} model .dat files under {args.outdir}")


if __name__ == "__main__":
    main()
