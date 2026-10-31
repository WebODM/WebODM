"""rio_tiler.utils: utility functions."""

import os
from io import BytesIO
from typing import Any, Dict, Optional, Tuple, Union

import numpy
from affine import Affine
from rasterio import windows
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, MaskFlags
from rasterio.features import is_valid_geom
from rasterio.io import DatasetReader, DatasetWriter, MemoryFile
from rasterio.rio.helpers import coords
from rasterio.transform import from_bounds, rowcol
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_geom

from .colormap import apply_cmap
from .constants import WEB_MERCATOR_CRS, BBox, NumType
from .errors import RioTilerError






def _stats(
    arr: numpy.ma.array, percentiles: Tuple[float, float] = (2, 98), **kwargs: Any
) -> Dict:
    """Calculate array statistics.

    Args:
        arr (numpy.ndarray): Input array data to get the stats from.
        percentiles (tuple, optional): Min/Max percentiles to compute. Defaults to `(2, 98)`.
        kwargs (optional): Options to forward to numpy.histogram function.

    Returns:
        dict: numpy array statistics (percentiles, min, max, stdev, histogram, valid_percent).

    Examples:
        >>> {
            'percentiles': [38, 147],
            'min': 20,
            'max': 180,
            'std': 28.123562304138662,
            'histogram': [
                [1625, 219241, 28344, 15808, 12325, 10687, 8535, 7348, 4656, 1208],
                [20.0, 36.0, 52.0, 68.0, 84.0, 100.0, 116.0, 132.0, 148.0, 164.0, 180.0]
            ],
            'valid_percent': 0.5
        }

    """
    sample, edges = numpy.histogram(arr[~arr.mask], **kwargs)
    return dict(
        percentiles=numpy.percentile(arr[~arr.mask], percentiles)
        .astype(arr.dtype)
        .tolist(),
        min=arr.min().item(),
        max=arr.max().item(),
        std=arr.std().item(),
        histogram=[sample.tolist(), edges.tolist()],
        valid_percent=((numpy.count_nonzero(~arr.mask)) / float(arr.data.size)) * 100,
    )


# https://github.com/OSGeo/gdal/blob/b1c9c12ad373e40b955162b45d704070d4ebf7b0/gdal/frmts/ingr/IngrTypes.cpp#L191




_DEFAULT_TRANSFORM_CACHE: Dict = {}


def default_transform(src_dst, dst_crs: CRS):
    key = None
    name = getattr(src_dst, "name", None)
    if name and isinstance(src_dst, DatasetReader):
        try:
            st = os.stat(name)
            key = (name, st.st_mtime_ns, st.st_size, src_dst.width, src_dst.height, dst_crs.to_string())
        except (OSError, TypeError):
            key = None
    if key is not None and key in _DEFAULT_TRANSFORM_CACHE:
        return _DEFAULT_TRANSFORM_CACHE[key]
    res = calculate_default_transform(
        src_dst.crs, dst_crs, src_dst.width, src_dst.height, *src_dst.bounds
    )
    if key is not None:
        if len(_DEFAULT_TRANSFORM_CACHE) >= 256:
            _DEFAULT_TRANSFORM_CACHE.clear()
        _DEFAULT_TRANSFORM_CACHE[key] = res
    return res


def get_vrt_transform(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    bounds: BBox,
    height: Optional[int] = None,
    width: Optional[int] = None,
    dst_crs: CRS = WEB_MERCATOR_CRS,
    window_precision: int = 6,
) -> Tuple[Affine, int, int]:
    """Calculate VRT transform.

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        bounds (tuple): Bounding box coordinates in target crs (**dst_crs**).
        height (int, optional): Desired output height of the array for the input bounds.
        width (int, optional): Desired output width of the array for the input bounds.
        dst_crs (rasterio.crs.CRS, optional): Target Coordinate Reference System. Defaults to `epsg:3857`.

    Returns:
        tuple: VRT transform (affine.Affine), width (int) and height (int)

    """
    dst_transform, _, _ = default_transform(src_dst, dst_crs)

    # If bounds window is aligned with the dataset internal tile we align the bounds with the pixels.
    # This is to limit the number of internal block fetched.
    if _requested_tile_aligned_with_internal_tile(
        src_dst, bounds, height, width, dst_crs
    ):
        col_off, row_off, w, h = windows.from_bounds(
            *bounds, transform=src_dst.transform, width=width, height=height,
        ).flatten()

        w = windows.Window(
            round(col_off, window_precision),
            round(row_off, window_precision),
            round(w, window_precision),
            round(h, window_precision),
        )
        bounds = src_dst.window_bounds(w)

    w, s, e, n = bounds

    # TODO: Explain
    if not height or not width:
        vrt_width = max(1, round((e - w) / dst_transform.a))
        vrt_height = max(1, round((s - n) / dst_transform.e))
        vrt_transform = from_bounds(w, s, e, n, vrt_width, vrt_height)
        return vrt_transform, vrt_width, vrt_height

    # TODO: Explain
    tile_transform = from_bounds(w, s, e, n, width, height)
    w_res = (
        tile_transform.a
        if abs(tile_transform.a) < abs(dst_transform.a)
        else dst_transform.a
    )
    h_res = (
        tile_transform.e
        if abs(tile_transform.e) < abs(dst_transform.e)
        else dst_transform.e
    )

    # TODO: Explain
    vrt_width = max(1, round((e - w) / w_res))
    vrt_height = max(1, round((s - n) / h_res))
    vrt_transform = from_bounds(w, s, e, n, vrt_width, vrt_height)

    return vrt_transform, vrt_width, vrt_height


