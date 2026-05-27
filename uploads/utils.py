import io
import ipaddress
import os
import socket
import uuid
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps

MAX_DIMENSION = 1920
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Map PIL format names to MIME types
FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "AVIF": "image/avif",
}

Image.MAX_IMAGE_PIXELS = 178956970  # ~13400x13400 pixels


def process_uploaded_image(image_file):
    """
    Validates, processes, and converts an uploaded image to AVIF format.

    Performs:
    1. File size validation
    2. Image integrity verification
    3. Format validation
    4. EXIF orientation correction
    5. Resize if exceeds MAX_DIMENSION
    6. Convert to AVIF for optimal compression

    Returns:
        tuple: (processed_file, width, height, content_type)

    Raises:
        ValidationError: If validation fails
    """
    if image_file.size > MAX_FILE_SIZE:
        raise ValidationError(
            f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB, "
            f"got {image_file.size / (1024 * 1024):.1f}MB."
        )

    try:
        img = Image.open(image_file)
        img.verify()
    except Exception as e:
        raise ValidationError(f"Invalid or corrupted image file: {e}")

    image_file.seek(0)
    img = Image.open(image_file)

    detected_format = img.format
    if detected_format not in FORMAT_TO_MIME:
        raise ValidationError(f"Unsupported image format '{detected_format}'. Allowed: JPEG, PNG, GIF, WEBP, AVIF.")

    is_animated = getattr(img, "is_animated", False) or (hasattr(img, "n_frames") and img.n_frames > 1)

    img = ImageOps.exif_transpose(img) or img

    width, height = img.size
    if not is_animated and (width > MAX_DIMENSION or height > MAX_DIMENSION):
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        width, height = img.size

    output = io.BytesIO()

    if is_animated:
        img_format = img.format or detected_format or "GIF"
        content_type = FORMAT_TO_MIME.get(img_format, "image/gif")
        original_ext = os.path.splitext(image_file.name)[1].lower()
        format_ext = f".{img_format.lower()}" if img_format else ".gif"
        extension = original_ext if original_ext else format_ext

        if img_format == "GIF":
            img.save(output, format="GIF", save_all=True, optimize=True)
        else:
            img.save(output, format=img_format)
    else:
        content_type = "image/avif"
        extension = ".avif"

        if img.mode not in ("RGB", "RGBA"):
            if img.mode == "P" and "transparency" in img.info:
                img = img.convert("RGBA")
            elif img.mode in ("LA", "L"):
                img = img.convert("RGBA" if img.mode == "LA" else "RGB")
            else:
                img = img.convert("RGB")

        img.save(
            output,
            format="AVIF",
            quality=80,
            speed=8,
        )

    output.seek(0)
    output_size = output.getbuffer().nbytes

    new_filename = f"{uuid.uuid4()}{extension}"

    return (
        InMemoryUploadedFile(
            file=output,
            field_name="ImageField",
            name=new_filename,
            content_type=content_type,
            size=output_size,
            charset=None,
        ),
        width,
        height,
        content_type,
    )


_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(host: str) -> bool:
    """Check if a hostname resolves to a private/internal IP address."""
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        pass

    try:
        addrs = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in addrs:
            try:
                addr = ipaddress.ip_address(sockaddr[0])
                if any(addr in net for net in _PRIVATE_RANGES):
                    return True
            except ValueError:
                continue
    except OSError:
        return True

    return False


def validate_image_source_url(url: str) -> None:
    """
    Validate that a URL is safe to fetch as an image source.

    Raises ValidationError if the URL is an SSRF risk (private IP, internal hostname,
    non-http scheme, etc.).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are supported.")
    if not parsed.netloc:
        raise ValidationError("URL is missing a hostname.")
    if _is_private_ip(parsed.hostname):
        raise ValidationError("URL points to a private or internal network address.")
