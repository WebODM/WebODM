import logging
import os
import subprocess
import json
import rasterio
import shutil
from app.geoutils import geom_transform_wkt_bbox
from django.contrib.gis.geos import GEOSGeometry
from app.security import double_quote
from osgeo import osr

logger = logging.getLogger('app.logger')

def export_pointcloud(input, output, **opts):
    epsg = opts.get('epsg')
    proj = opts.get('proj')
    export_format = opts.get('format')
    resample = float(opts.get('resample', 0))
    crop_wkt = opts.get('crop')
    crop_reference = opts.get('crop_reference')

    resample_args = []
    reprojection_args = []
    extra_args = []
    crop_args = []

    if epsg:
        reprojection_args = ["reprojection",
                            "--filters.reprojection.out_srs=%s" % double_quote("EPSG:" + str(epsg))]
    elif proj:
        srs = osr.SpatialReference()
        if srs.ImportFromProj4(proj) != 0:
            raise Exception(f"Invalid PROJ string: {proj}")
        reprojection_args = ["reprojection",
                            "--filters.reprojection.out_srs=%s" % proj]
        
    if export_format == "ply":
        extra_args = ['--writers.ply.dims', 'X,Y,Z,Red,Green,Blue',
                      '--writers.ply.sized_types', 'false',
                      '--writers.ply.storage_mode', 'little endian']

    if resample > 0:
        resample_args = ['sample', '--filters.sample.radius=%s' % resample]
    
    if crop_wkt is not None and crop_reference is not None:
        with rasterio.open(crop_reference) as ds:
            crop = GEOSGeometry(crop_wkt)
            crop.srid = 4326
            cutline, bounds = geom_transform_wkt_bbox(crop, ds, wkt_crs="projected")

        crop_args =  ['crop', "--filters.crop.polygon=%s" % cutline]

    subprocess.check_output([shutil.which("pdal"), "translate", input, output] + resample_args + reprojection_args + crop_args + extra_args)


def is_pointcloud_georeferenced(laz_path):
    if not os.path.isfile(laz_path):
        return False

    try:
        j = json.loads(subprocess.check_output([shutil.which("pdal"), "info", "--summary", laz_path]))
        return 'summary' in j and 'srs' in j['summary']
    except Exception as e:
        logger.warning(e)
        return True # Assume georeferenced
