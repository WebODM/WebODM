from typing import NamedTuple
from pyproj import CRS, Transformer


class Tile(NamedTuple):
    x: int
    y: int
    z: int


class WebMercatorQuad:
    crs = CRS.from_epsg(3857)
    minzoom = 0
    maxzoom = 24
    origin = 20037508.342789244
    scale_denominator_0 = 559082264.0287178
    tile_size = 256

    def __init__(self):
        self.to_geographic = Transformer.from_crs(self.crs, CRS.from_epsg(4326), always_xy=True)

    def resolution(self, zoom):
        return self.scale_denominator_0 / 2 ** zoom * 0.28e-3

    def zoom_for_res(self, res):
        for zoom in range(self.minzoom, self.maxzoom + 1):
            matrix_res = self.resolution(zoom)
            if res > matrix_res or abs(res - matrix_res) / matrix_res <= 1e-8:
                break
        if zoom > 0 and abs(res - matrix_res) / matrix_res > 1e-8:
            if self.resolution(max(zoom - 1, self.minzoom)) / res < res / matrix_res:
                zoom = max(zoom - 1, self.minzoom)
        return zoom

    def ul(self, x, y, z):
        res = self.resolution(z)
        return -self.origin + x * res * self.tile_size, self.origin - y * res * self.tile_size

    def xy_bounds(self, x, y, z):
        left, top = self.ul(x, y, z)
        right, bottom = self.ul(x + 1, y + 1, z)
        return (left, bottom, right, top)

    def bounds(self, x, y, z):
        left, top = self.to_geographic.transform(*self.ul(x, y, z))
        right, bottom = self.to_geographic.transform(*self.ul(x + 1, y + 1, z))
        return (left, bottom, right, top)
