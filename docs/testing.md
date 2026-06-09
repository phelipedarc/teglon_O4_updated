# Testing & validation

Teglon ships unit tests for the CLI plus a reproducible 3-event integration test.

## Unit tests

The pure helpers and CLI wiring are covered by `tests/test_new_functions.py`
(stdlib `unittest`, no DB/network needed):

```bash
# host
PYTHONPATH="$PWD" python -m unittest discover -s tests -v

# inside the Docker image (production runtime)
docker compose -p docker --env-file docker/.env -f docker/docker-compose.yml \
  run --rm --entrypoint python teglon_cli -m unittest discover -s tests -v
```

These assert, among other things, that the destructive commands (`delete-event`,
`setup`) default to a dry-run, that detector geometry is validated, and that the
4D map reconstruction places probability at the correct HEALPix indices.

## 3-event integration test (observational mode)

A canonical end-to-end check using three landmark events:

| Event | GraceDB id | Notes |
|-------|-----------|-------|
| GW170817 | `GW170817` (event G298048) | Not a superevent → use a local skymap + `--t0 1187008882.4` |
| GW190425 | `S190425z` | Public superevent (downloaded from GraceDB) |
| GW190814 | `S190814bv` | Public superevent (downloaded from GraceDB) |

For each event the test runs the observational pipeline and the comparison:

```bash
# GW170817: place web/events/GW170817/bayestar.fits.gz first, then:
./teglon load-map GW170817 --t0 1187008882.4
./teglon extract GW170817
./teglon compare GW170817        # side-by-side 2D vs 4D PDF + area metrics

# GW190425 / GW190814 (downloaded automatically):
./teglon load-map S190425z && ./teglon extract S190425z && ./teglon compare S190425z
./teglon load-map S190814bv && ./teglon extract S190814bv && ./teglon compare S190814bv
```

The `compare` step prints the 50%/90% credible-region areas for the original
LIGO map (2D) and the Teglon galaxy-reweighted map (4D), how much the localization
shrank, and writes `<GWID>_2D_vs_4D_comparison.pdf` to the event directory.

### Running a second instance side-by-side

The integration test above was validated on a separate install at a different
path, MySQL port, and compose project — proving Teglon can run multiple isolated
instances on one host. The keys are three env values in `docker/.env`:

```bash
LOCAL_DB_PORT=53307            # distinct host port
DB_CONTAINER_NAME=teglon_test_db   # distinct container name
COMPOSE_PROJECT_NAME=teglon_test   # distinct compose project (also export it)
```
