# Swiss additions for the GCP Interface

This overlay connects the GCP Interface to the basemaps managed by WebODM at
`/admin/app/basemap/`. TMS and WMS entries, the configured default basemap,
zoom levels, attribution, subdomains and WMS options are passed to the GCP map.
Leaflet overzooms imagery through level 28.

SWISSIMAGE is installed as a normal WebODM basemap by migration, so it can be
edited, disabled by deletion, or selected as the default from the admin.

It also registers the Swiss LV95 coordinate reference system with the bundled
Proj4 library. Existing GCP files can use `EPSG:2056` on their first line:

```text
EPSG:2056
2600000 1200000 500 1024 768 image.jpg
```

The existing `posm-gcpi` plugin, managed at `/admin/app/plugin/`, includes a
checkbox to compare an existing GCP altitude
with the official swisstopo terrain height whenever its marker is selected.
The comparison is enabled by default. If the returned height differs by more
than 0.1 metre, the user can confirm replacing the GCP altitude.

The same panel also includes a button to check all loaded map GCPs. It displays
one summary of the differences and can replace all differing altitudes after a
single confirmation. Coordinates are sent in `EPSG:2056` and the `COMB`
elevation model is used.

Build and start WebODM with:

```sh
docker compose \
  -f docker-compose.yml \
  -f docker-compose.swisstopo.yml \
  up -d --build
```

After updating the upstream WebODM code, rebuild the custom image:

```sh
docker compose \
  -f docker-compose.yml \
  -f docker-compose.swisstopo.yml \
  build --pull webapp

docker compose \
  -f docker-compose.yml \
  -f docker-compose.swisstopo.yml \
  up -d
```

The build fails intentionally if the upstream GCPI bundle changes in a way
that makes the patch unsafe to apply.

Run the bundle patch tests with:

```sh
node custom/swisstopo/patch-swisstopo.test.js
```

## Sync with upstream WebODM

Keep `master` identical to the official WebODM repository and rebase this
custom branch after each upstream update:

```sh
git switch master
git fetch upstream
git merge --ff-only upstream/master
git push origin master

git switch codex/swisstopo-gcp
git rebase master
git push --force-with-lease
```

Then rebuild and restart the custom image with the commands above. Using
`--force-with-lease` is appropriate here because this is a dedicated personal
customization branch; it refuses to overwrite unexpected remote changes.
