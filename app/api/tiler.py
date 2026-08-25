import json
import rio_tiler.utils
from rasterio.enums import ColorInterp
from rasterio.crs import CRS
from rasterio.features import bounds as featureBounds
from rasterio.errors import NotGeoreferencedWarning
import urllib
import os
from .common import get_asset_download_filename
from django.http import HttpResponse
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.utils import has_alpha_band, \
    non_alpha_indexes, render, create_cutline
from rio_tiler.utils import _stats as raster_stats
from rio_tiler.models import ImageStatistics, ImageData
from rio_tiler.models import Metadata as RioMetadata
from rio_tiler.profiles import img_profiles
from rio_tiler.colormap import cmap as colormap, apply_cmap
from rio_tiler.io import COGReader
from rio_tiler.errors import InvalidColorMapName, AlphaBandWarning
import numpy as np
from .custom_colormaps_helper import custom_colormaps
from app.raster_utils import extension_for_export_format, ZOOM_EXTRA_LEVELS
from .hsvblend import hsv_blend
from .hillshade import LightSource
from .formulas import lookup_formula, get_algorithm_list, get_auto_bands
from .tasks import TaskNestedView
from app.geoutils import geom_transform_wkt_bbox, get_rasterio_to_meters_factor
from rest_framework import exceptions
from rest_framework.response import Response
from worker.tasks import export_raster, export_pointcloud
from django.utils.translation import gettext as _
import warnings
from functools import lru_cache
from osgeo import osr

# Disable: NotGeoreferencedWarning: Dataset has no geotransform, gcps, or rpcs. The identity matrix be returned.
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

# Disable: Alpha band was removed from the output data array
warnings.filterwarnings("ignore", category=AlphaBandWarning)

# Disable: UserWarning: Warning: 'partition' will ignore the 'mask' of the MaskedArray.
warnings.filterwarnings("ignore", category=UserWarning)

# Disable: RuntimeWarning: overflow encountered in reduce
warnings.filterwarnings("ignore", category=RuntimeWarning)

for custom_colormap in custom_colormaps:
    colormap = colormap.register(custom_colormap)

@lru_cache(maxsize=128)
def get_colormap_encoded_values(cmap):
    values = colormap.get(cmap).values()
    # values = [[R, G, B, A], [R, G, B, A], ...]
    encoded_values = []
    for rgba in values:
        # Pack R, G, B, A (each 0-255) into a 32-bit integer
        # Format: 0xRRGGBBAA (R in most significant byte)
        encoded = (rgba[0] << 24) | (rgba[1] << 16) | (rgba[2] << 8) | rgba[3]
        encoded_values.append(encoded)

    return encoded_values
    
def get_zoom_safe(src_dst):
    minzoom, maxzoom = src_dst.spatial_info["minzoom"], src_dst.spatial_info["maxzoom"]
    if maxzoom < minzoom:
        maxzoom = minzoom
    return minzoom, maxzoom


def get_tile_url(task, tile_type, query_params):
    url = '/api/projects/{}/tasks/{}/{}/tiles/{{z}}/{{x}}/{{y}}'.format(task.project.id, task.id, tile_type)
    params = {}

    for k in ['formula', 'bands', 'rescale', 'color_map', 'hillshade']:
        if query_params.get(k):
            params[k] = query_params.get(k)
    
    if len(params) > 0:
        url = url + '?' + urllib.parse.urlencode(params)

    return url


def get_extent(task, tile_type):
    extent_map = {
        'orthophoto': task.orthophoto_extent,
        'dsm': task.dsm_extent,
        'dtm': task.dtm_extent,
    }
    if not tile_type in extent_map:
        raise exceptions.NotFound()

    extent = extent_map[tile_type]

    if extent is None:
        raise exceptions.NotFound()

    return extent


def get_raster_path(task, tile_type):
    return task.get_asset_download_path(tile_type + ".tif")

def get_pointcloud_path(task):
    return task.get_asset_download_path("georeferenced_model.laz")


