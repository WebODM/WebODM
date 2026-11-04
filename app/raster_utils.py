import rasterio
import re
import logging
import os
import subprocess
import numpy as np
import numexpr as ne
import json
import time
from rasterio.enums import ColorInterp
from rasterio.windows import Window
from app.vendor.rio_tiler.utils import has_alpha_band, linear_rescale
from app.vendor.rio_tiler.colormap import cmap as colormap, apply_cmap
from app.vendor.rio_tiler.errors import InvalidColorMapName
from app.api.hsvblend import hsv_blend
from app.api.hillshade import LightSource
from app.vendor.rio_tiler.io import COGReader
from webodm import settings

logger = logging.getLogger('app.logger')

ZOOM_EXTRA_LEVELS = 3

def extension_for_export_format(export_format):
    extensions = {
        'gtiff': 'tif',
        'gtiff-rgb': 'tif',
    }
    return extensions.get(export_format, export_format)

# Based on https://github.com/uav4geo/GeoDeep/blob/main/geodeep/slidingwindow.py
def compute_subwindows(window, max_window_size, overlap_pixels=0):
    col_off = int(window.col_off)
    row_off = int(window.row_off)
    width = int(window.width)
    height = int(window.height)

    win_size_x = min(max_window_size, width)
    win_size_y = min(max_window_size, height)

    step_size_x = win_size_x - overlap_pixels
    step_size_y = win_size_y - overlap_pixels

    last_x = col_off + width - win_size_x
    last_y = row_off + height - win_size_y
    x_offsets = list(range(col_off, last_x + 1, step_size_x))
    y_offsets = list(range(row_off, last_y + 1, step_size_y))

    if len(x_offsets) == 0 or x_offsets[-1] != last_x:
        x_offsets.append(last_x)
    if len(y_offsets) == 0 or y_offsets[-1] != last_y:
        y_offsets.append(last_y)

    # Generate the list of windows
    windows = []
    for y_offset in y_offsets:
        for x_offset in x_offsets:
            w = Window(
                    x_offset,
                    y_offset,
                    win_size_x,
                    win_size_y,
                )
            dst_w = Window(
                x_offset - window.col_off, 
                y_offset - window.row_off, 
                win_size_x, win_size_y
            )
             
            windows.append((w, dst_w))

    return windows

def compute_block_aligned_subwindows(src, win):
    subwins = []
    for _, w in src.block_windows(1):
        dst_w = Window(
            w.col_off - win.col_off, 
            w.row_off - win.row_off, 
            w.width, 
            w.height
        )
        subwins.append([w, dst_w])
    
    return subwins

def padded_window(w, pad):
    return Window(w.col_off - pad, w.row_off - pad, w.width + pad * 2, w.height + pad * 2)

