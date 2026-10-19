"""Lossless WebP encoding for screenshots and replay frames."""

from io import BytesIO

from PIL import Image


def encode_webp(width: int, height: int, rgb: bytes) -> bytes:
    """Encode RGB pixels without resizing or changing their values."""
    if width <= 0 or height <= 0:
        raise ValueError("WebP dimensions must be positive")
    if len(rgb) != width * height * 3:
        raise ValueError(f"expected {width * height * 3} bytes of RGB data, got {len(rgb)}")
    with Image.frombytes("RGB", (width, height), rgb) as image, BytesIO() as output:
        image.save(output, format="WEBP", lossless=True, method=1)
        return output.getvalue()
