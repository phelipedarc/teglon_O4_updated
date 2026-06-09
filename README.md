# teglon_O4
LIGO O4-optimized version of Teglon — a pixel-based gravitational-wave EM
follow-up observation planner.

[![Documentation Status](https://readthedocs.org/projects/teglon-04/badge/?version=latest)](https://teglon-04.readthedocs.io/en/latest/?badge=latest)

Documentation: https://teglon-04.readthedocs.io/en/latest/

## Quickstart (Docker)

```bash
cp docker/.env.example docker/.env      # set VOL_APP, VOL_DB, VOL_DUSTMAPS, DB_PWD
cp Settings.example.ini Settings.ini    # set your Treasure Map API token
./teglon up                             # start the bundled MySQL database
./teglon run S230529ay                  # download map -> rank tiles -> plot
```

Outputs land in `web/events/S230529ay/` (per-telescope `*.txt` tile lists and an
all-sky `*.svg` observation plan). The CLI runs inside the Docker network and
talks to the database container directly — **no port-forwarding / MySQL Workbench
tunnel needed.**

## Quickstart (pip)

```bash
pip install -e .                        # core pipeline
export DATABASE_HOST=127.0.0.1 DATABASE_PORT=53306 DATABASE_PASSWORD=...
teglon run S230529ay
```

## Common commands

```bash
./teglon run <GWID>        # full pipeline: load -> extract -> plot
./teglon load-map <GWID>   # individual stages
./teglon extract <GWID>
./teglon plot <GWID>
./teglon bootstrap         # build a fresh DB (dust + GLADE + detectors)
./teglon --help            # everything else
```

See the [documentation](https://teglon-04.readthedocs.io/en/latest/) for the full
CLI reference, configuration, and database details.
