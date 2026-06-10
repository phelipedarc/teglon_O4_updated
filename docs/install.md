# Installation

There are two supported ways to run Teglon-O4: **Docker** (recommended) and a
**pip-installed** CLI on the host. Both expose the same `teglon` command.

## Option A — Docker (recommended)

Docker bundles the MySQL database and the full scientific Python stack
(`healpy`, `ligo.skymap`, `dustmaps`, …), so you don't have to build those
natively. The CLI runs *inside* the Docker network and talks to the database
container directly — **no host port-forwarding or MySQL Workbench tunnel is
required.**

### Prerequisites

* Docker + Docker Compose v2 (`docker compose version`)
* A Treasure Map API token (free from <https://treasuremap.space>)
* The GLADE catalog + SFD dust maps are **fetched during setup** (not shipped) —
  the full first-time walkthrough is in [First-time install](first_time_install.md).

### Setup

```bash
git clone https://github.com/phelipedarc/teglon_O4_updated.git
cd teglon_O4_updated
git checkout darcTeglon       # the updated branch (don't skip this)

# 1. Configure paths/credentials
cp docker/.env.example docker/.env
$EDITOR docker/.env          # set VOL_APP, VOL_DB, VOL_DUSTMAPS, DB_PWD

cp Settings.example.ini Settings.ini
$EDITOR Settings.ini         # set your Treasure Map API token

# 2. Start the database (first start auto-loads the schema + stored procedures)
./teglon up

# 3. FIRST TIME ONLY: build the database (~45–63 min). Needs GLADE + dust maps —
#    see First-time install for the GLADE download + dust fetch.
./teglon setup --run

# 4. Run a GW event end-to-end
./teglon run S240413p
```

The `./teglon` wrapper forwards any subcommand to the CLI inside the network:

```bash
./teglon --help
./teglon extract S240413p --cum-prob 0.9 --num-tiles 500
./teglon down                # stop the stack when finished
```

> New to Teglon? Follow [First-time install](first_time_install.md) — it's the
> complete copy-pasteable path from an empty folder, including the GLADE + dust steps.

## Option B — pip (host install)

Use this if you already run (or can reach) a MySQL Teglon database and want the
`teglon` command directly on your machine.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .             # core pipeline deps
# optional extras:
pip install -e ".[web]"      # Flask API + Celery worker stack
pip install -e ".[legacy]"   # basemap-based legacy plots/integrations
```

Point the CLI at your database with environment variables (these override
`Settings.ini`), then run any command:

```bash
export DATABASE_HOST=127.0.0.1
export DATABASE_PORT=53306        # the port docker-compose maps to the DB container
export DATABASE_USER=teglon
export DATABASE_PASSWORD=...      # your DB password
export DATABASE_NAME=teglon

teglon run S240413p
```

!!! note "Native scientific dependencies"
    `healpy`, `ligo.skymap`, `mysqlclient`, and `basemap` need system libraries
    (a C/C++ toolchain, `default-libmysqlclient-dev`, etc.). If a host install
    fights you, use the Docker path — it already contains everything.

See [Configuration](configuration.md) for the full list of settings.
