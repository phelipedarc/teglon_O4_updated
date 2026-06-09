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

**Local skymaps / non-superevents.** GraceDB's superevent API only covers O3+
superevents. For an older event (e.g. **GW170817**, which is not a superevent) or
any offline map, place the FITS at `web/events/<GWID>/<healpix_file>` and pass the
event GPS time with `--t0`; Teglon then skips the download and ingests the local
file:

```bash
# GW170817 bayestar map already saved to web/events/GW170817/bayestar.fits.gz
teglon load-map GW170817 --t0 1187008882.4
```

`--t0` is also accepted by `run` and `trigger`.

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