class TileJson(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, tile_type=""):
        """
        Get tile.json for this tasks's asset type
        """
        task = self.get_and_check_task(request, pk)

        raster_path = get_raster_path(task, tile_type)
        if not os.path.isfile(raster_path):
            raise exceptions.NotFound()

        with COGReader(raster_path) as src:
            minzoom, maxzoom = get_zoom_safe(src)

        return Response({
            'tilejson': '2.1.0',
            'name': task.name,
            'version': '1.0.0',
            'scheme': 'xyz',
            'tiles': [get_tile_url(task, tile_type, self.request.query_params)],
            'minzoom': minzoom - ZOOM_EXTRA_LEVELS,
            'maxzoom': maxzoom + ZOOM_EXTRA_LEVELS,
            'bounds': get_extent(task, tile_type).extent
        })


class Bounds(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, tile_type=""):
        """
        Get the bounds for this tasks's asset type
        """
        task = self.get_and_check_task(request, pk)

        return Response({
            'url': get_tile_url(task, tile_type, self.request.query_params),
            'bounds': get_extent(task, tile_type).extent
        })


class Metadata(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, tile_type=""):
        """
        Get the metadata for this tasks's asset type
        """
        task = self.get_and_check_task(request, pk)
        formula = self.request.query_params.get('formula')
        bands = self.request.query_params.get('bands')
        defined_range = self.request.query_params.get('range')
        crop = self.request.query_params.get('crop') == '1'
        boundaries_feature = self.request.query_params.get('boundaries')
        if formula == '': formula = None
        if bands == '': bands = None
        if defined_range == '': defined_range = None
        if boundaries_feature == '': boundaries_feature = None
        if boundaries_feature is not None:
            boundaries_feature = json.loads(boundaries_feature)
        
        is_auto_bands_match = False
        is_auto_bands = False
        if bands == 'auto' and formula:
            is_auto_bands = True
            bands, is_auto_bands_match = get_auto_bands(task.orthophoto_bands, formula)
        try:
            expr, hrange = lookup_formula(formula, bands)
            if defined_range is not None:
                new_range = tuple(map(float, defined_range.split(",")[:2]))
                #Validate rescaling range
                if hrange is not None and (new_range[0] < hrange[0] or new_range[1] > hrange[1]):
                    pass
                else:
                    hrange = new_range

        except ValueError as e:
            raise exceptions.ValidationError(str(e))
        pmin, pmax = 2.0, 98.0
        raster_path = get_raster_path(task, tile_type)
        if not os.path.isfile(raster_path):
            raise exceptions.NotFound()

        to_meter = 1.0
        try:
            with COGReader(raster_path) as src:

                band_count = src.dataset.meta['count']
                if boundaries_feature is not None:
                    cutline = create_cutline(src.dataset, boundaries_feature, CRS.from_string('EPSG:4326'))
                    bounds = featureBounds(boundaries_feature)
                elif crop and task.crop is not None:
                    cutline, bounds = geom_transform_wkt_bbox(task.crop, src.dataset)
                else:
                    cutline = None
                    bounds = None
                
                if cutline is not None:
                    vrt_options = {'cutline': cutline}
                else:
                    vrt_options = None

                if tile_type in ['dsm', 'dtm']:
                    to_meter = get_rasterio_to_meters_factor(src.dataset)
                    
                    # WarpedVRT is really slow with compound CRSes
                    # so we override the CRS to the 2D version for speed
                    # in case there's one
                    if vrt_options is None:
                        vrt_options = {}

                    if task.epsg is not None:
                        vrt_options['src_crs'] = f"EPSG:{task.epsg}"

                if has_alpha_band(src.dataset):
                    band_count -= 1
                nodata = None
                # Workaround for https://github.com/WebODM/WebODM/issues/894
                if tile_type == 'orthophoto':
                    nodata = 0
                histogram_options = {"bins": 255, "range": hrange}
                if expr is not None:
                    data, mask = src.preview(expression=expr, vrt_options=vrt_options)
                    data = np.ma.array(data)
                    data.mask = mask == 0
                    stats = {
                        str(b + 1): raster_stats(data[b], percentiles=(pmin, pmax), bins=255, range=hrange)
                        for b in range(data.shape[0])
                    }
                    stats = {b: ImageStatistics(**s) for b, s in stats.items()}
                    metadata = RioMetadata(statistics=stats, **src.info().dict())
                else:
                    metadata = src.metadata(pmin=pmin, pmax=pmax, hist_options=histogram_options, nodata=nodata,
                                            bounds=bounds, vrt_options=vrt_options)
                info = json.loads(metadata.json())
        except IndexError as e:
            # Caught when trying to get an invalid raster metadata
            # or when the crop area is defined improperly. In order
            # to avoid locking the user out of the map, we remove cropping
            # if this ever happens.
            if task.crop is not None:
                task.crop = None
                task.save()
            
            raise exceptions.ValidationError("Cannot retrieve raster metadata: %s" % str(e))
        # Override min/max
        if hrange:
            for b in info['statistics']:
                info['statistics'][b]['min'] = hrange[0]
                info['statistics'][b]['max'] = hrange[1]
                info['statistics'][b]['percentiles'][0] = max(hrange[0], info['statistics'][b]['percentiles'][0])
                info['statistics'][b]['percentiles'][1] = min(hrange[1], info['statistics'][b]['percentiles'][1])

        cmap_labels = {
            "viridis": "Viridis",
            "jet": "Jet",
            "jet_r": "Jet (Reverse)",
            "terrain": "Terrain",
            "gist_earth": "Earth",
            "rdylgn": "RdYlGn",
            "rdylgn_r": "RdYlGn (Reverse)",
            "spectral": "Spectral",
            "spectral_r": "Spectral (Reverse)",
            "discrete_ndvi": "Contrast NDVI",
            "better_discrete_ndvi": "Custom NDVI Index",
            "rplumbo": "Rplumbo (Better NDVI)",
            "pastel1": "Pastel",
            "plasma": "Plasma",
            "inferno": "Inferno",
            "magma": "Magma",
            "cividis": "Cividis"
        }

        colormaps = []
        algorithms = []
        auto_bands = {'filter': '', 'match': None}

        if tile_type in ['dsm', 'dtm']:
            colormaps = ['viridis', 'jet', 'terrain', 'gist_earth', 'pastel1']
        elif formula and bands:
            colormaps = ['rdylgn', 'spectral', 'rdylgn_r', 'spectral_r', 'rplumbo', 'discrete_ndvi',
                         'better_discrete_ndvi',
                         'viridis', 'plasma', 'inferno', 'magma', 'cividis', 'jet', 'jet_r']
            algorithms = *get_algorithm_list(band_count),
            if is_auto_bands:
                auto_bands['filter'] = bands
                auto_bands['match'] = is_auto_bands_match

        info['color_maps'] = []
        info['algorithms'] = algorithms
        info['auto_bands'] = auto_bands

        if to_meter != 1.0:
            for b in info['statistics']:
                info['statistics'][b]['min'] *= to_meter
                info['statistics'][b]['max'] *= to_meter
                info['statistics'][b]['std'] *= to_meter
                info['statistics'][b]['percentiles'][0] *= to_meter
                info['statistics'][b]['percentiles'][1] *= to_meter
                info['statistics'][b]['histogram'][1] = [n * to_meter for n in info['statistics'][b]['histogram'][1]]
        
        if colormaps:
            for cmap in colormaps:
                try:
                    info['color_maps'].append({
                        'key': cmap,
                        'color_map': get_colormap_encoded_values(cmap),
                        'label': cmap_labels.get(cmap, cmap)
                    })
                except FileNotFoundError:
                    raise exceptions.ValidationError("Not a valid color_map value: %s" % cmap)

        info['name'] = task.name
        info['scheme'] = 'xyz'
        info['tiles'] = [get_tile_url(task, tile_type, self.request.query_params)]

        if info['maxzoom'] < info['minzoom']:
            info['maxzoom'] = info['minzoom']
        info['maxzoom'] += ZOOM_EXTRA_LEVELS
        info['minzoom'] -= ZOOM_EXTRA_LEVELS
        info['bounds'] = {'value': bounds if bounds is not None else src.bounds, 
                          'crs': f"EPSG:{task.epsg}" if task.epsg is not None else task.wkt}

        return Response(info)


