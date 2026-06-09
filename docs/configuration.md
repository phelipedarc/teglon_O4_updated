# Configuration

Teglon reads configuration from two places, in this order of precedence:

1. **Environment variables** (highest priority — used for the database connection)
2. **`Settings.ini`** at the repository root

## Database connection

The database connection parameters are resolved by
`web/src/utilities/Database_Helpers.py`. Each one is taken from the environment
first, then `Settings.ini`, then a Docker-friendly default:

| Env var | `Settings.ini` key | Default |
| --- | --- | --- |
| `DATABASE_HOST` | `database/DATABASE_HOST` | `gw_db` |
| `DATABASE_PORT` | `database/DATABASE_PORT` | `3306` |
| `DATABASE_NAME` | `database/DATABASE_NAME` | `teglon` |
| `DATABASE_USER` | `database/DATABASE_USER` | `teglon` |
| `DATABASE_PASSWORD` | `database/DATABASE_PASSWORD` | — |

This is what makes the same code run anywhere without edits:

* **Inside Docker** — the `teglon_cli` compose service sets `DATABASE_HOST=gw_db`,
  so the CLI reaches the database container over the internal network. **No host
  port-forwarding is required.**
* **On the host (pip install)** — set `DATABASE_HOST=127.0.0.1` and
  `DATABASE_PORT=53306` (the port `docker-compose` maps to the DB container) and
  the same commands work, again with no SSH tunnel.

```bash
export DATABASE_HOST=127.0.0.1
export DATABASE_PORT=53306
export DATABASE_PASSWORD=...
teglon extract S230529ay
```

You can also point `Settings.ini` somewhere else with `TEGLON_SETTINGS=/path/to/Settings.ini`.

## `Settings.ini`

Copy `Settings.example.ini` to `Settings.ini` and fill it in. Besides the
database block it holds:

* `[treasuremap]` — `TM_API_TOKEN`, `TM_ENDPOINT` (used by `add_detector` and the
  Treasure Map integration)
* `[gracedb]` — `API_ENDPOINT` for map downloads
* `[cosmology]` — `H0`, `OMEGA_M`, `OMEGA_DE` (used by detection-efficiency modeling)

`Settings.ini` and `docker/.env` are git-ignored. **Do not commit real
credentials** — keep secrets in your local copies or the environment.

## Docker `.env`

`docker/.env` (copy from `docker/.env.example`) configures the compose stack:
volume paths (`VOL_APP`, `VOL_DB`, `VOL_DUSTMAPS`), the DB password (`DB_PWD`),
the optional host DB port (`LOCAL_DB_PORT`), and resource limits (`CPU_LIMIT`,
`MEM_LIMIT`).
