# TEGLON — Redback Transients Extension

An **optional, self-contained add-on** that lets TEGLON compute detection-efficiency for **any
[redback](https://github.com/nikhil-sarin/redback) transient model** (kilonovae, GRB afterglows,
SNe, …). It is **separate from the TEGLON package**: nothing in `web/src` is modified, and every
script resolves TEGLON at runtime, so you can drop this directory into **any** TEGLON install and
run it — no package edits, no reinstall.

* **redback is only needed to _simulate_ light curves.** The detection analysis reads pre-made
  `.dat` banks and needs **no redback** — so it runs in a stock TEGLON container. redback is
  imported lazily; if it is missing you get an actionable install message, not a stack trace.
* **TEGLON is only needed to _analyze_.** The two simulation scripts need redback + astropy only.

---

## Deploy (any TEGLON, no modifications)

Copy this directory anywhere the TEGLON container can see it (e.g. under the app mount as
`/app/redback_extension`), then run the scripts with `python`. Each script finds the TEGLON app
root (the dir containing `web/src`) automatically via, in order: `--teglon_root` → `$TEGLON_ROOT`
→ `PYTHONPATH` (the container sets `PYTHONPATH=/app`) → walking up from the cwd.

```bash
# inside the TEGLON repo:
cp -r redback_extension /path/to/teglon/          # a SEPARATE dir; web/src untouched
# run via the project's compose 'teglon_cli' service (entrypoint overridden to python):
docker compose -p <proj> --env-file docker/.env -f docker/docker-compose.yml \
    run --rm --entrypoint python teglon_cli /app/redback_extension/<script>.py [flags]
```

**redback install** (only if you will *simulate* inside the container — analysis does not need it):
```bash
# persistent: add `redback` to docker/teglon_worker/requirements.txt and rebuild the image
docker compose ... build teglon_cli
# quick / throwaway:
docker compose ... exec teglon_cli pip install redback     # needs a C compiler for sncosmo
# isolated venv (recommended — keeps teglon's pinned astropy/ligo.skymap intact):
python -m venv redback_env && redback_env/bin/pip install -r redback_extension/requirements.txt
```
> Heads-up: on a **shared** TEGLON stack, installing redback upgrades astropy (5.x → 7.x) and can
> break `ligo.skymap` for other users. Prefer the two-environment split below (simulate in an
> isolated redback venv; analyze in the stock container via `--from_disk`).

---

## The 4 scripts

### 1. `simulate_redback_teglon.py` — model-agnostic light-curve bank
Draws `--n-sim` samples from a redback model's **default prior** and writes each as a TEGLON-format
ECSV `.dat` (30 cols: `time` + 29 bands, **absolute AB mag**, redback-native comment), binned into
numbered folders. Needs **redback + astropy only** (no TEGLON). Redshift is pinned so columns stay
absolute; TEGLON applies real distance/extinction later.

| Flag | Default | Meaning |
|---|---|---|
| `model` (positional) | — | redback model name, e.g. `three_component_kilonova` |
| `--outdir` | *(required)* | output root (numbered subdirs created inside) |
| `--n-sim` | 2000 | number of prior samples |
| `--z-ref` | 1e-3 | reference redshift for abs-mag conversion |
| `--tmin / --tmax / --ntime` | 1e-3 / 150 / 401 | log time grid (days) |
| `--bin-size` | 50 | `.dat` files per numbered subdir |
| `--seed` | 0 | RNG seed (reproducible sampling) |
| `--prefix` | model name | output filename prefix |
| `--limit` | 0 | cap sims (0 = use `--n-sim`) |

```bash
redback_env/bin/python simulate_redback_teglon.py three_component_kilonova \
    --n-sim 256 --outdir <teglon>/web/models/three_component_kilonova
```

### 2. `simulate_observed_tiles.py` — simulate pointings (upper limits)
Creates `ObservedTile` + `ObservedTile_HealpixPixel` rows covering an event's high-probability
region, so the detection integral has pointings to work with. Mirrors TEGLON's own
`load_observed_tiles.py` (same `Tile`/`Detector`, `batch_insert`, `LOAD DATA` junction). Rows are
tagged `REDBACK_SIM_*` (easy cleanup). **Needs TEGLON + DB.** Run with `--dry_run` first.

| Flag | Default | Meaning |
|---|---|---|
| `--healpix_map_id` | 2 | target `HealpixMap.id` |
| `--nside` | 256 | **stored** NSIDE of the map (must match; check `MAX(Pixel_Index)`) |
| `--detector_id` | 55 | `Detector.id` (e.g. 55 SWOPE, 74 ZTF, 105 T80-S) |
| `--band_id` | 19 | `Band.id` (19 = SDSS r) |
| `--n_tiles` | 60 | number of pointings |
| `--mag_lim` | 21.0 | limiting magnitude (upper limit) per tile |
| `--merger_mjd` | GW190425 | merger MJD (tile epochs are relative to this) |
| `--mjd_after_min / --mjd_after_max` | 1.0 / 3.0 | tile-epoch window in days after merger (e.g. `0.5 2.0` = first 2 days) |
| `--min_pixel_separation` | 3 | min ring-spacing between tile centers (larger for wide detectors) |
| `--order_by` | prob | rank tile centers by 2-D `prob` or 4-D `netprob` |
| `--position_angle` | 0.0 | tile PA (deg) |
| `--field_prefix` | `REDBACK_SIM_` | FieldName tag (used by cleanup) |
| `--dry_run` | off | compute + print, do NOT insert |
| `--teglon_root` | — | TEGLON root if not auto-resolvable |

