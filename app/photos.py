"""Profile photos: any phone picture in, one small square WebP out.

Re-encoding is the point. It strips EXIF (a phone photo carries the GPS
position it was taken at, and profiles are public), normalises rotation, and
means the file we serve is one we wrote, not whatever was uploaded.
"""

import hashlib
import io
import os
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app import config

MAX_BYTES = 5 * 1024 * 1024
SIZE = 256
# Anything larger is a decompression bomb, not a phone camera.
Image.MAX_IMAGE_PIXELS = 60_000_000


class PhotoError(ValueError):
    pass


def store(raw: bytes) -> str:
    """Save the photo and return its file name under AVATARS_DIR."""
    if len(raw) > MAX_BYTES:
        raise PhotoError("照片太大了，请选一张 5 MB 以内的")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP", "GIF", "MPO"):
                    raise PhotoError("请上传 JPG、PNG 或 WebP 照片")
                image = ImageOps.exif_transpose(image)
                image = ImageOps.fit(image.convert("RGB"), (SIZE, SIZE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as error:
        raise PhotoError("这张照片打不开，换一张试试（iPhone 可在设置里把相机格式改为“兼容性最佳”）") from error
    output = io.BytesIO()
    image.save(output, "WEBP", quality=85)
    data = output.getvalue()
    name = hashlib.sha256(data).hexdigest()[:16] + ".webp"
    config.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.AVATARS_DIR / name
    if not path.exists():
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    return name
