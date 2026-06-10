# Quickstart

This walks through planning observations for a single gravitational-wave event.

## 1. Start the database

```bash
./teglon up
```

This starts the `teglon_db` MySQL container. On its very first start it
auto-loads the schema, stored procedures (`BackupTables`, `DeleteMap`), and
users from `docker/db_init/*.sql`.

> **First time?** The database still needs its science data (galaxies, dust,
> detectors, static grids). Build it once with `./teglon setup --run` — see
> [First-time install](first_time_install.md). The steps below assume that's done
> (or that you mounted an already-built `DATABASE/` volume).

## 2. Run the full pipeline

```bash
./teglon run S240413p
```

`run` performs three stages in order (no Celery/queue needed):

1. **load-map** — downloads `bayestar.fits.gz` from GraceDB, rescales it,
   ingests pixels, cross-matches with the GLADE galaxy catalog (4D probability),
   and links pixels to each telescope's static tile grid.
2. **extract** — ranks tiles per telescope by summed probability, filtered by
   dust extinction and a cumulative-probability cutoff.
3. **plot** — renders an all-sky Mollweide plan (probability contours, dust,
   Sun avoidance, airmass, and the ranked tiles).

## 3. Look at the output

Everything is written under the event directory:

```
web/events/S240413p/
├── bayestar.fits.gz                                   # the downloaded map
├── S240413p_SWOPE_4D_0.9_bayestar.fits.gz.txt        # ranked tiles (ECSV)
├── S240413p_THACHER_4D_0.9_bayestar.fits.gz.txt
├── S240413p_NICKEL_4D_0.9_bayestar.fits.gz.txt       # galaxy-targeted list
├── ...
└── all_telescopes_4D_0.9_bayestar.fits.gz.svg         # the observation plan
```

Each tile file is an Astropy ECSV table with columns `Field_Name, RA, Dec, Prob,
Percentile, EBV, A_lambda, Lum_Dist` (plus `B_mag, K_mag` for the galaxy list),
and a header recording every parameter used.

## Common variations

```bash
# Only one telescope, custom coverage and tile count
./teglon run S240413p --tele s --cum-prob 0.9 --num-tiles 300

# Skip the plot (just the tile lists)
./teglon run S240413p --no-plot

# Re-extract with different settings without re-downloading the map
./teglon extract S240413p --prob-type 2D --extinct 0.3
./teglon plot S240413p
```

See the [CLI reference](cli.md) for every option.