class Tiles(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, tile_type="", z="", x="", y="", scale=1, ext=None):
        """
        Get a tile image
        """
        task = self.get_and_check_task(request, pk)
        
        z = int(z)
        x = int(x)
        y = int(y)

        scale = int(scale)

        indexes = None
        nodata = None
        rgb_tile = None

        formula = self.request.query_params.get('formula')
        bands = self.request.query_params.get('bands')
        rescale = self.request.query_params.get('rescale')
        color_map = self.request.query_params.get('color_map')
        hillshade = self.request.query_params.get('hillshade')
        tilesize = self.request.query_params.get('size')
        crop = self.request.query_params.get('crop') == '1'

        boundaries_feature = self.request.query_params.get('boundaries')
        if boundaries_feature == '':
            boundaries_feature = None
        if boundaries_feature is not None:
            try:
                boundaries_feature = json.loads(boundaries_feature)
            except json.JSONDecodeError:
                raise exceptions.ValidationError(_("Invalid boundaries parameter"))

        if formula == '': formula = None
        if bands == '': bands = None
        if rescale == '': rescale = None
        if color_map == '': color_map = None
        if hillshade == '' or hillshade == '0': hillshade = None
        if tilesize == '' or tilesize is None: tilesize = 256
        if bands == 'auto' and formula:
            bands, _discard_ = get_auto_bands(task.orthophoto_bands, formula)

        try:
            tilesize = int(tilesize)
            if tilesize != 256 and tilesize != 512:
                raise ValueError("Invalid size")

            if tilesize == 512:
                z -= 1
        except ValueError:
            raise exceptions.ValidationError(_("Invalid tile size parameter"))

        try:
            expr, _discard_ = lookup_formula(formula, bands)
        except ValueError as e:
            raise exceptions.ValidationError(str(e))

        if tile_type in ['dsm', 'dtm'] and rescale is None:
            rescale = "0,1000"
        if tile_type == 'orthophoto' and rescale is None:
            rescale = "0,255"

        if tile_type in ['dsm', 'dtm'] and color_map is None:
            color_map = "gray"

        if tile_type == 'orthophoto' and formula is not None:
            if color_map is None:
                color_map = "gray"
            if rescale is None:
                rescale = "-1,1"

        if nodata is not None:
            nodata = np.nan if nodata == "nan" else float(nodata)
        tilesize = scale * tilesize
        url = get_raster_path(task, tile_type)
        if not os.path.isfile(url):
            raise exceptions.NotFound()

        to_meter = 1.0
        with COGReader(url) as src:
            if not src.tile_exists(z, x, y):
                raise exceptions.NotFound(_("Outside of bounds"))

            minzoom, maxzoom = get_zoom_safe(src)
            has_alpha = has_alpha_band(src.dataset)
            if z < minzoom - ZOOM_EXTRA_LEVELS or z > maxzoom + ZOOM_EXTRA_LEVELS:
                raise exceptions.NotFound()

            if boundaries_feature is not None:
                try:
                    cutline = create_cutline(src.dataset, boundaries_feature, CRS.from_string('EPSG:4326'))
                except:
                    raise exceptions.ValidationError(_("Invalid boundaries"))
            elif crop and task.crop is not None:
                cutline, bounds = geom_transform_wkt_bbox(task.crop, src.dataset)
            else:
                cutline = None
            
            if cutline is not None:
                vrt_options = {'cutline': cutline}
            else:
                vrt_options = None

            if tile_type in ['dsm', 'dtm']:
                to_meter = get_rasterio_to_meters_factor(src.dataset)

            # Handle N-bands datasets for orthophotos (not plant health)
            if tile_type == 'orthophoto' and expr is None:
                ci = src.dataset.colorinterp
                # More than 4 bands?
                if len(ci) > 4:
                    # Try to find RGBA band order
                    if ColorInterp.red in ci and \
                            ColorInterp.green in ci and \
                            ColorInterp.blue in ci:
                        indexes = (ci.index(ColorInterp.red) + 1,
                                   ci.index(ColorInterp.green) + 1,
                                   ci.index(ColorInterp.blue) + 1,)
                    else:
                        # Fallback to first three
                        indexes = (1, 2, 3,)
                elif has_alpha:
                    indexes = non_alpha_indexes(src.dataset)

            # Workaround for https://github.com/WebODM/WebODM/issues/894
            if nodata is None and tile_type == 'orthophoto':
                nodata = 0

            resampling = "nearest"
            padding = 0
            tile_buffer = None

            if tile_type in ["dsm", "dtm"]:
                resampling = "bilinear"
                padding = 16

                # WarpedVRT is really slow with compound CRSes
                # so we override the CRS to the 2D version for speed
                # in case there's one
                if vrt_options is None:
                    vrt_options = {}

                if task.epsg is not None:
                    vrt_options['src_crs'] = f"EPSG:{task.epsg}"

            # Hillshading is not a local tile operation and
            # requires neighbor tiles to be rendered seamlessly
            if hillshade is not None:
                tile_buffer = 16

            try:
                if expr is not None:
                    tile = src.tile(x, y, z, expression=expr, tilesize=tilesize, nodata=nodata,
                                    padding=padding,
                                    tile_buffer=tile_buffer,
                                    resampling_method=resampling, vrt_options=vrt_options)
                else:
                    tile = src.tile(x, y, z, indexes=indexes, tilesize=tilesize, nodata=nodata,
                                    padding=padding,
                                    tile_buffer=tile_buffer,
                                    resampling_method=resampling, vrt_options=vrt_options)
            except TileOutsideBounds:
                raise exceptions.NotFound(_("Outside of bounds"))
            
            if color_map:
                try:
                    colormap.get(color_map)
                except InvalidColorMapName:
                    raise exceptions.ValidationError(_("Not a valid color_map value"))
            
            intensity = None
            try:
                rescale_arr = list(map(float, rescale.split(",")))
                if tile_type in ['dsm', 'dtm']:
                    rescale_arr = [v / to_meter for v in rescale_arr]
            except ValueError:
                raise exceptions.ValidationError(_("Invalid rescale value"))

            # Auto?
            if ext is None:
                # Check for transparency
                if np.equal(tile.mask, 255).all():
                    ext = "jpg"
                else:
                    if 'image/webp' in request.headers.get('Accept', ''):
                        ext = "webp"
                    else:
                        ext = "png"

            driver = "jpeg" if ext == "jpg" else ext

            options = img_profiles.get(driver, {})
            if hillshade is not None:
                try:
                    hillshade = float(hillshade)
                    if hillshade <= 0:
                        hillshade = 1.0
                except ValueError:
                    raise exceptions.ValidationError(_("Invalid hillshade value"))
                if tile.data.shape[0] != 1:
                    raise exceptions.ValidationError(
                        _("Cannot compute hillshade of non-elevation raster (multiple bands found)"))
                delta_scale = (maxzoom + ZOOM_EXTRA_LEVELS + 1 - z) ** 2
                dx = src.dataset.meta["transform"][0] * delta_scale
                dy = src.dataset.meta["transform"][4] * delta_scale
                ls = LightSource(azdeg=315, altdeg=45)
                
                # Remove elevation data from edge buffer tiles
                # (to keep intensity uniform across tiles)
                elevation = tile.data[0]
                elevation[0:tile_buffer, 0:tile_buffer] = nodata
                elevation[tile_buffer+tilesize:tile_buffer*2+tilesize, 0:tile_buffer] = nodata
                elevation[0:tile_buffer, tile_buffer+tilesize:tile_buffer*2+tilesize] = nodata
                elevation[tile_buffer+tilesize:tile_buffer*2+tilesize, tile_buffer+tilesize:tile_buffer*2+tilesize] = nodata

                intensity = ls.hillshade(elevation, dx=dx, dy=dy, vert_exag=hillshade)
                intensity = intensity[tile_buffer:tile_buffer+tilesize, tile_buffer:tile_buffer+tilesize]

            if intensity is not None:
                rgb = tile.post_process(in_range=(rescale_arr,))
                rgb_data = rgb.data[:,tile_buffer:tilesize+tile_buffer, tile_buffer:tilesize+tile_buffer]
                if colormap:
                    rgb, _discard_ = apply_cmap(rgb_data, colormap.get(color_map))
                if rgb.data.shape[0] != 3:
                    raise exceptions.ValidationError(
                        _("Cannot process tile: intensity image provided, but no RGB data was computed."))
                intensity = intensity * 255.0
                rgb = hsv_blend(rgb, intensity)
                if rgb is not None:
                    mask = tile.mask[tile_buffer:tilesize+tile_buffer, tile_buffer:tilesize+tile_buffer]
                    return HttpResponse(
                        render(rgb, mask, img_format=driver, **options),
                        content_type="image/{}".format(ext)
                    )

            if color_map is not None:
                return HttpResponse(
                    tile.post_process(in_range=(rescale_arr,)).render(img_format=driver, colormap=colormap.get(color_map),
                                                                    **options),
                    content_type="image/{}".format(ext)
                )

            return HttpResponse(
                tile.post_process(in_range=(rescale_arr,)).render(img_format=driver, **options),
                content_type="image/{}".format(ext)
            )


