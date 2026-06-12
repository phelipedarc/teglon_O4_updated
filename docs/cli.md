# CLI reference

All functionality is exposed through the single `teglon` command. With Docker,
prefix any subcommand with the wrapper: `./teglon <subcommand> ...`. With the pip
install, call `teglon <subcommand> ...` directly.

Run `teglon --help` or `teglon <subcommand> --help` at any time.

## Global options & output

Place these *before* the subcommand:

| Option | Effect |
| --- | --- |
| `--version` | Print the Teglon version and exit |
| `-q`, `--quiet` | Only log warnings/errors (results still print) |
| `-v`, `--verbose` | Also log per-query debug detail |

**stdout vs stderr.** Progress and debug messages go to **stderr** (controlled by
`--quiet`/`--verbose`); machine-readable **results** (the `KEY=value` blocks and
`--json`) go to **stdout**. So a scheduler can parse stdout cleanly:

```bash
teglon -q compare S240413p --json   # stdout: one JSON line; logs silenced
```

## `teglon doctor`

Preflight checks before a run: database connectivity + content, the pickle caches,
the SFD dust maps, the GLADE catalog, and Treasure Map token validity. Exits
non-zero on a hard failure. `--json` emits the checks as JSON.

```bash
teglon doctor
# [OK  ] database            gw_db:3306/teglon
# [OK  ] database content    maps=5 galaxies=1614264 statictiles=396825
# [OK  ] dust map (SFD)      /dustmaps/sfd/SFD_dust_4096_ngp.fits
# [OK  ] Treasure Map token  79 instruments
```

## `teglon run <GWID>`

Full pipeline for one event: **load-map → extract → plot**.

| Option | Default | Description |
| --- | --- | --- |
| `--healpix-file` | `bayestar.fits.gz` | Map filename to download/use |
| `--healpix-dir` | `./web/events/{GWID}` | Event working directory |
| `--tele` | `a` | Telescope: `s`,`t`,`n`,`t80`,`nf`,`a`(ll) |
| `--extinct` | `0.5` | Max extinction (mag) |
| `--prob-type` | `4D` | `4D` (galaxy-weighted) or `2D` |
| `--cum-prob` | `0.9` | Cumulative probability to cover (0.2–0.95) |
| `--num-tiles` | `1000` | Top N tiles per telescope |
| `--analysis-mode` | off | Ingest at native resolution (no rescale) |
| `--no-clobber` | off | Fail if the map already exists instead of replacing it |
| `--no-plot` | off | Skip the plot stage |
| `--skip-swope/--skip-thacher/--skip-t80/--skip-newfirm` | off | Don't register those tiles |

```bash
teglon run S240413p --tele a --cum-prob 0.9 --num-tiles 500
```

## Individual stages

These let you re-run one step without repeating the others.

### `teglon load-map <GWID>`
Download + ingest a map (same `--skip-*`, `--analysis-mode`, `--no-clobber` flags as `run`).

**Non-superevents & the GWOSC fallback.** GraceDB's superevent API only covers O3+
superevents. When GraceDB has no match for a GW id, `load_map` automatically falls
back to the **GWOSC event API** (`https://gwosc.org/eventapi/json/event/<NAME>/`) to
get the event GPS time (and a HEALPix FITS, for catalogs that publish one).

- **Event GWOSC publishes a skymap for** (newer catalogs): everything is automatic —
  `teglon trigger <GWID>` downloads the FITS and uses the GWOSC GPS time.
- **GWTC-1 events (e.g. GW170817):** GWOSC publishes posterior samples only, not a
  HEALPix FITS. Place the FITS yourself at `web/events/<GWID>/<healpix_file>` and run
  normally — GWOSC still supplies the GPS time, so **no `--t0` is needed**:

```bash
# GW170817 bayestar map saved to web/events/GW170817/bayestar.fits.gz
teglon trigger GW170817        # GraceDB 404 -> GWOSC supplies GPS=1187008882.4
```

You can still pass `--t0 <gps>` explicitly (on `run`/`load-map`/`trigger`) to skip
all lookups for a fully-offline ingest.

### `teglon extract <GWID>`
Produce ranked tile lists from an already-ingested map. Adds a box filter:
`--band`, `--min-ra`, `--max-ra`, `--min-dec`, `--max-dec` (all four required together).
`--json` emits a per-telescope tile-file summary (filename + tile count) to stdout.

### `teglon plot <GWID>`
Render the plan. Options: `--tele`, `--band`, `--tile-file`, `--num-tiles`,
`--cum-prob-outer`, `--cum-prob-inner`.

## `teglon compare <GWID>`
Save a side-by-side PDF of the original LIGO localization (2D) versus the Teglon
galaxy-reweighted map (4D), and print the 50\%/90\% credible-region areas plus how
much the localization shrank. The **2D area is read from the original FITS at full
resolution** (so it equals the published localization area); the 4D area is the
galaxy-reweighted product. `--out` overrides the PDF path; `--json` emits the area
metrics as one JSON line on stdout.

```bash
teglon compare GW170817
```

## `teglon skymap-info <FITS | GWID>`
Print the 50\%, 90\% and 99\% credible-region areas (deg²) of a HEALPix skymap,
computed **directly from the file with `healpy`**. The argument is either:

- a **FITS path** — report that one map; or
- a **GW id** — report the original *and* the Teglon-reweighted map in the event
  directory, plus the shrink factor (use `--healpix-file` if the original isn't
  `bayestar.fits.gz`).

`--json` emits JSON instead of `KEY=value`.

```bash
teglon skymap-info web/events/S240413p/bayestar.fits.gz   # single file
teglon skymap-info S240413p                               # original + reweighted + shrink
teglon skymap-info GW170817 --healpix-file MCMC_TF2_LowSpin_AllSky.fits --json
```

Use it to cross-check the credible areas against the published localisation: on the
reweighted map the result reproduces `compare`'s 4D areas exactly, and on the
original map it returns the full-resolution credible areas (e.g. GW170817 90% =
16.2 deg², matching the GWOSC `sky_area`).

## `teglon load-obs <GWID> --tile-file FILE`
Ingest community / observed tiles into the `ObservedTile` tables. `--tile-dir`
defaults to `./web/events/{GWID}/observed_tiles`.

## `teglon efficiency <GWID>`
Model transient detection efficiency against a library of light curves.
Options: `--model-type` (`kne`, `grb`, …), `--num-cpu`, `--clobber`, `--json`
(emit a JSON summary of the output files).

## `teglon bootstrap`
Build a fresh database (dust + GLADE + optional detectors/grids). See
[Fresh DB bootstrap](bootstrap.md). Options: `--instruments-config FILE`,
`--skip-dust`, `--skip-galaxies`.

## Docker wrapper-only commands

These are provided by the `./teglon` script (not the Python CLI):

| Command | Description |
| --- | --- |
| `./teglon up` | Start the database container (detached) |
| `./teglon down` | Stop the stack |
| `./teglon logs` | Follow database logs |
| `./teglon dbshell` | Open a MySQL shell inside the network (no host port) |
