# Teglon O4 — User Documentation
**Version:** 2.0 | **Branch:** ZiggyTeglon | **Updated:** June 2026

This version keeps **everything from v1.0 working** and adds a single `teglon`
command, a Docker wrapper, environment-based configuration (no port-forwarding),
and several new functions. **Every old command still works** — the new commands
are shorter equivalents. This guide focuses on what changed.

---

## Table of Contents
1. What's new in 2.0
2. The `teglon` wrapper (Docker) and the pip CLI
3. Old ↔ new command equivalence
4. The new functions (delete-event, add-telescope, setup, trigger, compare)
5. Configuration & the "no port-forwarding" change
6. Benchmark test: GW ID → re-weighted skymap
7. Installation shortcuts taken during testing (full disclosure)
8. Troubleshooting (issues found & fixed in 2.0)

---

## 1. What's new in 2.0

| Area | v1.0 | 2.0 |
| --- | --- | --- |
| Running stages | `docker compose run --rm gw_script python ./web/src/...` per stage | `./teglon <subcommand>` (old form still works) |
| Full pipeline | run load_map → extract_tiles → plot_teglon by hand | `./teglon run <GWID>` (one command) |
| Install | Docker only, no packaging | Docker wrapper **and** `pip install -e .` (`pyproject.toml`) |
| DB connection | host hardcoded (`gw_db`) → needed a tunnel/Workbench port-forward | resolved from env first → **no port-forwarding** |
| New capabilities | — | `delete-event`, `add-telescope`, `setup`, `trigger`, `compare` |
| Docs | single intro page | full mkdocs site (install, CLI, config, testing, this guide) |

Nothing was removed. The per-stage scripts in `web/src/**` are unchanged, so any
v1.0 command line you already use keeps working.

---

## 2. The `teglon` wrapper (Docker) and the pip CLI

### 2.1 Docker wrapper (`./teglon`)
A small launcher in the repo root runs the CLI **inside the Docker network**, so
it talks to the database container directly — no host port-forwarding needed.

```bash
./teglon up                # start the database (detached)
./teglon run S240413p      # full pipeline
./teglon --help            # list every subcommand
./teglon down              # stop the stack
./teglon dbshell           # MySQL shell inside the network (no host port)
./teglon logs              # follow DB logs
```

The wrapper pins the compose **project name** so every call reuses the same DB
container instead of recreating it. Resolution order: shell `COMPOSE_PROJECT_NAME`
→ `COMPOSE_PROJECT_NAME` in `docker/.env` → the `docker/` directory name. (This is
why a second instance needs a distinct `COMPOSE_PROJECT_NAME` in its `.env`; see §8.)

### 2.2 pip CLI
```bash
pip install -e .              # core pipeline; gives the `teglon` command on the host
pip install -e ".[web]"       # + Flask/Celery stack
pip install -e ".[legacy]"    # + basemap (legacy plots)
```
Then point it at any database with env vars and run any subcommand:
```bash
export DATABASE_HOST=127.0.0.1 DATABASE_PORT=53306 DATABASE_PASSWORD=...
teglon run S240413p
```

---

## 3. Old ↔ new command equivalence

Both columns do the same thing. The old form runs the unchanged script via the
`gw_script` service; the new form runs it through the unified CLI.

| Task | v1.0 command | 2.0 equivalent |
| --- | --- | --- |
| Test DB connectivity | `docker compose run --rm gw_script python ./web/src/utilities/kick_db.py` | `./teglon up` then `./teglon dbshell` |
| Upload GLADE | `… python ./web/src/utilities/bulk_upload_glade.py` | part of `./teglon setup --run` |
| Initialize core tables | `… python ./web/src/utilities/initialize_teglon.py --is_debug --build_skydistances --build_skypixels --build_detectors --build_TM_detectors --build_bands --build_MWE --build_galaxy_skypixel_associations --build_completeness --compose_completeness --build_static_grids` | part of `./teglon setup --run` |
| Build pickle caches | `… python ./web/src/utilities/build_init_pickles.py --build_skypixels_pickle --build_ebv_pickle --build_composed_completeness_pickle` | part of `./teglon setup --run` |
| Ingest a map | `… python ./web/src/ingestion/load_map.py --gw_id S240413p` | `./teglon load-map S240413p` |
| Ingest (analysis mode) | `… load_map.py --gw_id S240413p --analysis_mode` | `./teglon load-map S240413p --analysis-mode` |
| Extract tiles | `… python ./web/src/output/extract_tiles.py --gw_id S240413p --healpix_file bayestar.fits.gz` | `./teglon extract S240413p` |
| Plot | `… python ./web/src/output/plot_teglon.py --gw_id S240413p` | `./teglon plot S240413p` |
| Convert observations | `… python ./web/src/ingestion/obs_tile_converter.py …` | *(unchanged — run the script)* |
| Load observed tiles | `… python ./web/src/ingestion/load_observed_tiles.py --gw_id S240413p --tile_file f.ecsv` | `./teglon load-obs S240413p --tile-file f.ecsv` |
| Detection efficiency | `… python ./web/src/analysis/model_detection_efficiency.py --gw_id S240413p --model_type kne --num_cpu 70 …` | `./teglon efficiency S240413p --model-type kne --num-cpu 70` |
| Add a detector | `… python ./web/src/utilities/add_detector.py --tm_detector_id N …` | `./teglon add-telescope --tm-detector-id N …` |
| Add a static grid | `… python ./web/src/utilities/add_static_grid.py --teglon_detector_id N --detector_prefix X` | `./teglon add-telescope … --teglon-detector-id N --prefix X` |
| Delete a map | `… python ./web/src/utilities/delete_map.py --healpix_map_id N` | `./teglon delete-event <GWID>` *(by GW id, also removes files, dry-run by default)* |
| Full pipeline | *(run the three stages above by hand)* | `./teglon run S240413p` |
| GW ID → re-weighted skymap | *(not available)* | `./teglon trigger S240413p` |
| Original vs reweighted comparison | *(not available)* | `./teglon compare S240413p` |

