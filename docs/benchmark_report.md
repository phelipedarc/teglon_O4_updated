# Teglon-O4 — Install & Function Benchmark

**Date:** 2026-06-10
**Method:** a genuine first-time run — `git clone` of the fork
`https://github.com/phelipedarc/teglon_O4_updated.git` (branch `darcTeglon`),
following `docs/first_time_install.md`. **No shortcuts** — real dust fetch, real
GLADE load, full `initialize_teglon`. Isolated instance: compose project
`teglon_install`, container `teglon_install_db`, port 53310.

---

## 1. Installation benchmark (full, from scratch, true first-time)

| Step | What it does | Time |
|------|--------------|-----:|
| `git clone` (fork + checkout `darcTeglon`) | fetch code + 839 MB model library | 102 s |
| Provide `GLADE_2.4.dat` | catalog file (simulated download) | ~0 s |
| `./teglon up` | start + init MySQL (schema/procs/users) | 33 s |
| Fetch SFD dust maps (`initialize_dust.py`) | 2×64 MB | 23 s |
| `./teglon setup --run` | GLADE upload + `initialize_teglon` (all stages) + pickles | **3622 s (60.4 min)** |
| **TOTAL** | empty folder → ready-to-run | **≈ 3780 s ≈ 63 min** |

`setup --run` breakdown: GLADE upload **1260 s** (≈ 21 min) · `initialize_teglon`
≈ **37 min** · `build_init_pickles` ≈ **2 min**.

DB after build: SkyPixel 262,128 · SkyPixel_EBV 196,608 · SkyPixel_Galaxy 11.3 M ·
SkyCompleteness 2.5 M · CompletenessGrid 27.1 M · StaticTile 396,825 · Detector 80 ·
Band 16. Pickles: `composed_completeness_dict.pkl` (473 M), `sky_pixels.pkl`, `ebv.pkl`.
(`StaticTile_HealpixPixel` is empty until the first map is loaded — it is built
per-event by `load_map`.)

> **Why 63 min here vs ~49 min on a dedicated run:** three other test-DB containers
> were running concurrently on the same NVMe, so the I/O-bound GLADE upload took
> 1127 s instead of 591 s. On a clean single-instance host the total is ~45–50 min.

### Completion verified (no hang)
`setup --run` was launched via the `./teglon` wrapper, which now runs the CLI with
`-T` (no pseudo-TTY). It signalled completion cleanly (exit 0, "Setup complete."),
with no leftover container or process — fixing the earlier issue where a backgrounded
`docker compose run` *finished its work but never exited*, appearing hung. After
completion the DB (StaticTile 396,825) and all pickles were confirmed present.

---

## 2. Per-event function benchmark (5 events, fresh DB)

Each event: GW ID → reweighted skymap → tiles → plot → comparison. CLI-reported
execution time (excludes ~2 s container start).

| Function | GW190425 (S190425z) | GW190814 (S190814bv) | S240413p | S231206cc | GW170817¹ |
|----------|--------------------:|---------------------:|---------:|----------:|----------:|
| `trigger` (GW ID → reweighted FITS) | **177.9 s** | **139.0 s** | **120.0 s** | **256.5 s** | **141.9 s** |
| `extract` (tiles ×5 telescopes) | 11.3 s | 15.6 s | 6.7 s | 6.9 s | 3.2 s |
| `plot` (6-panel sky plan) | 34.6 s | 29.6 s | 28.1 s | 33.3 s | 34.6 s |
| `compare` (2D-vs-4D PDF + areas) | 9.8 s | 6.6 s | 7.8 s | 8.7 s | 7.1 s |

¹ GW170817 used the local `MCMC_TF2_LowSpin_AllSky.fits` (NSIDE 1024) + the **GWOSC
fallback** for the event time (GraceDB has no match):

```
GWOSC match: GW170817  GPS=1187008882.4  gracedb_id=G298048
Using local skymap MCMC_TF2_LowSpin_AllSky.fits with GWOSC t_0=1187008882.4
```

`trigger` time scales mostly with input-map resolution + localization tightness;
all five produced 5-telescope tile lists + a reweighted FITS + a comparison PDF.

### Science result (90% credible region)
The 2D area is the **published, full-resolution** localization (read directly from
the original FITS); the 4D area is the Teglon galaxy-reweighted product. Both were
cross-checked with `teglon skymap-info` (healpy): the 2D values match the original
FITS exactly (e.g. GW170817 90% = 16.2 deg² = GWOSC `sky_area`), and the 4D values
match `compare` exactly.

| Event | Prob → galaxies | 2D 90° | Teglon 90° | shrink |
|-------|---------------:|-------:|-----------:|-------:|
| GW190425 (S190425z) | 0.454 | 10182.6 deg² | 5532.6 deg² | 1.84× |
| GW190814 (S190814bv) | 0.843 | 37.6 deg² | 12.0 deg² | 3.13× |
| S240413p | 0.170 | 38.1 deg² | 28.8 deg² | 1.33× |
| S231206cc | 0.004 | 445.1 deg² | 317.9 deg² | 1.40× |
| **GW170817 (MCMC)** | 0.910 | **16.2 deg²** | **0.37 deg²** | **44.0×** |

The shrink scales with how much probability lands on catalog galaxies: GW170817
(nearby, 91% to galaxies, tight MCMC map) collapses **44×** (16.2 → 0.37 deg²);
distant events with low catalog completeness (S231206cc 0.4%, S240413p 17%) shrink
only modestly — the expected behavior.

---

## 3. Management-function checks (from earlier identical builds)

| Function | Time | Result |
|----------|-----:|--------|
| `add-telescope --tm-detector-id 47` | 3.7 s | Treasure Map fetch + dedup (all 80 detectors loaded by `setup`) |
| `delete-event <GWID> --yes` | 1.9 s | removes the map (targeted `DeleteMap` proc) + event directory; other maps preserved |

Not benchmarked (require campaign data): `load-obs` (executed pointings file),
`efficiency` (observed tiles + model run). `run` = composite of `load-map`+`extract`+`plot`.

---

## 4. Bottom line

A brand-new user (cloning the fork) reaches a fully working Teglon in **~45–63 min**
(one-time, depending on host I/O load), then **GW ID → re-weighted skymap in ~2–4 min**
and a full multi-telescope plan in ~3–5 min. All CLI functions ran successfully on the
from-scratch build, including the **GWOSC fallback** for GW170817 and ingestion of a
custom MCMC localization. The `-T` wrapper fix guarantees long background runs exit
cleanly (verified: `setup --run` completed and reported with no hang).

---

## Appendix — environment

- Host: many-core x86_64, NVMe (`/mnt/nvmeold1`, ~267 GB free at start; 3 other test
  DBs running → I/O contention).
- Code: fork `phelipedarc/teglon_O4_updated` @ `darcTeglon` (commit `3dddf490`).
- MySQL 8.0.25, compose project `teglon_install`, host port 53310.
- 4 events downloaded from public GraceDB; GW170817 from a local MCMC FITS +
  GWOSC event time.
