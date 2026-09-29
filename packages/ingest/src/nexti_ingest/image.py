"""Screenshots: the header must match the type and stay within the pixel limits. Only the header is read; the
image is never decoded here (decompression bombs, parser bugs)."""

import warnings
from dataclasses import dataclass
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from nexti_ingest.errors import Rejection
from nexti_ingest.limits import Limits

FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


@dataclass(frozen=True)
class ImageReport:
    width: int
    height: int


def inspect_image(stream: BinaryIO, content_type: str, limits: Limits) -> ImageReport:
    stream.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as img:
                fmt, (width, height) = img.format, img.size
                img.verify()  # structure and checksums, without decoding the pixels
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise Rejection("image_too_large", "The image declares too many pixels.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise Rejection("corrupt_image", "The image cannot be read.") from exc
    finally:
        stream.seek(0)
    if fmt != FORMATS.get(content_type):
        raise Rejection("type_mismatch", "The image content does not match its type.")
    if width > limits.max_image_side or height > limits.max_image_side or width * height > limits.max_image_pixels:
        raise Rejection(
            "image_too_large", f"The image is {width}x{height} pixels; the limit is {limits.max_image_side}."
        )
    return ImageReport(width, height)
