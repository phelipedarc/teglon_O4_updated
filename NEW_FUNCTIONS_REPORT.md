# Teglon-O4 — New Functions Report

**Date:** 2026-06-09
**Scope:** 4 new user functions + unit tests. Additive only — nothing removed.
**Safety rule honored:** no deletions performed; every destructive op is dry-run by
default and requires explicit confirmation.

---

## 1. Summary of new functions

All four are new subcommands of the unified `teglon` CLI
(`web/src/services/teglon_cli.py`). They reuse existing code paths; no science
logic or schema was changed.

| # | Command | What it does | Reuses |
|---|---------|--------------|--------|
| 1 | `teglon delete-event <GWID>` | Clean a GW event from the DB **and** files | `BackupTables`/`DeleteMap` procs (same as `delete_map.py` / `load_map --clobber`) |
| 2 | `teglon add-telescope --tm-detector-id <id>` | Register a new telescope (e.g. LSST/Vera Rubin) + optional static grid | `Teglon.add_detector`, `Teglon.add_static_grid` |
| 3 | `teglon setup [--run]` | One-time complete install initialization | `bulk_upload_glade.py`, `initialize_teglon.py` (all flags), `build_init_pickles.py` |
| 4 | `teglon trigger <GWID> --healpix-file <f>` | Ingest + galaxy-reweight a skymap, export the updated 4D HEALPix map to FITS | `Teglon.load_map`, plot_teglon's 4D reconstruction |

### Safety design
- **`delete-event`** is **dry-run by default**: it prints the maps + files it
  *would* remove and exits. Only `--yes` performs deletion. Map ids are coerced to
  `int` before being put in SQL. Flags: `--db-only`, `--files-only`.
- **`setup`** is **dry-run by default**: prints the step plan and exits. Only
  `--run` executes (it can take ~2–3 hours).
- **`add-telescope`** requires `--tm-detector-id`; the static grid is only built if
  you also pass `--teglon-detector-id` and `--prefix`.
- **`trigger`** ingests with `--clobber` by default (override with `--no-clobber`);
  `--no-ingest` exports from an already-ingested event without re-ingesting.

---

## 2. Files changed

**Edited (additive):**
- `web/src/services/teglon_cli.py`
  - New pure helpers (unit-tested): `event_dir`, `build_delete_map_sql`,
    `plan_event_file_deletion`, `normalize_geometry_args`, `build_setup_steps`,
    `reweighted_output_path`, `reconstruct_reweighted_map`.
  - New command functions: `cmd_delete_event`, `cmd_add_telescope`, `cmd_setup`,
    `cmd_trigger`.
  - Four new subparsers registered in `build_parser`.

**New:**
- `tests/test_new_functions.py` — 23 unit tests.
- `NEW_FUNCTIONS_REPORT.md` — this report.

**Not touched:** `teglon.py` science logic, the SQL schema/stored procedures, the
existing per-stage scripts, and all previously documented commands.

---

## 3. Unit test results

Tests cover the pure helpers and the argparse wiring (including that the
destructive commands default to dry-run). They do **not** touch the DB, network,
or filesystem (other than a temp dir).

**Host run** (`python -m unittest discover -s tests -v`):
```
Ran 23 tests in 0.107s
OK
```

**Docker run** (inside `ghcr.io/davecoulter/teglon_o4:latest`, the production image):
```
Ran 23 tests in 0.177s
OK
```

### Test inventory (23)
- `TestEventHelpers` (5): event dir templating; delete SQL structure; **int coercion of
  map id** (rejects `"42; DROP TABLE ..."`); file-deletion planning lists files+dir;
  missing dir → empty.
- `TestTelescopeGeometry` (6): rectangle ok / missing-dims error; circle ok /
  missing-radius error; polygon → no geometry; unknown geometry error.
- `TestSetupSteps` (4): default 3 steps in order; init step carries all 11 documented
  flags; `--no-debug` omits `--is_debug`; skip flags reduce step count.
- `TestReweightedMap` (3): output path format; values land at the right HEALPix
  indices with correct npix; out-of-range pixel index ignored (no crash).
- `TestParserSafetyDefaults` (5): **delete-event defaults to dry-run**; **setup
  defaults to dry-run**; add-telescope requires `--tm-detector-id`; func wiring for
  add-telescope and trigger.

---

## 4. Live (non-destructive) verification

Run against the real database/container — read-only, nothing changed:

- `./teglon delete-event S230529ay` → correctly resolved `HealpixMap id=6` and listed
  the 12 event files, then printed `DRY RUN -- nothing was deleted.` ✅
- `./teglon setup` → printed the exact documented 3-step plan, then
  `DRY RUN -- nothing was executed.` ✅

---

## 5. Not yet run — needs your permission

Per your rule, I did **not** execute any destructive / data-writing integration:
- `delete-event --yes` (would remove a map + files)
- `add-telescope` (writes a Detector row; hits the Treasure Map API)
- `setup --run` (multi-hour DB build)
- `trigger` without `--no-ingest` (re-ingests/clobbers a map)

Tell me which of these you'd like me to run live, and on which event/IDs.
