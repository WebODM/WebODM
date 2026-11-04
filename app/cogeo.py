import os
import logging
import tempfile
import shutil
import subprocess
from app.vendor.validate_cloud_optimized_geotiff import validate
from webodm import settings

logger = logging.getLogger('app.logger')

def valid_cogeo(src_path):
    """
    Validate a Cloud Optimized GeoTIFF
    :param src_path: path to GeoTIFF
    :return: true if the GeoTIFF is a cogeo, false otherwise
    """
    warnings, errors, details = validate(src_path, full_check=True)
    return not errors and not warnings


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

    logger.info("Optimizing %s as Cloud Optimized GeoTIFF" % src_path)
    return make_cogeo(src_path)


def make_cogeo(src_path):
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