Flag naming: the CLI uses kebab-case (`--healpix-file`, `--num-tiles`,
`--analysis-mode`); the underlying scripts still use snake_case (`--healpix_file`,
…). Use whichever entry point you prefer.

---

## 4. The new functions

### 4.1 `teglon delete-event <GWID>` — clean a map from DB **and** files
Dry-run by default (prints what it would remove); `--yes` executes. Operates by
GW id (not the integer map id), and also removes the event directory. Internally
uses the same `BackupTables`/`DeleteMap` procedures as v1.0's `delete_map.py`, so
all other maps are preserved.
```bash
./teglon delete-event S240413p              # dry-run
./teglon delete-event S240413p --yes        # execute (DB + files)
./teglon delete-event S240413p --yes --db-only   # keep files
```

### 4.2 `teglon add-telescope` — register a telescope (e.g. LSST/Vera Rubin)
Wraps `add_detector` (+ optional `add_static_grid`).
```bash
./teglon add-telescope --tm-detector-id 78 --geometry circle --radius 1.75 \
    --teglon-detector-id <new DB id> --prefix L
```

### 4.3 `teglon setup` — one-time complete initialization
Dry-run by default; `--run` executes. Chains GLADE → `initialize_teglon` (all
flags) → `build_init_pickles` — i.e. the entire v1.0 sections 5–6 in one command.
```bash
./teglon setup            # print the plan
./teglon setup --run      # build the DB from scratch (~2–3 h)
```

### 4.4 `teglon trigger <GWID>` — GW ID → re-weighted skymap
Ingests + galaxy-reweights the map and exports the updated HEALPix probability map
to FITS (`web/events/<GWID>/<GWID>_4D_reweighted_<file>`). This is the
benchmarked end-to-end path (see §6).
```bash
./teglon trigger S240413p
./teglon trigger GW170817        # GraceDB 404 -> GWOSC fallback supplies the GPS time
```

**GWOSC fallback.** If GraceDB has no match for the GW id, `load_map` automatically
queries the GWOSC event API (`/eventapi/json/event/<NAME>/`) for the event GPS time
and, where the catalog publishes one, the HEALPix FITS. GWTC-1 events (e.g.
GW170817) publish posterior samples only, so place the FITS at
`web/events/<GWID>/<file>` yourself — GWOSC still supplies the time, so no `--t0`
is needed. `--t0 <gps>` remains available to skip all lookups (offline ingest).

