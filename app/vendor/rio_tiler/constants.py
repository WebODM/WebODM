"""rio-tiler constant values."""

from typing import Sequence, Tuple, Union

from .tms import WebMercatorQuad
from rasterio.crs import CRS

NumType = Union[float, int]
BBox = Tuple[float, float, float, float]
ColorTuple = Tuple[int, int, int, int]
NoData = Union[float, int, str]
Indexes = Union[Sequence[int], int]


WEB_MERCATOR_CRS = CRS.from_epsg(3857)
WGS84_CRS = CRS.from_epsg(4326)

WEB_MERCATOR_TMS = WebMercatorQuad()
