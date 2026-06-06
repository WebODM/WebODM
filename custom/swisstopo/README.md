# SWISSIMAGE provider for the GCP Interface

This overlay adds the swisstopo SWISSIMAGE WMTS provider to the WebODM GCP
Interface. Native tiles are requested through zoom level 20 and Leaflet
overzooms the imagery through level 28.

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
