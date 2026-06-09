# Fresh DB bootstrap

If you are starting from an **empty** database (rather than the pre-populated
`DATABASE/` volume), you need to load the science data once: the dust map, the
GLADE galaxy catalog, and each telescope's detector + static tile grid.

The schema, stored procedures, and users are loaded automatically by the
`docker/db_init/*.sql` mounts the first time the `teglon_db` container starts —
`bootstrap` only fills in the data.

## Run it

```bash
./teglon up
./teglon bootstrap
```

By default this runs two stages:

1. **dust** — `initialize_dust.py`: queries the SFD dust map for every NSIDE-128
   sky pixel and writes `ebv.pkl`.
2. **galaxies** — `bulk_upload_glade.py`: parses the GLADE catalog, computes
   luminosity distances and B-luminosity proxies, and bulk-loads ~1.6 M galaxies.

You can skip either stage:

```bash
./teglon bootstrap --skip-dust          # galaxies only
./teglon bootstrap --skip-galaxies      # dust only
```

## Detectors and static grids

Adding telescopes is data-specific (each needs its Treasure Map detector id,
geometry, and declination limits), so it is driven by a JSON config:

```bash
cp instruments.example.json instruments.json
$EDITOR instruments.json
./teglon bootstrap --instruments-config instruments.json
```

Each entry creates a `Detector` (via the Treasure Map API) and its all-sky
`StaticTile` grid:

```json
[
  {
    "name": "SWOPE",
    "tm_detector_id": 12,
    "teglon_detector_id": 1,
    "detector_prefix": "S",
    "detector_geometry": "rectangle",
    "detector_width": 0.45,
    "detector_height": 0.45,
    "min_dec": -90.0,
    "max_dec": 35.0
  }
]
```

Prefer to do it by hand? The original per-step scripts still work:

```bash
./teglon  # (wrapper) -- or inside the container:
python web/src/utilities/add_detector.py --tm_detector_id 12 --detector_geometry rectangle \
    --detector_width 0.45 --detector_height 0.45 --min_dec -90 --max_dec 35
python web/src/utilities/add_static_grid.py --teglon_detector_id 1 --detector_prefix S
```

!!! warning "Heavy operation"
    A full GLADE upload moves millions of rows and can take a long time. Make
    sure the DB container has adequate memory (`MEM_LIMIT` in `docker/.env`).

!!! note "Treasure Map detectors"
    The `--build_TM_detectors` step requires a valid `TM_API_TOKEN` in
    `Settings.ini`. The Treasure Map `/instruments` API expects `type=1`
    (photometric) — this is already handled in `initialize_teglon.py`. A 400
    response usually means the token is missing/expired.
