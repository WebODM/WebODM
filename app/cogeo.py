import os
import logging
import tempfile
import shutil
import rasterio
import re
import subprocess
from rio_tiler.utils import has_alpha_band
from webodm import settings

logger = logging.getLogger('app.logger')

def valid_cogeo(src_path):
    """
    Validate a Cloud Optimized GeoTIFF
    :param src_path: path to GeoTIFF
    :return: true if the GeoTIFF is a cogeo, false otherwise
    """
    try:
        from app.vendor.validate_cloud_optimized_geotiff import validate
        warnings, errors, details = validate(src_path, full_check=True)
        return not errors and not warnings
    except ModuleNotFoundError:
        logger.warning("Using legacy cog_validate (osgeo.gdal package not found)")
        try:
            from rio_cogeo.cogeo import cog_validate
        except ModuleNotFoundError:
            logger.warning("Cannot use cog_validate (rio_cogeo is not installed)")
            return False
        # Legacy
        return cog_validate(src_path, strict=True)


def assure_cogeo(src_path):
    """
    Guarantee that the .tif passed as an argument is a Cloud Optimized GeoTIFF (cogeo)
    If the path is not a cogeo, it is destructively converted into a cogeo.
    If the file cannot be converted, the function does not change the file
    :param src_path: path to GeoTIFF (cogeo or not)
    :return: None
    """

    if not os.path.isfile(src_path):
        logger.warning("Cannot validate cogeo: %s (file does not exist)" % src_path)
        return

    if valid_cogeo(src_path):
        return

    # Not a cogeo
    logger.info("Optimizing %s as Cloud Optimized GeoTIFF" % src_path)

    # Check if we have GDAL >= 3.1
    use_legacy = False
    gdal_version = get_gdal_version()
    if gdal_version:
        major, minor, build = gdal_version
        
        # GDAL 2 and lower
        if major <= 2:
            use_legacy = True
        
        # GDAL 3.0 and lower
        if major == 3 and minor < 1:
            use_legacy = True
    else:
        # This shouldn't happen
        use_legacy = True
        
    if use_legacy:
        logger.warning("Using legacy implementation (GDAL >= 3.1 not found)")
        return make_cogeo_legacy(src_path)
    else:
        return make_cogeo_gdal(src_path)

def get_gdal_version():
    # Bit of a hack without installing 
    # python bindings
    gdal_translate = shutil.which('gdal_translate')
    if not gdal_translate:
        return None
    
    # Get version
    version_output = subprocess.check_output([gdal_translate, "--version"]).decode('utf-8')
    
    m = re.match(r"GDAL\s+([\d+])\.([\d+])\.([\d+]),\s+released", version_output)
    if not m:
        return None
    
    return tuple(map(int, m.groups()))


def make_cogeo_gdal(src_path):
    """
    Make src_path a Cloud Optimized GeoTIFF.
    Requires GDAL >= 3.1
    """

    tmpfile = tempfile.mktemp('_cogeo.tif', dir=settings.MEDIA_TMP)
    swapfile = tempfile.mktemp('_cogeo_swap.tif', dir=settings.MEDIA_TMP)

    try:
        subprocess.run(["gdal_translate", "-of", "COG",
                        "-co", "BLOCKSIZE=256",
                        "-co", "COMPRESS=deflate",
                        "-co", "NUM_THREADS=ALL_CPUS",
                        "-co", "BIGTIFF=IF_SAFER",
                        "-co", "RESAMPLING=NEAREST",
                        "--config", "GDAL_NUM_THREADS", "ALL_CPUS",
                        src_path, tmpfile])
    except Exception as e:
        logger.warning("Cannot create Cloud Optimized GeoTIFF: %s" % str(e))

    if os.path.isfile(tmpfile):
        shutil.move(src_path, swapfile) # Move to swap location

        try:
            shutil.move(tmpfile, src_path)
        except IOError as e:
            logger.warning("Cannot move %s to %s: %s" % (tmpfile, src_path, str(e)))
            shutil.move(swapfile, src_path) # Attempt to restore
            raise e

        if os.path.isfile(swapfile):
            os.remove(swapfile)

        return True
    else:
        return False

def make_cogeo_legacy(src_path):
    """
    Make src_path a Cloud Optimized GeoTIFF
    This implementation does not require GDAL >= 3.1
    but sometimes (rarely) hangs for unknown reasons
    """
    try:
        from rio_cogeo.cogeo import cog_translate
    except ModuleNotFoundError:
        logger.warning("Cannot use cog_translate (rio_cogeo is not installed)")
        return False

    tmpfile = tempfile.mktemp('_cogeo.tif', dir=settings.MEDIA_TMP)
    swapfile = tempfile.mktemp('_cogeo_swap.tif', dir=settings.MEDIA_TMP)

    with rasterio.open(src_path) as dst:
        output_profile = dict(
            blockxsize=256,
            blockysize=256,
            driver='GTiff',
            tiled=True,
            compress=dst.profile.get('compress', 'deflate'),
            interleave='pixel'
        )

        # Dataset Open option (see gdalwarp `-oo` option)
        config = dict(
            GDAL_NUM_THREADS="ALL_CPUS",
            GDAL_TIFF_INTERNAL_MASK=True,
            GDAL_TIFF_OVR_BLOCKSIZE="128",
        )

        nodata = None
        if has_alpha_band(dst) and dst.meta['dtype'] == 'uint16':
            nodata = 0.0 # Hack to workaround https://github.com/cogeotiff/rio-cogeo/issues/112

        cog_translate(dst, tmpfile, output_profile, nodata=nodata,
                      config=config, in_memory=False,
                      quiet=True, web_optimized=False)
        # web_optimized reduces the dimension of the raster, as well as reprojecting to EPSG:3857
        # we want to keep resolution and projection at the tradeoff of slightly slower tile render speed

    if os.path.isfile(tmpfile):
        shutil.move(src_path, swapfile) # Move to swap location

        try:
            shutil.move(tmpfile, src_path)
        except IOError as e:
            logger.warning("Cannot move %s to %s: %s" % (tmpfile, src_path, str(e)))
            shutil.move(swapfile, src_path) # Attempt to restore
            raise e

        if os.path.isfile(swapfile):
            os.remove(swapfile)

        return True
    else:
        return False
