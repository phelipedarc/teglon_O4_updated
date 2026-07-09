# Welcome to teglon's documentation

![Map](static/map.png)
*GW190425 localization map as transformed by Teglon. Hot pixels represent high probability galaxies.*

Teglon is a pixel based gravitational wave search and analysis pipeline. It optimizes 
EM search strategies for gravitational wave sources given an input galaxy catalog. Teglon can 
also be used to calculate transient lightcurve model detections efficiencies at the pixel level as 
a function of a set of observations. Teglon is instrument agnostic and can model any telescope 
footprint. Teglon is easily extensible to contain and query any 
[HEALPix](https://healpix.jpl.nasa.gov/) based data (e.g., dustmaps, GW localizations and CMB data).

Essential Teglon functions

* Load LIGO HEALPix maps
* Extract observations
* Plot observation plans and LIGO localization probability maps 
* Ingest community EM observations
* Calculate detection efficiency of a library transient lightcurves given a map and a set of observations

## Getting started

Once installed, the whole pipeline runs from a single command. With Docker:

```bash
./teglon up                  # start the bundled MySQL database
./teglon trigger S240413p    # GW ID -> ingest + galaxy-reweight -> updated skymap
./teglon extract S240413p    # ranked tiles per telescope
./teglon compare S240413p    # side-by-side 2D-vs-4D PDF
```

Outputs land in `web/events/S240413p/`. `./teglon --help` lists every command.

**New here? Start with:**

* [User Guide](user_guide_v2.md) — the complete guide (features, **old↔new command map**, benchmarks)
* [First-time install](first_time_install.md) — from an empty folder, step by step
* [CLI reference](cli.md) — every subcommand and option

More:

* [Installation](install.md) — Docker and pip
* [Quickstart](quickstart.md) — run your first event end-to-end
* [Configuration](configuration.md) — env vars vs `Settings.ini`
* [Database](database.md) — how the data fits together (and why no port-forwarding is needed)
* [Benchmark report](benchmark_report.md) — install + per-event timings
