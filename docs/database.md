# Database

Teglon stores its sky model, galaxy catalog, telescope definitions, and
per-event probability data in a **MySQL 8** database. It uses MySQL-specific
features — spatial types (`MULTIPOLYGON`, `POINT`, `ST_AsText`), window
functions, stored procedures, and `LOAD DATA LOCAL INFILE` — so MySQL is a hard
requirement (it is bundled in the Docker stack).

## No port-forwarding required

In the Docker setup the database runs as the `teglon_db` container and the CLI
runs as the ephemeral `teglon_cli` service on the **same Docker network**. The
CLI connects to host `gw_db:3306` directly — there is no need to expose the DB
on the host or set up a MySQL Workbench / SSH tunnel.

The host port mapping (`LOCAL_DB_PORT`, default `53306`) is **optional** and only
exists so you can inspect the DB from the host if you want to. The pipeline never
needs it. See [Configuration](configuration.md) for how the connection is
resolved from environment variables.

To open a shell against the DB without any host port:

```bash
./teglon dbshell
```

## Key tables

| Table | Purpose |
| --- | --- |
| `HealpixMap` | One row per (GW event, map file); event time, NSIDE |
| `HealpixPixel` | Per-pixel probability and distance distribution |
| `HealpixPixel_Completeness` | `NetPixelProb` = prob × galaxy completeness (the "4D" probability) |
| `SkyPixel` / `SkyPixel_EBV` | Fixed NSIDE-128 sky tessellation + dust extinction |
| `Galaxy` | GLADE galaxy catalog (~1.6 M rows) |
| `HealpixPixel_Galaxy_Weight` | Per-galaxy probability weight (galaxy-targeted mode) |
| `CompletenessGrid` | Distance-completeness lookup per sky pixel |
| `Detector` | Telescope FOV polygon + declination limits |
| `StaticTile` / `StaticTile_HealpixPixel` | Pre-tiled all-sky grids and their pixel membership |
| `ObservedTile` / `ObservedTile_HealpixPixel` | Ingested community observations |
| `Band` | Photometric bands with F99 extinction coefficients |

## Schema initialization

When the `teglon_db` container starts with an **empty** data directory, MySQL
auto-runs the mounted SQL in `docker/db_init/` in order: schema, the `angsep`
function, `BackupTables`/`DeleteMap` stored procedures, and the users. To then
fill the science data (galaxies, dust, detectors, static grids), run
[`teglon setup --run`](first_time_install.md) once (~45–63 min).

If you mount an already-populated `DATABASE/` volume, none of that is needed and
you can go straight to [`teglon run <GWID>`](quickstart.md).