```bash
# 28 T80-S tiles, first 2 days only, r<23, for S190814bv (map 3):
python /app/redback_extension/simulate_observed_tiles.py --healpix_map_id 3 --nside 256 \
    --detector_id 105 --band_id 19 --n_tiles 30 --min_pixel_separation 5 --mag_lim 23.0 \
    --merger_mjd 58709.8824 --mjd_after_min 0.5 --mjd_after_max 2.0 --order_by netprob
```
**Cleanup** (removes only the simulated pointings for a map):
```sql
USE teglon;
DELETE oth FROM ObservedTile_HealpixPixel oth JOIN ObservedTile ot ON ot.id=oth.ObservedTile_id
  WHERE ot.HealpixMap_id=<ID> AND ot.FieldName LIKE 'REDBACK_SIM_%';
DELETE FROM ObservedTile WHERE HealpixMap_id=<ID> AND FieldName LIKE 'REDBACK_SIM_%';
```
…then delete the event's cached `web/events/<GWID>/pickles/*.pkl` before re-analyzing.

### 3. `model_detection_efficiency_redback_transients.py` — the engine
A faithful copy of TEGLON's `model_detection_efficiency.py` where the **only change is that the
free parameters are redback's**. Two modes; the detection algorithm is byte-identical to TEGLON's.

* **`--from_disk <dir>`** — analysis-only: parse a pre-simulated bank (generic redback comment) and
  run detection. **No redback needed** → runs in a stock container. *(recommended)*
* **simulate + analyze** — `--model <name> --n_sim <N>` simulates the bank in-process then analyzes
  (needs redback in the same env). `--analysis_detection False` = simulate + save only.

`.prob` output columns are the model's redback free-parameter names + `Prob`.

| Flag (extension) | Default | Meaning |
|---|---|---|
| `--from_disk` | "" | dir of a pre-simulated `.dat` bank → analysis-only, no redback |
| `--model` | two_component_kilonova_model | redback model (simulate mode / output naming) |
| `--n_sim` | 2000 | prior samples (simulate mode) |
| `--analysis_detection` | True | `False` → simulate + save only, skip detection |
| `--z_ref / --seed` | 1e-3 / 0 | abs-mag redshift / sampling seed |
| `--teglon_root` | — | TEGLON root if not auto-resolvable |
| **Inherited TEGLON flags** | | |
| `--gw_id` | — | event, e.g. `S190814bv` |
| `--merger_time_MJD` | GW190425 | **must match** the simulated pointings' merger |
| `--model_type` | kne | fills `{MODEL_TYPE}` in the output paths |
| `--model_base_path` | `./web/models/{MODEL_TYPE}` | bank location (simulate writes here) |
| `--model_output_dir` | `./web/events/{GWID}/model_detection/{MODEL_TYPE}` | `.prob` output dir |
| `--num_cpu` | 5 | multiprocessing workers |
| `--clobber` | off | clear cached event pickles (use after changing pointings) |

```bash
python /app/redback_extension/model_detection_efficiency_redback_transients.py \
    --gw_id S190814bv --model three_component_kilonova \
    --from_disk web/models/three_component_kilonova --model_type three_component_kilonova \
    --merger_time_MJD 58709.8824 --num_cpu 8 --clobber
```

### 4. `plot_redback_detection_efficiency.py` — detectability figures
Plots detection probability over **any two** free parameters (discovered from the `.prob` columns);
the other params are marginalized. Ejecta-physics overlays (KE contours, NS binding-energy region,
AT2017gfo markers) appear only for a velocity–mass plane. Needs **astropy + matplotlib only**.

| Flag | Default | Meaning |
|---|---|---|
| `--prob-glob` | *(required)* | glob for the `.prob` file(s) |
| `--x / --y` | *(required)* | the two free-param columns to plot |
| `--reduce` | scatter | collapse other params: `scatter` (sampled banks) / `max` / `mean` / `fix` |
| `--fix` | — | for `--reduce fix`, e.g. `mej_2=0.03 vej_2=0.2` |
| `--levels` | 0.01 0.05 0.10 0.30 | probability contour levels (fractions) |
| `--xscale / --yscale` | log / log | axis scales |
| `--event-label` | "" | title text |
| `--add-kne` | AT2017gfo | reference markers `'label,vej,mej[,colour]'` |
| `--show-points` | off | overlay the sampled models |
| `--dpi` | 300 | figure DPI |

```bash
redback_env/bin/python plot_redback_detection_efficiency.py \
    --prob-glob '<...>/Detection_Redback_three_component_kilonova_1.prob' \
    --x vej_1 --y mej_1 --show-points --event-label "GW190814 T80 r<23" --out fig.png
```

---

## End-to-end workflow

```
[1] simulate bank   (redback env)      simulate_redback_teglon.py <model> --n-sim N --outdir BANK
[2] simulate points (TEGLON container) simulate_observed_tiles.py --healpix_map_id ID --detector_id D ...
[3] analyze         (TEGLON container) model_detection_efficiency_redback_transients.py --from_disk BANK --gw_id EV ...
[4] plot            (redback env)      plot_redback_detection_efficiency.py --prob-glob '<.prob>' --x .. --y ..
```

The abs-mag bank from step 1 is **event-independent** — reuse it across events/detectors/depths.

## Notes / gotchas
* Pass the map's **stored** NSIDE to the pointing sim (`SELECT MAX(Pixel_Index)`: <786432 ⇒ 256).
* `--merger_time_MJD` (engine) must equal `--merger_mjd` (pointings).
* Detection needs `ObservedTile_HealpixPixel` populated and the pixels to have completeness.
* The container runs as root over the `/app` bind-mount, so the pickles / `.prob` it writes are
  root-owned; create `web/events/<GWID>/{pickles,model_detection/<type>}` via the container first.
* Verified end-to-end on GW190425 (35 ZTF, max 16.2%) and GW190814 (28 T80-S, first 2 d, r<23,
  max 41.7%).
