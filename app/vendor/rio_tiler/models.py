"""rio-tiler models."""

import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import attr
import numpy
from affine import Affine
from rasterio.coords import BoundingBox
from rasterio.crs import CRS
from rasterio.dtypes import dtype_ranges
from rasterio.transform import from_bounds

from .constants import ColorTuple, NumType
from .errors import InvalidDatatypeWarning
from .utils import linear_rescale, render


def to_coordsbbox(bbox) -> Optional[BoundingBox]:
    """Convert bbox to CoordsBbox nameTuple."""
    return BoundingBox(*bbox) if bbox else None


@attr.s
class ImageData:
    """Image Data class.

    Attributes:
        data (numpy.ndarray): pixel values.
        mask (numpy.ndarray): rasterio mask values.
        assets (list, optional): list of assets used to construct the data values.
        bounds (BoundingBox, optional): bounding box of the data.
        crs (rasterio.crs.CRS, optional): Coordinates Reference System of the bounds.
        metadata (dict, optional): Additional metadata. Defaults to `{}`.

    """

    data: numpy.ndarray = attr.ib()
    mask: numpy.ndarray = attr.ib()
    assets: Optional[List] = attr.ib(default=None)
    bounds: Optional[BoundingBox] = attr.ib(default=None, converter=to_coordsbbox)
    crs: Optional[CRS] = attr.ib(default=None)
    metadata: Optional[Dict] = attr.ib(factory=dict)

    @data.validator
    def _validate_data(self, attribute, value):
        """ImageData data has to be a 3d array in form of (count, height, width)"""
        if not len(value.shape) == 3:
            raise ValueError(
                "ImageData data has to be an array in form of (count, height, width)"
            )

    @mask.default
    def _default_mask(self):
        return numpy.zeros((self.height, self.width), dtype="uint8") + 255

    def __iter__(self):
        """Allow for variable expansion (``arr, mask = ImageData``)"""
        for i in (self.data, self.mask):
            yield i




    @property
    def width(self) -> int:
        """Width of the data array."""
        return self.data.shape[2]

    @property
    def height(self) -> int:
        """Height of the data array."""
        return self.data.shape[1]

    @property
    def count(self) -> int:
        """Number of band."""
        return self.data.shape[0]

    @property
    def transform(self):
        """Returns the affine transform."""
        return (
            from_bounds(*self.bounds, self.width, self.height)
            if self.bounds
            else Affine.scale(self.width, -self.height)
        )

    def _rescale(
        self,
        data: numpy.ndarray,
        mask: numpy.ndarray,
        in_range: Sequence[Tuple[NumType, NumType]],
        out_range: Sequence[Tuple[NumType, NumType]] = ((0, 255),),
        out_dtype: Union[str, numpy.number] = "uint8",
    ):
        """Rescale data."""
        nbands = data.shape[0]

        if len(in_range) != nbands:
            in_range = ((in_range[0]),) * nbands

        if len(out_range) != nbands:
            out_range = ((out_range[0]),) * nbands

        for bdx in range(nbands):
            if (
                data.dtype == numpy.uint8
                and tuple(in_range[bdx]) == (0, 255)
                and tuple(out_range[bdx]) == (0, 255)
            ):
                data[bdx] = numpy.where(mask, data[bdx], 0)
            else:
                data[bdx] = numpy.where(
                    mask,
                    linear_rescale(
                        data[bdx], in_range=in_range[bdx], out_range=out_range[bdx]
                    ),
                    0,
                )

        return data.astype(out_dtype, copy=False)

    def post_process(
        self,
        in_range: Optional[Sequence[Tuple[NumType, NumType]]] = None,
        out_dtype: Union[str, numpy.number] = "uint8",
        **kwargs: Any,
    ) -> "ImageData":
        """Post-process image data.

        Args:
            in_range (tuple): input min/max bounds value to rescale from.
            out_dtype (str, optional): output datatype after rescaling. Defaults to `uint8`.
            kwargs (optional): keyword arguments to forward to `rio_tiler.utils.linear_rescale`.

        Returns:
            ImageData: new ImageData object with the updated data.

        Examples:
            >>> img.post_process(in_range=((0, 16000), ))

        """
        data = self.data.copy()
        mask = self.mask.copy()

        if in_range:
            data = self._rescale(data, mask, in_range, out_dtype=out_dtype, **kwargs)

        return ImageData(
            data,
            mask,
            crs=self.crs,
            bounds=self.bounds,
            assets=self.assets,
            metadata=self.metadata,
        )

    def render(self, add_mask: bool = True, img_format: str = "PNG", **kwargs) -> bytes:
        """Render data to image blob.

        Args:
            add_mask (bool, optional): add mask to output image. Defaults to `True`.
            img_format (str, optional): output image format. Defaults to `PNG`.
            kwargs (optional): keyword arguments to forward to `rio_tiler.utils.render`.

        Returns:
            bytes: image.

        """
        img_format = img_format.upper()

        if img_format == "GTIFF":
            if "transform" not in kwargs:
                kwargs.update({"transform": self.transform})
            if "crs" not in kwargs and self.crs:
                kwargs.update({"crs": self.crs})

        data = self.data
        datatype_range = (dtype_ranges[str(data.dtype)],)

        if img_format in ["PNG"] and data.dtype not in ["uint8", "uint16"]:
            warnings.warn(
                f"Invalid type: `{data.dtype}` for the `{img_format}` driver. Data will be rescaled using min/max type bounds.",
                InvalidDatatypeWarning,
            )
            data = self._rescale(data.copy(), self.mask, in_range=datatype_range)

        elif img_format in ["JPEG", "WEBP"] and data.dtype not in ["uint8"]:
            warnings.warn(
                f"Invalid type: `{data.dtype}` for the `{img_format}` driver. Data will be rescaled using min/max type bounds.",
                InvalidDatatypeWarning,
            )
            data = self._rescale(data.copy(), self.mask, in_range=datatype_range)

        elif img_format in ["JP2OPENJPEG"] and data.dtype not in [
            "uint8",
            "int16",
            "uint16",
        ]:
            warnings.warn(
                f"Invalid type: `{data.dtype}` for the `{img_format}` driver. Data will be rescaled using min/max type bounds.",
                InvalidDatatypeWarning,
            )
            data = self._rescale(data.copy(), self.mask, in_range=datatype_range)

        if add_mask:
            return render(data, self.mask, img_format=img_format, **kwargs)

        return render(data, img_format=img_format, **kwargs)
