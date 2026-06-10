# CLI reference

All functionality is exposed through the single `teglon` command. With Docker,
prefix any subcommand with the wrapper: `./teglon <subcommand> ...`. With the pip
install, call `teglon <subcommand> ...` directly.

Run `teglon --help` or `teglon <subcommand> --help` at any time.

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
teglon run S230529ay --tele a --cum-prob 0.9 --num-tiles 500
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

### `teglon plot <GWID>`
Render the plan. Options: `--tele`, `--band`, `--tile-file`, `--num-tiles`,
`--cum-prob-outer`, `--cum-prob-inner`.

## `teglon compare <GWID>`
Save a side-by-side PDF of the original LIGO localization (2D) versus the Teglon
galaxy-reweighted map (4D), and print the 50%/90% credible-region areas plus how
much the localization shrank. `--out` overrides the PDF path.

```bash
teglon compare GW170817
```

## `teglon load-obs <GWID> --tile-file FILE`
Ingest community / observed tiles into the `ObservedTile` tables. `--tile-dir`
defaults to `./web/events/{GWID}/observed_tiles`.

## `teglon efficiency <GWID>`
Model transient detection efficiency against a library of light curves.
Options: `--model-type` (`kne`, `grb`, …), `--num-cpu`, `--clobber`.

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