### 4.5 `teglon compare <GWID>` — original vs Teglon-updated skymap
Saves a side-by-side PDF and prints credible-region areas. **Physically correct:**
both panels are the *same* 2D sky representation over the *same* pixel set,
normalized identically — only the per-pixel probability differs (Teglon's update).
Reports 50%/90% areas and the shrink factor.

---

## 5. Configuration & the "no port-forwarding" change

Database connection parameters resolve from the **environment first**
(`DATABASE_HOST/PORT/NAME/USER/PASSWORD`), then `Settings.ini`, then a default.
This is what removes the need to port-forward:

- **Inside Docker** the CLI runs on the DB's network (`DATABASE_HOST=gw_db`) — it
  reaches the database container directly.
- **On the host** (pip) set `DATABASE_HOST=127.0.0.1 DATABASE_PORT=53306` and the
  same commands work.

The host port mapping (`LOCAL_DB_PORT`) is now **optional** — only needed if you
want to inspect the DB with MySQL Workbench. See `configuration.md`.

> v1.0 also had a latent bug: `query_db()` ignored the configured port (hardcoded
> 3306). 2.0 honors `DATABASE_PORT`.

---

## 6. Benchmark test: GW ID → re-weighted skymap

The headline performance number is the time to go from a bare GW ID to the
galaxy-reweighted skymap, via `trigger`:

```bash
time ./teglon trigger S240413p
```

**Measured (clone-based test install, 8 CPUs):**

| Step | Time |
| --- | --- |
| Download `bayestar.fits.gz` from GraceDB | 3.2 s |
| Ingest + galaxy-reweight + export FITS | ~120 s |
| **Total (`trigger`)** | **123.8 s (~2 min)** |

Output: `web/events/S240413p/S240413p_4D_reweighted_bayestar.fits.gz`.

For reference, the `compare` step quantifies the localization improvement
(normalized 90% credible region):

| Event | Prob → galaxies | 2D 90° | Teglon 90° | shrink |
| --- | --: | --: | --: | --: |
| GW170817 | 0.910 | 22.5 deg² | 0.73 deg² | 30.6× |
| GW190425 (S190425z) | 0.716 | 7787 deg² | 2494 deg² | 3.1× |
| GW190814 (S190814bv) | 0.900 | 25.1 deg² | 10.0 deg² | 2.5× |
| S240413p | 0.340 | 29.2 deg² | 27.4 deg² | 1.07× |

(The shrink scales with how much probability lands on catalog galaxies — large for
nearby events, small for distant ones where the catalog is incomplete.)

---

## 7. Installation shortcuts taken during testing (full disclosure)

The 2.0 changes were validated on a **clone-based** test install at
`/mnt/nvmeold1/teglon_test` (separate compose project `teglon_test`, port 53307).
To get a working galaxy database quickly, several shortcuts were used **instead of
the official from-scratch `setup`**. If you follow the official path
(`first_time_install.md`), you do **not** need these — they are documented so you
know exactly what was and wasn't exercised:

1. **Database cloned, not built.** Instead of `./teglon setup --run` (the ~2–3 h
   GLADE + `initialize_teglon` build), the production `teglon` schema was copied
   with a read-only `mysqldump` and restored into the test instance (minutes).
   *Official path:* run `./teglon setup --run`.
2. **Pickle cache copied.** `composed_completeness_dict.pkl` (read by `load_map`),
   `ebv.pkl`, `sky_pixels.pkl`, `N128_dict.pkl` were copied from the production
   install rather than regenerated by `build_init_pickles`.
   *Official path:* these are produced by `setup`'s pickle step.
3. **Dust maps reused.** `VOL_DUSTMAPS` pointed at the existing SFD maps rather
   than fetching fresh.
   *Official path:* run `initialize_dust.py` (step 4 of `first_time_install.md`).
4. **GLADE provided as a file.** A real `GLADE_2.4.dat` must live under
   `web/src/utilities/galaxy_catalog_files/` — a symlink to a host path **fails
   inside the container** (it isn't mounted). Place the real file there.
5. **GW170817 ingested from a local skymap.** GW170817 isn't on public GraceDB
   (it's not a superevent), so its BAYESTAR map was downloaded from the public DCC
   archive and ingested with `./teglon load-map GW170817 --t0 1187008882.4`.
6. **From-scratch `setup` not run to completion.** It was validated through GLADE
   + sky pixels + detectors + the Treasure Map fix, then stopped. The later
   `initialize_teglon` stages (MWE, associations, completeness, static grids) and
   the pickle step were not run end-to-end in the test session.

---

## 8. Troubleshooting (issues found & fixed in 2.0)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Bind for 0.0.0.0:5330x failed: port is already allocated` when running `./teglon` | The wrapper resolved a different compose **project** than the running DB, so it tried to recreate the DB container on a busy port | The wrapper now reads `COMPOSE_PROJECT_NAME` from `docker/.env`. For a second instance, set distinct `LOCAL_DB_PORT`, `DB_CONTAINER_NAME`, and `COMPOSE_PROJECT_NAME` in its `.env`. |
| `container name "/teglon_db" already in use` (second instance) | `container_name` was hardcoded | Parameterized: `container_name: ${DB_CONTAINER_NAME:-teglon_db}` |
| `FileNotFoundError: …/pickles/N128_dict.pkl` on a fresh install | the pickle cache dir didn't exist yet | `Teglon.__init__` now creates it (`os.makedirs(..., exist_ok=True)`) |
| `setup` GLADE step: `GLADE_2.4.dat` not found | a symlink to an un-mounted host path dangles in the container | place the **real** `GLADE_2.4.dat` under `galaxy_catalog_files/` |
| `initialize_teglon --build_TM_detectors`: `TypeError: string indices must be integers` | Treasure Map API changed: `/instruments` now needs `type=1` (not `"photometric"`) → HTTP 400; some `nickname`s are `None` | fixed in `initialize_teglon.py` (`type=1`, coerce `nickname or ''`) |
| `version` is obsolete warning | legacy `version: '2.4'` in compose | removed |
| TM 500 / token error (from v1.0) | `TM_API_TOKEN` missing the `rX-` prefix | keep the `rX-` prefix in `Settings.ini` |

The v1.0 troubleshooting items (port 53306 in use, GLADE filename, GLADE
intermediate permissions, stale pickles, missing model dirs, OOM) all still apply.
