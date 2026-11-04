"""rio-tiler.expression: Parse and Apply expression."""

import re
from typing import Sequence, Tuple, Union

import numexpr
import numpy


def parse_expression(expression: str, cast: bool = True) -> Tuple:
    """Parse rio-tiler band math expression.

    Args:
        expression (str): band math/combination expression.
        cast (bool): cast band names to integers (convert to index values).

    Returns:
        tuple: band names/indexes.

    Examples:
        >>> parse_expression("b1,b2")
            (2, 1)

        >>> parse_expression("B1/B2", cast=False)
            ("2", "1")

    """
    bands = set(re.findall(r"\bb(?P<bands>[0-9A-Z]+)\b", expression, re.IGNORECASE))
    return tuple(map(int, bands)) if cast else tuple(bands)


def apply_expression(
    blocks: Sequence[str], bands: Sequence[Union[str, int]], data: numpy.ndarray,
) -> numpy.ndarray:
    """Apply rio-tiler expression.

    Args:

        blocks (sequence): expression for a specific layer.
        bands (sequence): bands names.
        data (numpy.array):  array of bands.

    Returns:
        numpy.array: output data.

    """
    return numpy.array(
        [
            numpy.nan_to_num(
                numexpr.evaluate(bloc.strip(), local_dict=dict(zip(bands, data)))
            )
            for bloc in blocks
        ]
    )