def has_alpha_band(src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT]) -> bool:
    """Check for alpha band or mask in source."""
    if (
        any([MaskFlags.alpha in flags for flags in src_dst.mask_flag_enums])
        or ColorInterp.alpha in src_dst.colorinterp
    ):
        return True
    return False


def has_mask_band(src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT]) -> bool:
    """Check for mask band in source."""
    if any(
        [
            (MaskFlags.per_dataset in flags and MaskFlags.alpha not in flags)
            for flags in src_dst.mask_flag_enums
        ]
    ):
        return True
    return False


def non_alpha_indexes(src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT]) -> Tuple:
    """Return indexes of non-alpha bands."""
    return tuple(
        b
        for ix, b in enumerate(src_dst.indexes)
        if (
            src_dst.mask_flag_enums[ix] is not MaskFlags.alpha
            and src_dst.colorinterp[ix] is not ColorInterp.alpha
        )
    )


def linear_rescale(
    image: numpy.ndarray,
    in_range: Tuple[NumType, NumType],
    out_range: Tuple[NumType, NumType] = (0, 255),
) -> numpy.ndarray:
    """Apply linear rescaling to a numpy array.

    Args:
        image (numpy.ndarray): array to rescale.
        in_range (tuple): array min/max value to rescale from.
        out_range (tuple, optional): output min/max bounds to rescale to. Defaults to `(0, 255)`.

    Returns:
        numpy.ndarray: linear rescaled array.

    """
    imin, imax = in_range
    omin, omax = out_range
    image = numpy.clip(image, imin, imax) - imin
    image = image / numpy.float64(imax - imin)
    return image * (omax - omin) + omin


def _requested_tile_aligned_with_internal_tile(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    bounds: BBox,
    height: Optional[int] = None,
    width: Optional[int] = None,
    bounds_crs: CRS = WEB_MERCATOR_CRS,
) -> bool:
    """Check if tile is aligned with internal tiles."""
    if not src_dst.is_tiled:
        return False

    if src_dst.crs != bounds_crs:
        return False

    col_off, row_off, w, h = windows.from_bounds(
        *bounds, transform=src_dst.transform, height=height, width=width
    ).flatten()

    if round(w) % 64 and round(h) % 64:
        return False

    if (src_dst.width - round(col_off)) % 64:
        return False

    if (src_dst.height - round(row_off)) % 64:
        return False

    return True


