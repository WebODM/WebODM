import rasterio

from .classes import BootTestCase
import os

class TestApi(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_rasterio_functions(self):
        with rasterio.open(os.path.join("app", "fixtures", "orthophoto.tif")) as raster:
            self.assertTrue(raster.crs.to_epsg() == 32615)
            self.assertTrue(raster.width == 212)
