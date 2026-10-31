"""rio_tiler.io.base: ABC class for rio-tiler readers."""

import abc
from typing import Any, Dict, Tuple

import attr
from ..tms import Tile, WebMercatorQuad

from ..constants import WEB_MERCATOR_TMS, BBox
from ..models import ImageData


@attr.s
class SpatialMixin:
    """Spatial Info Mixin.

    Attributes:
        tms (WebMercatorQuad, optional): tile grid definition.
        bbox (tuple): Dataset bounds (left, bottom, right, top). **READ ONLY attribute**.
        minzoom (int): Overwrite Min Zoom level. **READ ONLY attribute**.
        maxzoom (int): Overwrite Max Zoom level. **READ ONLY attribute**.

    """

    tms: WebMercatorQuad = attr.ib(default=WEB_MERCATOR_TMS)
    bounds: BBox = attr.ib(init=False)
    minzoom: int = attr.ib(init=False)
    maxzoom: int = attr.ib(init=False)

    @property
    def center(self) -> Tuple[float, float, int]:
        """Dataset center + minzoom."""
        return (
            (self.bounds[0] + self.bounds[2]) / 2,
            (self.bounds[1] + self.bounds[3]) / 2,
            self.minzoom,
        )

    @property
    def spatial_info(self) -> Dict:
        """Return Dataset's spatial info."""
        return {
            'bounds': self.bounds,
            'center': self.center,
            'minzoom': self.minzoom,
            'maxzoom': self.maxzoom,
        }

    def tile_exists(self, tile_z: int, tile_x: int, tile_y: int) -> bool:
        """Check if a tile is intersets the dataset bounds.

        Args:
            tile_x (int): Tile's horizontal index.
            tile_y (int): Tile's vertical index.
            tile_z (int): Tile's zoom level index.

        Returns:
            bool: True if the tile is intersets the dataset bounds.

        """
        tile = Tile(x=tile_x, y=tile_y, z=tile_z)
        tile_bounds = self.tms.bounds(*tile)
        return (
            (tile_bounds[0] < self.bounds[2])
            and (tile_bounds[2] > self.bounds[0])
            and (tile_bounds[3] > self.bounds[1])
            and (tile_bounds[1] < self.bounds[3])
        )


@attr.s
class BaseReader(SpatialMixin, metaclass=abc.ABCMeta):
    """Rio-tiler.io BaseReader."""

    def __enter__(self):
        """Support using with Context Managers."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Support using with Context Managers."""
        pass

    @abc.abstractmethod
    def info(self) -> Dict:
        """Return Dataset's info.

        Returns:
            rio_tile.models.Info: Dataset info.

        """
        ...

    @abc.abstractmethod
    def stats(
        self, pmin: float = 2.0, pmax: float = 98.0, **kwargs: Any,
    ) -> Dict[str, Dict]:
        """Return Dataset's statistics.

        Args:
            pmin (float, optional): Histogram minimum cut. Defaults to `2.0`.
            pmax (float, optional): Histogram maximum cut. Defaults to `98.0`.

        Returns:
            rio_tile.models.ImageStatistics: Dataset statistics.

        """
        ...

    def metadata(
        self, pmin: float = 2.0, pmax: float = 98.0, **kwargs: Any,
    ) -> Dict:
        """Return Dataset's statistics and info.

        Args:
            pmin (float, optional): Histogram minimum cut. Defaults to `2.0`.
            pmax (float, optional): Histogram maximum cut. Defaults to `98.0`.

        Returns:
            rio_tile.models.Metadata: Dataset statistics and metadata.

        """
        info = self.info()
        stats = self.stats(pmin, pmax, **kwargs)
        return {**info, 'statistics': stats}

    @abc.abstractmethod
    def tile(self, tile_x: int, tile_y: int, tile_z: int, **kwargs: Any) -> ImageData:
        """Read a Map tile from the Dataset.

        Args:
            tile_x (int): Tile's horizontal index.
            tile_y (int): Tile's vertical index.
            tile_z (int): Tile's zoom level index.

        Returns:
            rio_tiler.models.ImageData: ImageData instance with data, mask and tile spatial info.

        """
        ...


    @abc.abstractmethod
    def preview(self, **kwargs: Any) -> ImageData:
        """Read a preview of a Dataset.

        Returns:
            rio_tiler.models.ImageData: ImageData instance with data, mask and input spatial info.

        """
        ...