def render(
    data: numpy.ndarray,
    mask: Optional[numpy.ndarray] = None,
    img_format: str = "PNG",
    colormap: Optional[Dict] = None,
    **creation_options: Any,
) -> bytes:
    """Translate numpy.ndarray to image bytes.

    Args:
        data (numpy.ndarray): Image array to encode.
        mask (numpy.ndarray, optional): Mask array.
        img_format (str, optional): Image format. See: for the list of supported format by GDAL: https://www.gdal.org/formats_list.html. Defaults to `PNG`.
        colormap (dict, optional): GDAL RGBA Color Table dictionary.
        creation_options (optional): Image driver creation options to forward to GDAL.

    Returns
        bytes: image body.

    Examples:
        >>> with COGReader("my_tif.tif") as cog:
            img = cog.preview()
            with open('test.jpg', 'wb') as f:
                f.write(render(img.data, img.mask, img_format="jpeg"))


    """
    img_format = img_format.upper()

    if len(data.shape) < 3:
        data = numpy.expand_dims(data, axis=0)

    if colormap:
        data, alpha = apply_cmap(data, colormap)
        if mask is not None:
            mask = (
                mask * alpha * 255
            )  # This is a special case when we want to mask some valid data

    # WEBP doesn't support 1band dataset so we must hack to create a RGB dataset
    if img_format == "WEBP" and data.shape[0] == 1:
        data = numpy.repeat(data, 3, axis=0)

    if img_format == "PNG" and data.dtype == "uint16" and mask is not None:
        mask = linear_rescale(mask, (0, 255), (0, 65535)).astype("uint16")

    elif img_format == "JPEG":
        mask = None

    elif img_format == "NPY":
        # If mask is not None we add it as the last band
        if mask is not None:
            mask = numpy.expand_dims(mask, axis=0)
            data = numpy.concatenate((data, mask))

        bio = BytesIO()
        numpy.save(bio, data)
        bio.seek(0)
        return bio.getvalue()

    elif img_format == "NPZ":
        bio = BytesIO()
        if mask is not None:
            numpy.savez_compressed(bio, data=data, mask=mask)
        else:
            numpy.savez_compressed(bio, data=data)
        bio.seek(0)
        return bio.getvalue()

    count, height, width = data.shape

    if (
        img_format in ("PNG", "JPEG", "WEBP")
        and data.dtype == numpy.uint8
        and data.shape[0] in (1, 3)
    ):
        return _render_pil(data, mask, img_format, creation_options)

    output_profile = dict(
        driver=img_format,
        dtype=data.dtype,
        count=count + 1 if mask is not None else count,
        height=height,
        width=width,
    )
    output_profile.update(creation_options)

    with MemoryFile() as memfile:
        with memfile.open(**output_profile) as dst:
            dst.write(data, indexes=list(range(1, count + 1)))
            # Use Mask as an alpha band
            if mask is not None:
                dst.write(mask.astype(data.dtype), indexes=count + 1)

        return memfile.read()






def _render_pil(
    data: numpy.ndarray,
    mask: Optional[numpy.ndarray],
    img_format: str,
    creation_options: Dict,
) -> bytes:
    from PIL import Image

    bands = [data[i] for i in range(data.shape[0])]
    if mask is not None:
        bands.append(mask.astype(numpy.uint8, copy=False))
    if len(bands) == 1:
        arr = numpy.ascontiguousarray(bands[0])
    else:
        arr = numpy.ascontiguousarray(numpy.dstack(bands))
    mode = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[len(bands)]
    img = Image.fromarray(arr, mode)
    bio = BytesIO()
    if img_format == "PNG":
        img.save(bio, "PNG", compress_level=int(creation_options.get("zlevel", 6)))
    elif img_format == "JPEG":
        img.save(bio, "JPEG", quality=int(creation_options.get("quality", 75)))
    else:
        img.save(
            bio,
            "WEBP",
            quality=int(creation_options.get("quality", 75)),
            lossless=bool(creation_options.get("lossless", False)),
        )
    return bio.getvalue()


def create_cutline(
    src_dst: Union[DatasetReader, DatasetWriter, WarpedVRT],
    geometry: Dict,
    geometry_crs: CRS = None,
) -> str:
    """
    Create WKT Polygon Cutline for GDALWarpOptions.

    Ref: https://gdal.org/api/gdalwarp_cpp.html?highlight=vrt#_CPPv415GDALWarpOptions

    Args:
        src_dst (rasterio.io.DatasetReader or rasterio.io.DatasetWriter or rasterio.vrt.WarpedVRT): Rasterio dataset.
        geometry (dict): GeoJSON feature or GeoJSON geometry. By default the cordinates are considered to be in the dataset CRS. Use `geometry_crs` to set a specific CRS.
        geometry_crs (rasterio.crs.CRS, optional): Input geometry Coordinate Reference System
    Returns:
        str: WKT geometry in form of `POLYGON ((x y, x y, ...)))

    """
    if "geometry" in geometry:
        geometry = geometry["geometry"]

    if not is_valid_geom(geometry):
        raise RioTilerError("Invalid geometry")

    geom_type = geometry["type"]
    if geom_type not in ["Polygon", "MultiPolygon"]:
        raise RioTilerError(
            "Invalid geometry type: {geom_type}. Should be Polygon or MultiPolygon"
        )

    if geometry_crs:
        geometry = transform_geom(geometry_crs, src_dst.crs, geometry)

    polys = []
    geom = (
        [geometry["coordinates"]] if geom_type == "Polygon" else geometry["coordinates"]
    )
    for p in geom:
        xs, ys = zip(*coords(p))
        src_y, src_x = rowcol(src_dst.transform, xs, ys)
        src_x = [max(0, min(src_dst.width, x)) for x in src_x]
        src_y = [max(0, min(src_dst.height, y)) for y in src_y]
        poly = ", ".join([f"{x} {y}" for x, y in list(zip(src_x, src_y))])
        polys.append(f"(({poly}))")

    str_poly = ",".join(polys)

    return (
        f"POLYGON {str_poly}"
        if geom_type == "Polygon"
        else f"MULTIPOLYGON ({str_poly})"
    )
