"""rio-tiler colormap functions and classes."""

import os
import pathlib
from typing import Dict, Tuple, Union

import attr
import numpy

from .errors import ColorMapAlreadyRegistered, InvalidColorMapName, InvalidFormat

try:
    from importlib.resources import files as resources_files  # type: ignore
except ImportError:
    # Try backported to PY<39 `importlib_resources`.
    from importlib_resources import files as resources_files  # type: ignore


EMPTY_COLORMAP: Dict = {i: [0, 0, 0, 0] for i in range(256)}

DEFAULT_CMAPS_FILES = {
    f.stem: str(f) for f in (resources_files(__package__) / "cmap_data").glob("*.npy")
}

USER_CMAPS_DIR = os.environ.get("COLORMAP_DIRECTORY", None)
if USER_CMAPS_DIR:
    DEFAULT_CMAPS_FILES.update(
        {f.stem: str(f) for f in pathlib.Path(USER_CMAPS_DIR).glob("*.npy")}
    )








# From https://github.com/mojodna/marblecutter/blob/5b9040ba6c83562a465eabdbb6e8959e6a8bf041/marblecutter/utils.py#L35
_LUT_CACHE: Dict = {}


def make_lut(colormap: Dict) -> numpy.ndarray:
    """Create a lookup table numpy.ndarray from a GDAL RGBA Color Table dictionary.

    Args:
        colormap (dict): GDAL RGBA Color Table dictionary.

    Returns:
        numpy.ndarray: colormap lookup table.

    """
    lut = numpy.zeros(shape=(256, 4), dtype=numpy.uint8)
    for i, color in colormap.items():
        lut[int(i)] = color

    return lut


def apply_cmap(
    data: numpy.ndarray, colormap: Dict
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Apply colormap on data.

    Args:
        data (numpy ndarray): 1D image array to translate to RGB.
        colormap (dict): GDAL RGBA Color Table dictionary.

    Returns:
        tuple: Data (numpy.ndarray) and Mask (numpy.ndarray) values.

    Raises:
        InvalidFormat: If data is not a 1 band dataset (1, col, row).

    """
    if data.shape[0] > 1:
        raise InvalidFormat("Source data must be 1 band")

    # if colormap has more than 256 values OR its `max` key >= 256 we can't use
    # rio_tiler.colormap.make_lut, because we don't want to create a `lookup table`
    # with more than 256 entries (256 x 4) array. In this case we use `apply_discrete_cmap`
    # which can work with arbitrary colormap dict.
    if len(colormap) > 256 or max(colormap) >= 256:
        return apply_discrete_cmap(data, colormap)

    cached = _LUT_CACHE.get(id(colormap))
    if cached is not None and cached[0] is colormap:
        lookup_table = cached[1]
    else:
        lookup_table = make_lut(colormap)
        if len(_LUT_CACHE) >= 64:
            _LUT_CACHE.clear()
        _LUT_CACHE[id(colormap)] = (colormap, lookup_table)
    data = lookup_table[data[0], :]

    data = numpy.transpose(data, [2, 0, 1])

    return data[:-1], data[-1]


def apply_discrete_cmap(
    data: numpy.ndarray, colormap: Dict
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Apply discrete colormap.

    Args:
        data (numpy ndarray): 1D image array to translate to RGB.
        color_map (dict): Discrete ColorMap dictionary.

    Returns:
        tuple: Data (numpy.ndarray) and Alpha band (numpy.ndarray).

    Examples:
        >>> data = numpy.random.randint(0, 3, size=(1, 256, 256))
            cmap = {
                0, [0, 0, 0, 0],
                1: [255, 255, 255, 255],
                2: [255, 0, 0, 255],
                3: [255, 255, 0, 255],
            }
            data, mask = apply_discrete_cmap(data, cmap)
            assert data.shape == (3, 256, 256)

    """
    res = numpy.zeros((data.shape[1], data.shape[2], 4), dtype=numpy.uint8)

    for k, v in colormap.items():
        res[data[0] == k] = v

    data = numpy.transpose(res, [2, 0, 1])

    return data[:-1], data[-1]




@attr.s(frozen=True)
class ColorMaps:
    """Default Colormaps holder.

    Attributes:
        data (dict): colormaps. Defaults to `rio_tiler.colormap.DEFAULTS_CMAPS`.

    """

    data: Dict[str, Union[str, Dict]] = attr.ib(
        default=attr.Factory(lambda: DEFAULT_CMAPS_FILES)
    )

    def get(self, name: str) -> Dict:
        """Fetch a colormap.

        Args:
            name (dict): colormap name.

        Returns
            dict: colormap dictionary.

        """
        cmap = self.data.get(name, None)
        if cmap is None:
            raise InvalidColorMapName(f"Invalid colormap name: {name}")

        if isinstance(cmap, str):
            colormap = numpy.load(cmap)
            assert colormap.shape == (256, 4)
            assert colormap.dtype == numpy.uint8
            cmap = {idx: value.tolist() for idx, value in enumerate(colormap)}
            self.data[name] = cmap
        return cmap


    def register(
        self, custom_cmap: Dict[str, Union[str, Dict]], overwrite: bool = False,
    ) -> "ColorMaps":
        """Register a custom colormap.

        Args:
            custom_cmap (dict): custom colormap(s) to register.
            overwrite (bool): Overwrite existing colormap with same key (default: False)

        Examples:
            >>> cmap = cmap.register({"acmap": {0: [0, 0, 0, 0]}})

            >>> cmap = cmap.register({"acmap": "acmap.npy"})

        """
        for name, cmap in custom_cmap.items():
            if not overwrite and name in self.data:
                raise ColorMapAlreadyRegistered(
                    f"{name} is already registered. Use force=True to overwrite."
                )

        return ColorMaps({**self.data, **custom_cmap})


cmap = ColorMaps()  # noqa
