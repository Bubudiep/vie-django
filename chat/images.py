import base64
import io
import logging

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageFilter, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# "HD" cap on the longer edge of an uploaded image — keeps chat photos from
# eating storage/bandwidth at full camera resolution (12MP+) while staying
# sharp enough to view full-screen.
MAX_DIMENSION = 1920
JPEG_QUALITY = 85

# A tiny, heavily blurred copy embedded as a base64 data URI — not a separate
# file, since a placeholder only helps on a slow connection if it renders
# with zero extra network round-trips — so the frontend can paint it
# instantly (classic blur-up/LQIP) while the full image is still loading.
PREVIEW_MAX_DIMENSION = 24
PREVIEW_JPEG_QUALITY = 30
PREVIEW_BLUR_RADIUS = 3


def _fit(image, max_dimension):
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dimension:
        return image
    scale = max_dimension / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.LANCZOS)


def process_image(uploaded_file, name):
    """Downscale an uploaded image to fit an HD box and re-encode it as JPEG,
    plus build a tiny blurred placeholder for instant "loading" UI on a slow
    connection.

    Returns (file, preview_data_url): `file` is a ready-to-save ContentFile
    (JPEG, HD-capped), or None if Pillow is unavailable or the upload isn't a
    readable image — callers should fall back to storing the original as-is.
    """
    if not PILLOW_AVAILABLE:
        logger.warning('Pillow not installed — skipping image processing for %r', name)
        return None, ''

    try:
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)
        image.load()
    except Exception:
        logger.warning('Could not read %r as an image — storing as-is', name, exc_info=True)
        return None, ''

    image = ImageOps.exif_transpose(image)
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')

    resized = _fit(image, MAX_DIMENSION)
    buffer = io.BytesIO()
    resized.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    base = name.rsplit('.', 1)[0] if '.' in name else name
    processed_file = ContentFile(buffer.getvalue(), name=f'{base}.jpg')

    preview = _fit(image, PREVIEW_MAX_DIMENSION).filter(ImageFilter.GaussianBlur(radius=PREVIEW_BLUR_RADIUS))
    preview_buffer = io.BytesIO()
    preview.save(preview_buffer, format='JPEG', quality=PREVIEW_JPEG_QUALITY)
    preview_data_url = 'data:image/jpeg;base64,' + base64.b64encode(preview_buffer.getvalue()).decode('ascii')

    return processed_file, preview_data_url
