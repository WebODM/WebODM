"""Errors and warnings."""


class RioTilerError(Exception):
    """Base exception class."""


class InvalidFormat(RioTilerError):
    """Invalid image format."""


class TileOutsideBounds(RioTilerError):
    """Z-X-Y Tile is outside image bounds."""


class PointOutsideBounds(RioTilerError):
    """Point is outside image bounds."""




class InvalidColorMapName(RioTilerError):
    """Invalid colormap name."""


class AlphaBandWarning(UserWarning):
    """Automaticaly removed Alpha band from output array."""


class NoOverviewWarning(UserWarning):
    """Dataset has no overviews."""




class MissingAssets(RioTilerError):
    """Missing Assets."""


class MissingBands(RioTilerError):
    """Missing bands."""


class ExpressionMixingWarning(UserWarning):
    """Expression and assets/indexes mixing."""




class ColorMapAlreadyRegistered(RioTilerError):
    """ColorMap is already registered."""




class InvalidColorFormat(RioTilerError):
    """Invalid color format."""


class InvalidDatatypeWarning(UserWarning):
    """Invalid Output Datatype."""
