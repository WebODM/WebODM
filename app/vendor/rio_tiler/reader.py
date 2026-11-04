"""rio-tiler.reader: low level reader."""

import math
import warnings
from typing import Any, Callable, Dict, Optional, Tuple, Union

import numpy
import rasterio
from affine import Affine
from rasterio import windows
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.io import DatasetReader, DatasetWriter
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from .constants import WGS84_CRS, BBox, Indexes, NoData
from .errors import AlphaBandWarning, TileOutsideBounds
from .utils import _requested_tile_aligned_with_internal_tile as is_aligned
from .utils import _stats as raster_stats
from .utils import get_vrt_transform, has_alpha_band, has_mask_band, non_alpha_indexes


def read(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    height: Optional[int] = None,
    width: Optional[int] = None,
    indexes: Optional[Indexes] = None,
    window: Optional[windows.Window] = None,
    force_binary_mask: bool = True,
    nodata: Optional[NoData] = None,
    unscale: bool = False,
    resampling_method: Resampling = "nearest",
    vrt_options: Optional[Dict] = None,
    post_process: Optional[
        Callable[[numpy.ndarray, numpy.ndarray], Tuple[numpy.ndarray, numpy.ndarray]]
    ] = None,
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Low level read function.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        height (int, optional): Output height of the array.
        width (int, optional): Output width of the array.
        indexes (sequence of int or int, optional): Band indexes.
        window (rasterio.windows.Window, optional): Window to read.
        force_binary_mask (bool, optional): Cast returned mask to binary values (0 or 255). Defaults to `True`.
        nodata (int or float, optional): Overwrite dataset internal nodata value.
        unscale (bool, optional): Apply 'scales' and 'offsets' on output data value. Defaults to `False`.
        resampling_method (rasterio.enums.Resampling, optional): Rasterio's resampling algorithm. Defaults to `nearest`.
        vrt_options (dict, optional): Options to be passed to the rasterio.warp.WarpedVRT class.
        post_process (callable, optional): Function to apply on output data and mask values.

    Returns:
        tuple: Data (numpy.ndarray) and Mask (numpy.ndarray) values.

    """
    if isinstance(indexes, int):
        indexes = (indexes,)

    vrt_params = dict(add_alpha=True, resampling=Resampling[resampling_method])
    nodata = nodata if nodata is not None else src_dst.nodata
    if nodata is not None:
        vrt_params.update(dict(nodata=nodata, add_alpha=False, src_nodata=nodata))

    if has_alpha_band(src_dst):
        vrt_params.update(dict(add_alpha=False))

    if indexes is None:
        indexes = non_alpha_indexes(src_dst)
        if indexes != src_dst.indexes:
            warnings.warn(
                "Alpha band was removed from the output data array", AlphaBandWarning
            )

    out_shape = (len(indexes), height, width) if height and width else None
    mask_out_shape = (height, width) if height and width else None
    resampling = Resampling[resampling_method]

    if vrt_options:
        vrt_params.update(vrt_options)

    with WarpedVRT(src_dst, **vrt_params) as vrt:
        if ColorInterp.alpha in vrt.colorinterp:
            idx = vrt.colorinterp.index(ColorInterp.alpha) + 1
            indexes = tuple(indexes) + (idx,)
            if out_shape:
                out_shape = (len(indexes), height, width)

            data = vrt.read(
                indexes=indexes,
                window=window,
                out_shape=out_shape,
                resampling=resampling,
            )
            data, mask = data[0:-1], data[-1].astype("uint8")
        else:
            data = vrt.read(
                indexes=indexes,
                window=window,
                out_shape=out_shape,
                resampling=resampling,
            )
            if (
                nodata is not None
                and not has_mask_band(src_dst)
                and (len(indexes) == src_dst.count or src_dst.count == 1)
            ):
                if isinstance(nodata, float) and math.isnan(nodata):
                    valid = ~numpy.isnan(data)
                else:
                    valid = data != nodata
                mask = numpy.any(valid, axis=0).astype("uint8") * numpy.uint8(255)
            else:
                mask = vrt.dataset_mask(
                    window=window, out_shape=mask_out_shape, resampling=resampling,
                )

        if force_binary_mask:
            mask = numpy.where(mask != 0, numpy.uint8(255), numpy.uint8(0))

        if unscale:
            data = data.astype("float32", casting="unsafe")
            numpy.multiply(data, vrt.scales[0], out=data, casting="unsafe")
            numpy.add(data, vrt.offsets[0], out=data, casting="unsafe")

    if post_process:
        data, mask = post_process(data, mask)

    return data, mask


def part(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    bounds: BBox,
    height: Optional[int] = None,
    width: Optional[int] = None,
    padding: int = 0,
    dst_crs: Optional[CRS] = None,
    bounds_crs: Optional[CRS] = None,
    minimum_overlap: Optional[float] = None,
    vrt_options: Optional[Dict] = None,
    max_size: Optional[int] = None,
    **kwargs: Any,
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Read part of a dataset.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        bounds (tuple): Output bounds (left, bottom, right, top). By default the cordinates are considered to be in either the dataset CRS or in the `dst_crs` if set. Use `bounds_crs` to set a specific CRS.
        height (int, optional): Output height of the array.
        width (int, optional): Output width of the array.
        padding (int, optional): Padding to apply to each edge of the tile when retrieving data to assist in reducing resampling artefacts along edges. Defaults to `0`.
        dst_crs (rasterio.crs.CRS, optional): Target coordinate reference system.
        bounds_crs (rasterio.crs.CRS, optional): Overwrite bounds Coordinate Reference System.
        minimum_overlap (float, optional): Minimum % overlap for which to raise an error with dataset not covering enought of the tile.
        vrt_options (dict, optional): Options to be passed to the rasterio.warp.WarpedVRT class.
        max_size (int, optional): Limit output size array if not widht and height.
        kwargs (optional): Additional options to forward to `rio_tiler.reader.read`.

    Returns:
        tuple: Data (numpy.ndarray) and Mask (numpy.ndarray) values.

    """
    if not dst_crs:
        dst_crs = src_dst.crs

    if max_size and width and height:
        warnings.warn(
            "'max_size' will be ignored with with 'height' and 'width' set.",
            UserWarning,
        )

    if bounds_crs:
        bounds = transform_bounds(bounds_crs, dst_crs, *bounds, densify_pts=21)

    if minimum_overlap:
        src_bounds = transform_bounds(
            src_dst.crs, dst_crs, *src_dst.bounds, densify_pts=21
        )
        x_overlap = max(
            0, min(src_bounds[2], bounds[2]) - max(src_bounds[0], bounds[0])
        )
        y_overlap = max(
            0, min(src_bounds[3], bounds[3]) - max(src_bounds[1], bounds[1])
        )
        cover_ratio = (x_overlap * y_overlap) / (
            (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        )

        if cover_ratio < minimum_overlap:
            raise TileOutsideBounds(
                "Dataset covers less than {:.0f}% of tile".format(cover_ratio * 100)
            )

    vrt_transform, vrt_width, vrt_height = get_vrt_transform(
        src_dst, bounds, height, width, dst_crs=dst_crs
    )

    window = windows.Window(col_off=0, row_off=0, width=vrt_width, height=vrt_height)

    if max_size and not (width and height):
        if max(vrt_width, vrt_height) > max_size:
            ratio = vrt_height / vrt_width
            if ratio > 1:
                height = max_size
                width = math.ceil(height / ratio)
            else:
                width = max_size
                height = math.ceil(width * ratio)

    out_height = height or vrt_height
    out_width = width or vrt_width

    ovr_dst = None
    if (
        height
        and width
        and isinstance(src_dst, DatasetReader)
        and getattr(src_dst, "name", None)
        and not (vrt_options and "cutline" in vrt_options)
    ):
        scale = min(vrt_width / width, vrt_height / height)
        if scale >= 2:
            factor = 2 ** int(math.floor(math.log2(scale)))
            level = None
            for i, f in enumerate(src_dst.overviews(1)):
                if f <= factor:
                    level = i
            if level is not None:
                ovr_dst = rasterio.open(src_dst.name, overview_level=level)
                src_dst = ovr_dst
                vrt_transform, vrt_width, vrt_height = get_vrt_transform(
                    src_dst, bounds, height, width, dst_crs=dst_crs
                )
                window = windows.Window(
                    col_off=0, row_off=0, width=vrt_width, height=vrt_height
                )

    if padding > 0 and not is_aligned(src_dst, bounds, out_height, out_width, dst_crs):
        vrt_transform = vrt_transform * Affine.translation(-padding, -padding)
        orig_vrt_height = vrt_height
        orig_vrt_width = vrt_width
        vrt_height = vrt_height + 2 * padding
        vrt_width = vrt_width + 2 * padding
        window = windows.Window(
            col_off=padding,
            row_off=padding,
            width=orig_vrt_width,
            height=orig_vrt_height,
        )

    vrt_options = vrt_options or {}
    vrt_options.update(
        {
            "crs": dst_crs,
            "transform": vrt_transform,
            "width": vrt_width,
            "height": vrt_height,
        }
    )

    try:
        return read(
            src_dst,
            out_height,
            out_width,
            window=window,
            vrt_options=vrt_options,
            **kwargs,
        )
    finally:
        if ovr_dst is not None:
            ovr_dst.close()


def preview(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    max_size: int = 1024,
    height: int = None,
    width: int = None,
    **kwargs: Any,
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Read decimated version of a dataset.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        max_size (int, optional): Limit output size array if not widht and height. Defaults to `1024`.
        height (int, optional): Output height of the array.
        width (int, optional): Output width of the array.
        kwargs (optional): Additional options to forward to `rio_tiler.reader.read`.

    Returns:
        tuple: Data (numpy.ndarray) and Mask (numpy.ndarray) values.

    """
    if not height and not width:
        if max(src_dst.height, src_dst.width) < max_size:
            height, width = src_dst.height, src_dst.width
        else:
            ratio = src_dst.height / src_dst.width
            if ratio > 1:
                height = max_size
                width = math.ceil(height / ratio)
            else:
                width = max_size
                height = math.ceil(width * ratio)

    return read(src_dst, height, width, **kwargs)




def stats(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    bounds: Optional[BBox] = None,
    indexes: Optional[Indexes] = None,
    max_size: int = 1024,
    bounds_crs: CRS = WGS84_CRS,
    percentiles: Tuple[float, float] = (2.0, 98.0),
    hist_options: Optional[Dict] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Retrieve statistics from a dataset.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        bounds (tuple, optional): Bounding box coordinates from which to calculate image statistics.
        indexes (sequence of int or int, optional): Band indexes.
        max_size (int, optional): Limit the size of the longest dimension of the dataset read, respecting bounds X/Y aspect ratio. Defaults to `1024`.
        bounds_crs (rasterio.crs.CRS, optional): Input bounds Coordinate Reference System. Defaults to `epsg:4326`.
        percentiles (tuple, optional): Min/Max percentiles to compute. Defaults to `(2, 98)`.
        hist_options (dict, optional): Options to forward to numpy.histogram function.
        kwargs (optional): Additional options to forward to `rio_tiler.reader.part` or `rio_tiler.reader.preview`.

    Returns:
        dict: Dataset statistics.

    """
    if isinstance(indexes, int):
        indexes = (indexes,)

    if indexes is None:
        indexes = non_alpha_indexes(src_dst)
        if indexes != src_dst.indexes:
            warnings.warn(
                "Alpha band was removed from the output data array", AlphaBandWarning
            )

    if bounds:
        data, mask = part(
            src_dst,
            bounds,
            max_size=max_size,
            indexes=indexes,
            bounds_crs=bounds_crs,
            **kwargs,
        )
    else:
        data, mask = preview(src_dst, max_size=max_size, indexes=indexes, **kwargs)

    data = numpy.ma.array(data)
    data.mask = mask == 0

    hist_options = hist_options or {}
    return {
        f"{indexes[b]}": raster_stats(data[b], percentiles=percentiles, **hist_options)
        for b in range(data.shape[0])
    }


def metadata(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    bounds: Optional[BBox] = None,
    indexes: Optional[Indexes] = None,
    max_size: int = 1024,
    bounds_crs: CRS = WGS84_CRS,
    percentiles: Tuple[float, float] = (2.0, 98.0),
    hist_options: Optional[Dict] = None,
    **kwargs: Any,
) -> Dict:
    """Retrieve metadata and statistics from a dataset.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        bounds (tuple, optional): Bounding box coordinates from which to calculate image statistics.
        indexes (sequence of int or int, optional): Band indexes.
        max_size (int, optional): Limit the size of the longest dimension of the dataset read, respecting bounds X/Y aspect ratio. Defaults to `1024`.
        bounds_crs (rasterio.crs.CRS, optional): Input bounds Coordinate Reference System. Defaults to `epsg:4326`.
        percentiles (tuple, optional): Min/Max percentiles to compute. Defaults to `(2, 98)`.
        hist_options (dict, optional): Options to forward to numpy.histogram function.
        kwargs (optional): Additional options to forward to `rio_tiler.reader.part` or `rio_tiler.reader.preview`.

    Returns:
        dict: Dataset metadata and statistics.

    """
    if isinstance(indexes, int):
        indexes = (indexes,)

    if indexes is None:
        indexes = non_alpha_indexes(src_dst)
        if indexes != src_dst.indexes:
            warnings.warn(
                "Alpha band was removed from the output data array", AlphaBandWarning
            )

    if bounds:
        data, mask = part(
            src_dst,
            bounds,
            max_size=max_size,
            indexes=indexes,
            bounds_crs=bounds_crs,
            **kwargs,
        )
        bounds = transform_bounds(bounds_crs, WGS84_CRS, *bounds, densify_pts=21)

    else:
        data, mask = preview(src_dst, max_size=max_size, indexes=indexes, **kwargs)
        bounds = transform_bounds(
            src_dst.crs, WGS84_CRS, *src_dst.bounds, densify_pts=21
        )

    data = numpy.ma.array(data)
    data.mask = mask == 0

    hist_options = hist_options or {}
    statistics = {
        f"{indexes[b]}": raster_stats(data[b], percentiles=percentiles, **hist_options)
        for b in range(data.shape[0])
    }

    def _get_descr(ix):
        """Return band description."""
        return src_dst.descriptions[ix - 1] or ""

    band_descriptions = [(f"{ix}", _get_descr(ix)) for ix in indexes]
    tags = [(f"{ix}", src_dst.tags(ix)) for ix in indexes]

    other_meta = dict()
    if src_dst.scales[0] and src_dst.offsets[0]:
        other_meta.update(dict(scale=src_dst.scales[0]))
        other_meta.update(dict(offset=src_dst.offsets[0]))

    if has_alpha_band(src_dst):
        nodata_type = "Alpha"
    elif has_mask_band(src_dst):
        nodata_type = "Mask"
    elif src_dst.nodata is not None:
        nodata_type = "Nodata"
    else:
        nodata_type = "None"

    try:
        cmap = src_dst.colormap(1)
        other_meta.update(dict(colormap=cmap))
    except ValueError:
        pass

    return dict(
        bounds=bounds,
        statistics=statistics,
        band_metadata=tags,
        band_descriptions=band_descriptions,
        dtype=src_dst.meta["dtype"],
        colorinterp=[src_dst.colorinterp[ix - 1].name for ix in indexes],
        nodata_type=nodata_type,
        **other_meta,
    )