class Export(TaskNestedView):
    def post(self, request, pk=None, project_pk=None, asset_type=None):
        """
        Export assets (orthophoto, DEMs, etc.) after applying scaling
        formulas, shading, reprojections
        """
        task = self.get_and_check_task(request, pk)

        formula = request.data.get('formula')
        bands = request.data.get('bands')
        rescale = request.data.get('rescale')
        export_format = request.data.get('format', 'laz' if asset_type == 'georeferenced_model' else 'gtiff')
        epsg = request.data.get('epsg')
        proj = request.data.get('proj')
        color_map = request.data.get('color_map')
        hillshade = request.data.get('hillshade')
        resample = request.data.get('resample', 0)

        if formula == '': formula = None
        if bands == '': bands = None
        if rescale == '': rescale = None
        if epsg == '': epsg = None
        if proj == '': proj = None
        if color_map == '': color_map = None
        if hillshade == '': hillshade = None
        if resample == '': resample = 0

        if epsg is not None:
            proj = None

        expr = None

        if asset_type in ['orthophoto', 'dsm', 'dtm'] and not export_format in ['gtiff', 'gtiff-rgb', 'jpg', 'png', 'kmz']:
            raise exceptions.ValidationError(_("Unsupported format: %(value)s") % {'value': export_format})
        if asset_type == 'georeferenced_model' and not export_format in ['laz', 'las', 'ply', 'csv']:
            raise exceptions.ValidationError(_("Unsupported format: %(value)s") % {'value': export_format})
        
        # Default color map, hillshade
        if asset_type in ['dsm', 'dtm'] and export_format != 'gtiff':
            if color_map is None:
                color_map = 'viridis'
            if hillshade is None:
                hillshade = 6
        
        if color_map is not None:
            try:
                colormap.get(color_map)
            except InvalidColorMapName:
                raise exceptions.ValidationError(_("Not a valid color_map value"))

        if resample is not None:
            try:
                resample = float(resample)
            except ValueError:
                raise exceptions.ValidationError(_("Invalid resample value: %(value)s") % {'value': resample})

        if epsg is not None:
            try:
                epsg = int(epsg)
            except ValueError:
                raise exceptions.ValidationError(_("Invalid EPSG code: %(value)s") % {'value': epsg})
        
        if proj is not None:
            try:
                srs = osr.SpatialReference()
                if srs.ImportFromProj4(proj) != 0:
                    raise exceptions.ValidationError(_("Invalid PROJ string: %(value)s") % {'value': proj})
            except Exception as e:
                raise exceptions.ValidationError(_("Invalid PROJ string: %(value)s") % {'value': proj})

        if (formula and not bands) or (not formula and bands):
            raise exceptions.ValidationError(_("Both formula and bands parameters are required"))

        if formula and bands:
            if bands == 'auto':
                bands, _discard_ = get_auto_bands(task.orthophoto_bands, formula)

            try:
                expr, _discard_ = lookup_formula(formula, bands)
            except ValueError as e:
                raise exceptions.ValidationError(str(e))
        
        if export_format in ['gtiff-rgb', 'jpg', 'png']:
            if formula is not None and rescale is None:
                rescale = "-1,1"
        
        if export_format == 'gtiff':
            rescale = None
        
        if rescale is not None:
            rescale = rescale.replace("%2C", ",")
            try:
                rescale = list(map(float, rescale.split(",")))
            except ValueError:
                raise exceptions.ValidationError(_("Invalid rescale value: %(value)s") % {'value': rescale})
        
        if hillshade is not None:
            try:
                hillshade = float(hillshade)
                if hillshade < 0:
                    raise Exception("Hillshade must be > 0")
            except:
                raise exceptions.ValidationError(_("Invalid hillshade value: %(value)s") % {'value': hillshade})
        
        if asset_type == 'georeferenced_model':
            url = get_pointcloud_path(task)
        else:
            url = get_raster_path(task, asset_type)

        if not os.path.isfile(url):
            raise exceptions.NotFound()

        if epsg is not None and (task.epsg is None and task.wkt is None):
            raise exceptions.ValidationError(_("Cannot use epsg on non-georeferenced dataset"))
        
        # Strip unsafe chars, append suffix
        extension = extension_for_export_format(export_format)
        filename = "{}{}.{}".format(
                        get_asset_download_filename(task, asset_type),
                        "-{}".format(formula) if expr is not None else "",
                        extension
                    )

        if asset_type in ['orthophoto', 'dsm', 'dtm']:
            # Shortcut the process if no processing is required
            if export_format == 'gtiff' and ((task.epsg is not None and epsg == task.epsg) or epsg is None) and (proj is None) and expr is None and task.crop is None:
                return Response({'url': '/api/projects/{}/tasks/{}/download/{}.tif'.format(task.project.id, task.id, asset_type), 'filename': filename})
            else:
                celery_task_id = export_raster.delay(url, epsg=epsg,
                                                        proj=proj, 
                                                        expression=expr, 
                                                        format=export_format, 
                                                        rescale=rescale, 
                                                        color_map=color_map,
                                                        hillshade=hillshade,
                                                        asset_type=asset_type,
                                                        name=task.name,
                                                        crop=task.crop.wkt if task.crop is not None else None).task_id
                return Response({'celery_task_id': celery_task_id, 'filename': filename})
        elif asset_type == 'georeferenced_model':
            # Shortcut the process if no processing is required
            if export_format == 'laz' and ((task.epsg is not None and epsg == task.epsg) or epsg is None) and (proj is None) and (resample is None or resample == 0) and task.crop is None:
                return Response({'url': '/api/projects/{}/tasks/{}/download/{}.laz'.format(task.project.id, task.id, asset_type), 'filename': filename})
            else:
                celery_task_id = export_pointcloud.delay(url, epsg=epsg,
                                                            proj=proj, 
                                                            format=export_format,
                                                            resample=resample,
                                                            crop=task.crop.wkt if task.crop is not None else None,
                                                            crop_reference=task.get_reference_raster() if task.crop is not None else None).task_id
                return Response({'celery_task_id': celery_task_id, 'filename': filename})