def export_raster(input, output, progress_callback=None, **opts):
    now = time.time()

    current_progress = 0
    last_update = 0

    def p(text, perc=0):
        nonlocal current_progress
        nonlocal last_update

        t = time.time()
        current_progress += perc

        if t - last_update >= 1:
            if progress_callback is not None:
                progress_callback(text, current_progress)
            last_update = t

    epsg = opts.get('epsg')
    proj = opts.get('proj')
    expression = opts.get('expression')
    export_format = opts.get('format')
    rescale = opts.get('rescale')
    color_map = opts.get('color_map')
    hillshade = opts.get('hillshade')
    asset_type = opts.get('asset_type')
    name = opts.get('name', 'raster') # KMZ specific
    crop = opts.get('crop')

    dem = asset_type in ['dsm', 'dtm']
    path_base, _ = os.path.splitext(output)
    resampling = 'nearest'
    if dem:
        resampling = 'bilinear'

    if crop is not None:
        crop_geojson = os.path.join(path_base, "crop.geojson")
        raster_vrt = os.path.join(path_base, "raster.vrt")

        os.makedirs(os.path.dirname(crop_geojson), exist_ok=True)
        with open(crop_geojson, "w", encoding="utf-8") as f:
            f.write(json.dumps(crop))

        subprocess.check_output(["gdalwarp", "-cutline", crop_geojson,
                '--config', 'GDALWARP_DENSIFY_CUTLINE', 'NO', 
                '-crop_to_cutline', '-of', 'VRT', '-r', resampling,
                 input, raster_vrt])

        input = raster_vrt
    
    with COGReader(input) as ds_src:
        src = ds_src.dataset
        profile = src.meta.copy()
        units = ds_src.dataset.units
        win = Window(0, 0, src.width, src.height)
            
        # Output format
        driver = "GTiff"
        compress = None
        window_size = 512
        with_alpha = True
        rgb = False
        bigtiff = False
        indexes = src.indexes
        output_raster = output
        jpg_background = 255 # white
        reproject = src.crs is not None and ((epsg is not None and src.crs.to_epsg() != epsg) or proj is not None)

        # KMZ is special, we just export it as GeoTIFF
        # and then call GDAL to tile/package it
        kmz = export_format == "kmz"
        if kmz:
            export_format = "gtiff-rgb"
            output_raster = path_base + ".kmz.tif"

        # JPG and PNG are exported to GeoTIFF only if reprojection is needed
        jpg = export_format == "jpg"
        png = export_format == "png"
        if reproject:
            if jpg:
                export_format = 'gtiff-rgb'
                path_base, _ = os.path.splitext(output)
                output_raster = path_base + ".jpg.tif"
            if png:
                export_format = 'gtiff-rgb'
                path_base, _ = os.path.splitext(output)
                output_raster = path_base + ".png.tif"

        JPEG_PX_LIMIT = 65000 # Due to 16bit fields for w,h in JPEG standard
        if jpg and (src.width > JPEG_PX_LIMIT or src.height > JPEG_PX_LIMIT):
            raise Exception(f"Image is too large (> {JPEG_PX_LIMIT}px) for JPEG. Use TIFF (RGB) instead.")

        if export_format == "jpg":
            driver = "JPEG"
            profile.update(quality=90)
            band_count = 3
            with_alpha = False
            rgb = True
        elif export_format == "png":
            driver = "PNG"
            band_count = 4
            rgb = True
        elif export_format == "gtiff-rgb":
            compress = "JPEG"
            bigtiff = True
            profile.update(jpeg_quality=90)
            band_count = 4
            rgb = True
            if jpg:
                band_count = 3
                with_alpha = False
        else:
            bigtiff = True
            compress = "DEFLATE"
            band_count = src.count

        if bigtiff:
            profile.update(BIGTIFF='IF_SAFER', BLOCKXSIZE=window_size, BLOCKYSIZE=window_size, TILED='YES')

        if reproject:
            path_base, _ = os.path.splitext(output_raster)
            output_raster = path_base + ".base.tif"

        if compress is not None and not reproject:
            profile.update(compress=compress)
            profile.update(predictor=2 if compress == "DEFLATE" else 1)

        if rgb and rescale is None:
            # Compute min max
            nodata = None
            if asset_type == 'orthophoto':
                nodata = 0
            md = ds_src.metadata(pmin=2.0, pmax=98.0, hist_options={"bins": 255}, nodata=nodata)
            rescale = [md['statistics']['1']['min'], md['statistics']['1']['max']]

        ci = src.colorinterp
        alpha_index = None
        if has_alpha_band(src):
            alpha_index = src.colorinterp.index(ColorInterp.alpha) + 1
        
        subwins = compute_subwindows(win, window_size)
        # subwins = compute_block_aligned_subwindows(src, win)

        if rgb and expression is None:
            # More than 4 bands?
            if len(ci) > 4:
                # Try to find RGBA band order
                if ColorInterp.red in ci and \
                        ColorInterp.green in ci and \
                        ColorInterp.blue in ci and \
                        ColorInterp.alpha in ci:
                    indexes = (ci.index(ColorInterp.red) + 1,
                                ci.index(ColorInterp.green) + 1,
                                ci.index(ColorInterp.blue) + 1,
                                ci.index(ColorInterp.alpha) + 1)
                # No? pick first three + alpha
                elif ColorInterp.alpha in ci:
                    indexes = (1, 2, 3, ci.index(ColorInterp.alpha) + 1)
            
            # Only 2 bands (common with thermal)?
            elif len(ci) == 2 and ColorInterp.gray in ci and ColorInterp.alpha in ci:
                indexes = (ci.index(ColorInterp.gray) + 1,) * 3 + \
                           (ci.index(ColorInterp.alpha) + 1, )

        cmap = None
        if color_map:
            try:
                cmap = colormap.get(color_map)
            except InvalidColorMapName:
                logger.warning("Invalid colormap {}".format(color_map))


        def process(arr, skip_rescale=False, skip_background=False, skip_type=False, mask=None, includes_alpha=True, drop_last_band=False):
            if not skip_rescale and rescale is not None:
                if includes_alpha:
                    arr[:-1, :, :] = linear_rescale(arr[:-1, :, :], in_range=rescale)
                else:
                    arr = linear_rescale(arr, in_range=rescale)
            if not skip_background and (mask is not None or includes_alpha):
                if mask is not None:
                    background = mask==0
                elif includes_alpha:
                    background = arr[-1]==0
                if includes_alpha:
                    arr[:-1, :, :][:, background] = jpg_background
                else:
                    arr[:, background] = jpg_background
            if not skip_type and rgb and arr.dtype != np.uint8:
                if includes_alpha:
                    arr[-1][arr[-1] > 255] = 255
                    
                arr = arr.astype(np.uint8)
            
            if drop_last_band:
                return arr[:-1, :, :]
            else:
                return arr

        def update_rgb_colorinterp(dst):
            if with_alpha:
                dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha]
            else:
                dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]

        profile.update(driver=driver, count=band_count)
        if rgb:
            profile.update(dtype=rasterio.uint8)

        if dem and rgb and profile.get('nodata') is not None:
            profile.update(nodata=None)

        
        post_perc = 20 if reproject or kmz else 0
        num_wins = len(subwins)
        progress_per_win = (100 - post_perc) / num_wins if num_wins > 0 else 0

        if expression is not None:
            # Apply band math
            if rgb:
                profile.update(dtype=rasterio.uint8, count=band_count)
            else:
                profile.update(dtype=rasterio.float32, count=1, nodata=-9999)

            bands_names = ["b{}".format(b) for b in tuple(sorted(set(re.findall(r"b(?P<bands>[0-9]{1,2})", expression))))]
            rgb_expr = expression.split(",")
            indexes = tuple([int(b.replace("b", "")) for b in bands_names])

            if alpha_index is not None:
                indexes += (alpha_index, )

            with rasterio.open(output_raster, 'w', **profile) as dst:
                for idx, (w, dst_w) in enumerate(subwins):
                    p(f"Processing tile {idx}/{num_wins}", progress_per_win)

                    data = src.read(indexes=indexes, window=w, out_dtype=np.float32)
                    arr = dict(zip(bands_names, data))
                    arr = np.array([np.nan_to_num(ne.evaluate(bloc.strip(), local_dict=arr)) for bloc in rgb_expr])

                    # Set nodata values
                    index_band = arr[0]
                    mask = None
                    if alpha_index is not None:
                        # -1 is the last band = alpha
                        mask = data[-1] != 0
                        index_band[~mask] = -9999

                    # Remove infinity values
                    index_band[index_band>1e+30] = -9999
                    index_band[index_band<-1e+30] = -9999

                    # Make sure this is float32
                    arr = arr.astype(np.float32)

                    # Apply colormap?
                    if rgb and cmap is not None:
                        rgb_data, _ = apply_cmap(process(arr, skip_background=True, includes_alpha=False), cmap)
                        dst.write(process(rgb_data, skip_rescale=True, mask=mask, includes_alpha=False), window=dst_w, indexes=(1,2,3))

                        if with_alpha:
                            dst.write(mask.astype(np.uint8) * 255, 4, window=dst_w)

                        update_rgb_colorinterp(dst)
                    else:
                        # Raw
                        dst.write(process(arr), window=dst_w) 
        elif dem:
            # Apply hillshading, colormaps to elevation
            with rasterio.open(output_raster, 'w', **profile) as dst:
                # Copy units information
                if export_format == "gtiff" and not rgb and len(units) == len(dst.units):
                    dst.units = units

                for idx, (w, dst_w) in enumerate(subwins):
                    p(f"Processing tile {idx}/{num_wins}", progress_per_win)

                    # Apply colormap?
                    if rgb and cmap is not None:
                        nodata = profile.get('nodata')
                        if nodata is None:
                            nodata = -9999

                        pad = 16
                        elevation = src.read(window=padded_window(w, pad), boundless=True, fill_value=nodata, out_shape=(
                            1,
                            window_size + pad * 2,
                            window_size + pad * 2,
                        ), resampling=rasterio.enums.Resampling.bilinear)[:1][0]

                        elevation[0:pad, 0:pad] = nodata
                        elevation[pad+window_size:pad*2+window_size, 0:pad] = nodata
                        elevation[0:pad, pad+window_size:pad*2+window_size] = nodata
                        elevation[pad+window_size:pad*2+window_size, pad+window_size:pad*2+window_size] = nodata

                        mask = elevation != nodata

                        intensity = None
                        if hillshade is not None and hillshade > 0:
                            delta_scale = ZOOM_EXTRA_LEVELS ** 2
                            dx = src.meta["transform"][0] * delta_scale
                            dy = src.meta["transform"][4] * delta_scale
                            ls = LightSource(azdeg=315, altdeg=45)

                            intensity = ls.hillshade(elevation, dx=dx, dy=dy, vert_exag=hillshade)
                            intensity = intensity[pad:pad+window_size, pad:pad+window_size]
                            intensity = intensity * 255.0

                        rgb_data, _ = apply_cmap(process(elevation[pad:window_size+pad, pad:window_size+pad][np.newaxis,:], skip_background=True, includes_alpha=False), cmap)

                        if intensity is not None:
                            rgb_data = hsv_blend(rgb_data, intensity)
                        
                        mask = mask[pad:window_size+pad, pad:window_size+pad]
                        dst.write(process(rgb_data, skip_rescale=True, mask=mask, includes_alpha=False), window=dst_w, indexes=(1,2,3))
                        if with_alpha:
                            dst.write(mask.astype(np.uint8) * 255, 4, window=dst_w)

                        update_rgb_colorinterp(dst)
                    else:
                        # Raw
                        arr = src.read(window=w)[:1]
                        dst.write(process(arr), window=dst_w)
        else:
            # Copy bands as-is
            with rasterio.open(output_raster, 'w', **profile) as dst:
                for idx, (w, dst_w) in enumerate(subwins):
                    p(f"Processing tile {idx}/{num_wins}", progress_per_win)

                    arr = src.read(indexes=indexes, window=w)
                    dst.write(process(arr, drop_last_band=not with_alpha), window=dst_w)

                new_ci = [src.colorinterp[idx - 1] for idx in indexes]
                if not with_alpha:
                    new_ci = [ci for ci in new_ci if ci != ColorInterp.alpha]
                    
                dst.colorinterp = new_ci
        
        if kmz:
            subprocess.check_output(["gdal_translate", "-of", "KMLSUPEROVERLAY", 
                                        "-co", "Name={}".format(name),
                                        "-co", "FORMAT=AUTO", output_raster, output])
            p("Finalizing", post_perc)

        elif reproject:
            output_vrt = path_base + ".vrt"

            if epsg is not None:
                t_srs = f"EPSG:{epsg}"
            elif proj is not None:
                t_srs = proj

            subprocess.check_output(["gdalwarp", "-r", "near" if resampling == "nearest" else resampling, 
                                    "-of", "VRT",
                                    "-t_srs", t_srs,
                                    output_raster, output_vrt])
            gt_args = ["-r", resampling, "--config", "GDAL_CACHEMAX", "25%"]
            if bigtiff and not jpg and not png:
                gt_args += ["-co", "BIGTIFF=IF_SAFER", 
                            "-co", "BLOCKXSIZE=512", 
                            "-co", "BLOCKYSIZE=512", 
                            "-co", "NUM_THREADS=%s" % settings.WORKERS_MAX_THREADS,]

            if compress and not png:
                if jpg:
                    gt_args += ["-co", "QUALITY=90"]
                else:
                    gt_args += ["-co", f"COMPRESS={compress}", 
                                "-co", "PREDICTOR=2"]

            subprocess.check_output(["gdal_translate"] +  
                                    gt_args +
                                    [output_vrt, output])
            
            if os.path.isfile(output_raster):
                os.unlink(output_raster)

            p("Finalizing", post_perc)
            
        logger.info(f"Exported {output} in {round(time.time() - now, 2)}s")
        
