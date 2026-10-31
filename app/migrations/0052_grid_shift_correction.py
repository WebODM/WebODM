import logging
from django.db import migrations

logger = logging.getLogger('app.logger')


def update_shifted_tasks(apps, schema_editor):
    # Attempt to update tasks processed before datum grid files were available
    try:
        import os
        import json
        import math
        from pyproj import CRS
        from pyproj.transformer import TransformerGroup
        from webodm import settings
        from app.geoutils import get_raster_bounds_geojson
        from app.grids import check_download_grid_for

        Task = apps.get_model('app', 'Task')

        def has_grid(t):
            d = t.definition or ""
            return "grids=" in d or "gridshift" in d

        def init_crs(key):
            kind, value = key
            return CRS.from_epsg(value) if kind == 'epsg' else CRS.from_wkt(value)

        def populate_extent_fields(t):
            # Same logic as Task.populate_extent_fields, which is not
            # available on the historical model
            assets_dir = os.path.join(settings.MEDIA_ROOT, "project", str(t.project_id), "task", str(t.id), "assets")
            for raster_path, field in [
                    (os.path.join(assets_dir, "odm_orthophoto", "odm_orthophoto.tif"), 'orthophoto_extent'),
                    (os.path.join(assets_dir, "odm_dem", "dsm.tif"), 'dsm_extent'),
                    (os.path.join(assets_dir, "odm_dem", "dtm.tif"), 'dtm_extent')]:
                if os.path.exists(raster_path):
                    extent = get_raster_bounds_geojson(raster_path)
                    if extent is not None:
                        setattr(t, field, extent)

        # Group task IDs (not instances, to keep memory usage low) by CRS
        groups = {}
        for t in Task.objects.all().only('id', 'epsg', 'wkt').iterator():
            if t.epsg is not None:
                key = ('epsg', t.epsg)
            elif t.wkt is not None:
                key = ('wkt', t.wkt)
            else:
                continue
            groups.setdefault(key, []).append(t.id)

        # Find CRSs with missing grids before downloading anything
        pending = {}
        for key, task_ids in groups.items():
            try:
                tg = TransformerGroup("EPSG:4326", init_crs(key), always_xy=True)
                if not tg.best_available:
                    pending[key] = task_ids
            except Exception as e:
                logger.warning(f"Cannot check grids for {key}: {str(e)}")

        if len(pending) == 0:
            return

        # Record of successfully migrated tasks
        updated = []

        for key, task_ids in pending.items():
            kind, value = key
            try:
                check_download_grid_for(Task.objects.only('id', 'epsg', 'wkt').get(pk=task_ids[0]), max_retries=1)

                tg = TransformerGroup("EPSG:4326", init_crs(key), always_xy=True)
                if not tg.best_available:
                    logger.warning(f"Grids still unavailable for {kind} {value}, skipping {len(task_ids)} task(s)")
                    continue

                grid_tf = next((t for t in tg.transformers if has_grid(t)), None)
                old_tf = next((t for t in tg.transformers if not has_grid(t)), None)
                if grid_tf is None or old_tf is None:
                    logger.warning(f"No grid/grid-free transform for {kind} {value}, skipping {len(task_ids)} task(s)")
                    continue

                def fix(lon_bad, lat_bad):
                    e, n = old_tf.transform(lon_bad, lat_bad)
                    lon, lat = grid_tf.transform(e, n, direction="INVERSE")
                    if not (math.isfinite(lon) and math.isfinite(lat)):
                        raise ValueError(f"infinite grid shift ({lon_bad}, {lat_bad})")
                    return lon, lat

                for task_id in task_ids:
                    try:
                        t = Task.objects.get(pk=task_id)

                        # Re-derive extents from the rasters
                        populate_extent_fields(t)

                        # Adjust crop
                        if t.crop is not None:

                            crop = t.crop
                            if 'coordinates' in crop:
                                crop['coordinates'] = [
                                    [list(fix(lon_bad, lat_bad)) for lon_bad, lat_bad in ring]
                                    for ring in crop['coordinates']
                                ]
                                t.crop = crop

                        t.save()
                        updated.append({'id': str(task_id), kind: value})
                        logger.info(f"Applied grid shift to task {task_id}")
                    except Exception as e:
                        logger.warning(f"Cannot apply grid shift to task {task_id}, skipping: {str(e)}")
            except Exception as e:
                logger.warning(f"Cannot apply grid shift for {kind} {value}: {str(e)}")

        if len(updated) > 0:
            updated_file = os.path.join(settings.MEDIA_ROOT, 'tmp', 'updated_grids.json')
            try:
                os.makedirs(os.path.dirname(updated_file), exist_ok=True)
                with open(updated_file, 'w') as f:
                    json.dump(updated, f, indent=2)
                logger.info(f"Wrote {updated_file}")
            except Exception as e:
                logger.warning(f"Cannot write {updated_file}: {str(e)}")
    except Exception as e:
        logger.warning(f"Grid shift migration failed: {str(e)}")


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('app', '0051_init_basemaps'),
    ]

    operations = [
        migrations.RunPython(update_shifted_tasks, migrations.RunPython.noop),
    ]
