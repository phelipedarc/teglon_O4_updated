# Welcome to teglon's documentation

![Map](static/map.png)
*GW190425 localization map as transformed by Tegelon. Hot pixels represent high probability galaxies.*

Teglon is a pixel based gravitational wave search and analysis pipeline. It optimizes 
EM search strategies for gravitational wave sources given an input galaxy catalog. Teglon can 
also be used to calculate transient lightcurve model detections efficiencies at the pixel level as 
a function of a set of observations. Teglon is instrument agnostics and can model any telescope 
footprint. Teglon is easily extensible to contain and query any 
[HEALPix](https://healpix.jpl.nasa.gov/) based data (e.g., dustmaps, GW localizations and CMB data).

Essential Teglon functions

* Load LIGO HEALPix maps
* Extract observations
* Plot observation plans and LIGO localization probably maps 
* Ingest community EM observations
* Calculate detection efficiency of a library transient lightcurves given a map and a set of observations

## Getting started

The whole pipeline runs from a single command. With Docker:

```bash
./teglon up                 # start the bundled MySQL database
./teglon run S230529ay      # download map -> rank tiles -> plot, for one GW event
```

Outputs land in `web/events/S230529ay/` (per-telescope tile lists `*.txt` and an
all-sky plan `all_telescopes_4D_0.9_bayestar.fits.gz.svg`).

Next steps:

* [Installation](install.md) — Docker and pip
* [Quickstart](quickstart.md) — run your first event end-to-end
* [CLI reference](cli.md) — every subcommand and option
* [Configuration](configuration.md) — env vars vs `Settings.ini`
* [Database](database.md) — how the data fits together (and why no port-forwarding is needed)
* [Fresh DB bootstrap](bootstrap.md) — build the database from scratch
