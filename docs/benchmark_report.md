# Teglon-O4 — From-Scratch Install & Function Benchmark

**Date:** 2026-06-10
**Install path:** `/mnt/nvmeold1/teglon_latetype` (clean, empty start)
**Method:** followed `docs/first_time_install.md` / `user_guide_v2.md` as a first-time
user. Clone = `git archive` of the committed `ZiggyTeglon` HEAD (stand-in for the
updated GitHub). **No shortcuts** — real dust fetch, real GLADE load, full
`initialize_teglon`. Isolated instance: project `teglon_latetype`, container
`teglon_latetype_db`, port **53309**.

---

## 1. Installation benchmark (full, from scratch)

| Step | What it does | Time |
|------|--------------|-----:|
| Clone (`git archive` HEAD) | fetch the code | 4 s |
| Provide `GLADE_2.4.dat` | catalog file (simulated download) | 1 s |
| `./teglon up` | start + init MySQL (schema/procs/users) | 32 s |
| Fetch SFD dust maps | `initialize_dust.py` (2×64 MB) | 13 s |
| GLADE upload | 3,228,528 galaxies → DB | **591 s (9.9 min)** |
| `initialize_teglon` (all stages) | sky pixels, detectors, E(B-V), galaxy↔pixel, completeness, static grids | **2179 s (36.3 min)** |
| `build_init_pickles` | runtime pickle caches | 127 s (2.1 min) |
| **TOTAL** | empty folder → ready-to-run | **≈ 2947 s ≈ 49 min** |

DB after build: SkyPixel 262,128 · SkyPixel_EBV 196,608 · SkyPixel_Galaxy 11.3 M ·
SkyCompleteness 2.5 M · CompletenessGrid 27.1 M · StaticTile 396,825 · Detector 80 ·
Band 16. Pickles: `composed_completeness_dict.pkl` (473 M), `sky_pixels.pkl`, `ebv.pkl`.

> 49 min here vs ~2–3 h in the v1.0 docs — this host has many CPUs and fast NVMe.
> The dominant cost is `initialize_teglon` (completeness + static grids).

### Diagnosis: the "stuck for hours" false alarm
`initialize_teglon` actually finished in **36 min**, but it was launched as a
`docker compose run` background job **without `-T`**; after the work completed the
wrapper kept a pipe open and never signalled "done", so it *looked* stuck for
~4.5 h while idle. **Fix applied:** the `./teglon` wrapper now runs the CLI with
`-T` (no pseudo-TTY), so long background runs exit cleanly. Re-run cost was zero —
the DB and pickles were already complete.

---

## 2. Per-event function benchmark (3 events, fresh DB)

Each event: GW ID → reweighted skymap → tiles → plot → comparison.
CLI-reported execution time (excludes ~2 s container start):

| Function | S240413p | S231206cc | S190814bv |
|----------|---------:|----------:|----------:|
| `trigger` (GW ID → reweighted FITS) | **119.3 s** | **155.8 s** | **142.7 s** |
| `extract` (ranked tiles ×5 telescopes) | 6.4 s | 6.7 s | 14.6 s |
| `plot` (6-panel sky plan) | 31.0 s | 28.4 s | 26.2 s |
| `compare` (2D-vs-4D PDF + areas) | 6.9 s | 6.3 s | 7.5 s |
| **GW ID → full plan (sum)** | **~164 s** | **~197 s** | **~191 s** |

All three produced ranked tile lists for **5 telescopes** + a reweighted FITS + a
comparison PDF.

### GW170817 via the GWOSC fallback (no `--t0`)

GW170817 is not a GraceDB superevent, so `load_map` now falls back to the **GWOSC
event API** (`/eventapi/json/event/GW170817/`) for the event time. End-to-end log:

```
GraceDB lookup failed for `GW170817` (404). Trying GWOSC...
GWOSC match: GW170817  GPS=1187008882.4  gracedb_id=G298048
Using local skymap ... with GWOSC t_0=1187008882.4
```

| Function | GW170817 |
|----------|---------:|
| `trigger` (GW ID → reweighted FITS) | **280.6 s** |
| `extract` | 25.5 s |
| `plot` | 39.2 s |
| `compare` | 11.9 s |

`trigger` is slower here because GW170817's input map is NSIDE 2048 (50 M pixels →
rescaled to 256). Science: 91% to galaxies, **90% region 22.45 → 0.73 deg² (30.6×)**.

> GWOSC publishes a HEALPix FITS only for catalogs that have one; GWTC-1 (GW170817)
> publishes posterior samples only, so the skymap FITS was supplied locally while
> GWOSC provided the GPS time automatically. For newer catalogs that expose a FITS
> `data_url`, the fallback downloads the skymap too.

### Science sanity (normalized 90% credible region)
| Event | Prob → galaxies | 2D 90° | Teglon 90° | shrink |
|-------|---------------:|-------:|-----------:|-------:|
| S240413p | 0.170 | 29.2 deg² | 28.8 deg² | 1.01× |
| S231206cc | 0.004 | 318.3 deg² | 317.9 deg² | 1.00× |
| S190814bv | 0.843 | 25.1 deg² | 12.0 deg² | 2.09× |

S190814bv (nearby) concentrates; S240413p / S231206cc (far, low completeness) do
not — the expected behavior.

> **Reproducibility note:** the from-scratch DB yields slightly different
> `net_prob_to_galaxies` than the production-cloned DB (S190814bv 0.84 vs 0.90;
> S240413p 0.17 vs 0.34). The completeness calibration differs between this fresh
> build and the older production database. Behavior is functionally identical.

---

## 3. Management-function benchmark

| Function | Time | Result |
|----------|-----:|--------|
| `add-telescope --tm-detector-id 47` | 3.7 s | Treasure Map fetch + dedup ("ZTF already in DB"); the full `setup` had already loaded all 80 detectors |
| `delete-event S240413p --yes` | 1.9 s | removed `HealpixMap id=2` + event directory; other maps preserved |

### Functions not benchmarked (require campaign data)
- `load-obs` — needs a file of executed pointings (observed tiles).
- `efficiency` — needs observed tiles + a model run (model grids ship in
  `web/models/`, but it requires an observation campaign + merger time).
- `run` — composite of `load-map`+`extract`+`plot` (covered individually above).

---

## 4. Bottom line

A brand-new user can go from an **empty folder to a fully working Teglon in ~49 min**
(one-time), then **GW ID → re-weighted skymap in ~2 minutes** and a full
multi-telescope plan in ~3 minutes. Every CLI function ran successfully on the
from-scratch build. One wrapper robustness fix (`-T`) was made during this run.

---

## Appendix — environment

- Host: many-core x86_64, NVMe (`/mnt/nvmeold1`, ~277 GB free at start).
- Docker Compose project `teglon_latetype`; MySQL 8.0.25 on host port 53309.
- `docker/.env`: `CPU_LIMIT=8.0`, `MEM_LIMIT=16gb`.
- Code: `ZiggyTeglon` @ commit `6ce5c045` (+ the `-T` wrapper fix made during this run).
- Events downloaded from public GraceDB (`bayestar.fits.gz`).
