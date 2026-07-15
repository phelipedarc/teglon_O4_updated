# First-time install & use (from an empty folder)

This is the complete, copy-pasteable path for someone who has **never used Teglon**
and starts from an **empty folder** with nothing installed. It ends by running the
real O4 event **S240413p**.

> Measured end-to-end from a fresh `git clone`: the one-time database build
> (step 6) takes **~45–63 min**; afterwards a per-event run (step 7) is **~2–4 min**.

---

## 0. Prerequisites

- **Docker** + **Docker Compose v2** — check with `docker compose version`
- **git**
- **~500 GB** free disk on a fast SSD (galaxy DB + intermediates)
- A **Treasure Map API token** — free from <https://treasuremap.space> (used to
  pull telescope footprints in step 6)
- Internet access (GraceDB, GLADE, dustmaps, Treasure Map)

Pick a base folder and two data folders (keep the DB data **outside** the repo):

```bash
export TEGLON_BASE=$HOME/teglon          # <-- your empty folder
export TEGLON_DATA=$HOME/teglon_data     # <-- DB + dust maps live here
mkdir -p "$TEGLON_BASE" "$TEGLON_DATA/DATABASE" "$TEGLON_DATA/DUST_MAP"
```

## 1. Get the code

```bash
cd "$TEGLON_BASE"
git clone https://github.com/phelipedarc/teglon_O4_updated.git
cd teglon_O4_updated
git checkout darcTeglon            # the branch with the unified CLI + all updates
```

> The updated code lives on the **`darcTeglon`** branch — don't skip the
> `git checkout`, or you'll get the old upstream code.

## 2. Configure

```bash
cp docker/.env.example docker/.env
```
Edit `docker/.env` and set (absolute paths!):
```bash
VOL_APP=<$TEGLON_BASE>/teglon_O4_updated
VOL_DB=<$TEGLON_DATA>/DATABASE
VOL_DUSTMAPS=<$TEGLON_DATA>/DUST_MAP
DB_PWD=<choose-a-strong-password>
LOCAL_DB_PORT=53306
CPU_LIMIT=8.0
MEM_LIMIT=16gb
```
Then the app settings (Treasure Map token):
```bash
cp Settings.example.ini Settings.ini
```
Edit `Settings.ini` → `[treasuremap] TM_API_TOKEN: rX-<your token>` (keep the
`rX-` prefix). Leave the `[database]` block as-is.

## 3. Download the GLADE galaxy catalog (~400 MB, once)

```bash
cd web/src/utilities/galaxy_catalog_files
wget http://glade.elte.hu/GLADE_2.4.txt
mv GLADE_2.4.txt GLADE_2.4.dat        # the file MUST be named exactly GLADE_2.4.dat
cd "$TEGLON_BASE/teglon_O4_updated"
```

## 4. Fetch the SFD dust maps (~130 MB, once)

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml \
  run --rm --no-deps --entrypoint python teglon_cli \
  web/src/utilities/initialize_dust.py
```
This downloads `SFD_dust_4096_ngp/sgp.fits` into your `VOL_DUSTMAPS` folder.

## 5. Start the database

```bash
./teglon up
```
On first start the schema, stored procedures and users load automatically. Wait a
few seconds until the container is healthy (`docker ps` shows `(healthy)`).

## 6. Build the database — ONE TIME (~45–63 min)

```bash
./teglon setup --run
```
This chains: **GLADE upload → `initialize_teglon`** (sky pixels, detectors, dust
E(B-V), galaxy↔pixel associations, completeness, static tile grids) **→ pickle
caches**. It needs a valid `TM_API_TOKEN` for the Treasure Map detector step.

> Run `./teglon setup` (without `--run`) first to print the plan without executing.
> Re-running `setup --run` is **safe** — stages whose tables/pickles already exist
> are skipped (use `--force` to rebuild them), so a re-run after an interruption
> won't duplicate rows.

> **Old way (v1.0):** the same build, by hand, was three commands run via the
> `gw_script` service — `bulk_upload_glade.py`, then `initialize_teglon.py` (with
> all `--build_*` flags), then `build_init_pickles.py`. `setup --run` simply chains
> them. Full old↔new mapping is in the
> [User Guide](user_guide_v2.md#3-old-new-command-equivalence) — both still work.

## 7. Use it — run S240413p end to end

```bash
# GW ID  ->  ingest + galaxy-reweight  ->  reweighted HEALPix FITS   (~2 min)
./teglon trigger S240413p

# Ranked observing tiles per telescope (Swope/Thacher/Nickel/T80S/NEWFIRM)
./teglon extract S240413p

# Side-by-side "original 2D vs Teglon-updated" PDF + credible-area metrics
./teglon compare S240413p
```
Outputs land in `web/events/S240413p/`:
- `S240413p_4D_reweighted_bayestar.fits.gz` — the reweighted skymap
- `S240413p_<TELESCOPE>_4D_0.9_bayestar.fits.gz.txt` — ranked tiles
- `S240413p_2D_vs_4D_comparison.pdf` — the comparison figure

All-in-one planning pipeline (load → extract → plot) is also available:
```bash
./teglon run S240413p
./teglon --help          # every command and option
./teglon down            # stop the stack when finished
```

---

## Notes & shortcuts

- **No Treasure Map token?** The 5 core telescopes are built by the local
  `--build_detectors` step regardless; you can skip the community detectors by
  editing the flag list, but the supported path is to supply a token.
- **Have a colleague's database?** You can skip steps 3–6 entirely: get a
  `mysqldump` of their `teglon` schema and restore it into your `VOL_DB` instance
  (`./teglon up`, then `mysql … < dump.sql`). Minutes instead of hours.
- **Non-superevents / offline maps** (e.g. GW170817, which isn't on public
  GraceDB): place the FITS at `web/events/<GWID>/<file>`, then run normally —
  Teglon automatically falls back to the **GWOSC** event API for the event time
  (`./teglon trigger GW170817 --healpix-file <file>`). No `--t0` needed (it stays
  available for a fully offline ingest).
- **Multiple instances on one host:** set distinct `LOCAL_DB_PORT`,
  `DB_CONTAINER_NAME`, and `COMPOSE_PROJECT_NAME` in `docker/.env`.

### What was verified
See the [benchmark report](benchmark_report.md).
