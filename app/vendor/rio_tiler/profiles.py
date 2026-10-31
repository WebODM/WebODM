"""Image file profiles."""

from collections import UserDict

from rasterio.profiles import Profile  # type: ignore


class JPEGProfile(Profile):
    """JPEG creation options ref: https://www.gdal.org/frmt_jpeg.html."""

    defaults = {"quality": 85}


class PNGProfile(Profile):
    """PNG creation options ref: https://www.gdal.org/frmt_png.html."""

    defaults = {"zlevel": 3}


class WEBPProfile(Profile):
    """WEBP creation options ref: https://www.gdal.org/frmt_webp.html."""

    defaults = {"quality": 75, "lossless": False}


class ImagesProfiles(UserDict):
    """GDAL Image creation options.

    ref: https://github.com/mapnik/mapnik/wiki/Image-IO#default-output-details.

    """

    def __init__(self):
        """Initialize COGProfiles dict."""
        self.data = {}
        self.data.update(
            {
                "jpeg": JPEGProfile(),
                "png": PNGProfile(),
                "webp": WEBPProfile(),
            }
        )

    def get(self, key, default=None):
        """Like normal item access but return a copy of the key."""
        if key in (self.keys()):
            return self.data[key].copy()
        return default

    def __getitem__(self, key):
        """Like normal item access but return a copy of the key."""
        return self.data[key].copy()


img_profiles = ImagesProfiles()
