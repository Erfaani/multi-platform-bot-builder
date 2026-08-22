"""Upload validation and sanitisation (SECURITY.md §7).

Applies to receipts, logos, AI documents and support attachments. The threat is
concrete: a customer uploads a file, a finance agent opens it in a browser, and anything
we failed to check runs in an admin session.

The pipeline:

1. Size cap, checked before anything is read into memory.
2. Extension allowlist **and** content-sniffed magic bytes — both must agree, because a
   `.png` extension proves nothing and a sniffed type alone lets `evil.html.png` through.
3. Images are re-encoded, which strips EXIF (a receipt photo carries GPS) and destroys
   any payload smuggled in a valid-looking image.
4. Filenames are regenerated; the original is kept as metadata only, so there is no
   path-traversal surface.
5. SHA-256 is computed for duplicate detection.

SVG is rejected everywhere — it is script-capable, so it is an XSS vector by design.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _

from apps.core.errors import ValidationError

#: Magic bytes → canonical content type. Deliberately short: every entry is a format we
#: are prepared to re-encode or serve safely.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
)

_WEBP_PREFIX = b"RIFF"
_WEBP_MARKER = b"WEBP"

IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    allowed_types: frozenset[str]
    allowed_extensions: frozenset[str]
    max_bytes: int
    reencode_images: bool = True


RECEIPT_POLICY = UploadPolicy(
    allowed_types=frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"}),
    allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".webp", ".pdf"}),
    max_bytes=5 * 1024 * 1024,
)

LOGO_POLICY = UploadPolicy(
    allowed_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
    allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".webp"}),
    max_bytes=2 * 1024 * 1024,
)

DOCUMENT_POLICY = UploadPolicy(
    allowed_types=frozenset({"application/pdf", "image/jpeg", "image/png"}),
    allowed_extensions=frozenset({".pdf", ".jpg", ".jpeg", ".png"}),
    max_bytes=20 * 1024 * 1024,
    reencode_images=False,
)

#: Product/property/course photos — the one kind of upload in this codebase meant to be
#: *publicly* viewable rather than kept private like receipts or AI documents. The
#: policy itself is identical to `LOGO_POLICY` (images only, re-encoded to strip
#: metadata); what differs is where the caller stores the result — see
#: `apps.commerce.models._public_upload_to` and `config/urls.py`'s dev-only public
#: media route, which is scoped to exactly the `public/` prefix these uploads use.
PUBLIC_IMAGE_POLICY = UploadPolicy(
    allowed_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
    allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".webp"}),
    max_bytes=5 * 1024 * 1024,
)


@dataclass(frozen=True, slots=True)
class SafeUpload:
    content: ContentFile
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    original_filename: str


def public_file_url(file_field) -> str:
    """The servable URL for a `public/`-prefixed `FileField` (`PUBLIC_IMAGE_POLICY`
    uploads). Deliberately not `file_field.url` — `Storage.url()` is built from
    `settings.MEDIA_URL`, which stays `None` on purpose (SECURITY.md §7: nothing is
    servable from the bare media root). This constructs the URL from
    `settings.PUBLIC_MEDIA_URL` instead, matching the one route `config/urls.py` (dev)
    or object storage/CDN (production) actually exposes."""
    if not file_field:
        return ""
    from django.conf import settings

    relative = file_field.name.removeprefix("public/")
    return f"{settings.PUBLIC_MEDIA_URL}{relative}"


def sniff_content_type(head: bytes) -> str | None:
    """Identify a file by its bytes. Returns None for anything unrecognised."""
    for magic, content_type in _MAGIC:
        if head.startswith(magic):
            return content_type
    if head[:4] == _WEBP_PREFIX and head[8:12] == _WEBP_MARKER:
        return "image/webp"
    return None


def _extension_of(name: str) -> str:
    _, _, ext = name.rpartition(".")
    return f".{ext.lower()}" if ext and ext != name else ""


def _reencode_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Re-encode through Pillow, dropping metadata and any embedded payload."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return data, content_type

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        # A decompression bomb would be an easy denial of service on the worker.
        if image.width * image.height > 50_000_000:
            raise ValidationError(
                code="upload.image_too_large",
                message=str(_("That image has too many pixels.")),
            )

        target = "PNG" if content_type == "image/png" else "JPEG"
        if target == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        buffer = io.BytesIO()
        # `Image.save` on a fresh object writes no EXIF unless asked.
        image.save(buffer, format=target, quality=88, optimize=True)

    return buffer.getvalue(), "image/png" if target == "PNG" else "image/jpeg"


def validate_and_sanitise(upload: UploadedFile, policy: UploadPolicy) -> SafeUpload:
    """Run the full pipeline, or raise :class:`ValidationError`."""
    original_name = (upload.name or "upload")[:255]

    if upload.size is None or upload.size <= 0:
        raise ValidationError(code="upload.empty", message=str(_("The file is empty.")))

    if upload.size > policy.max_bytes:
        raise ValidationError(
            code="upload.too_large",
            message=str(
                _("That file is larger than the %(mb)s MB limit.")
                % {"mb": policy.max_bytes // (1024 * 1024)}
            ),
        )

    extension = _extension_of(original_name)
    if extension not in policy.allowed_extensions:
        raise ValidationError(
            code="upload.extension_not_allowed",
            message=str(
                _("Allowed file types: %(types)s.")
                % {"types": ", ".join(sorted(policy.allowed_extensions))}
            ),
        )

    data = upload.read()
    sniffed = sniff_content_type(data[:32])

    if sniffed is None:
        raise ValidationError(
            code="upload.unrecognised_type",
            message=str(_("We could not recognise that file type.")),
        )

    if sniffed not in policy.allowed_types:
        raise ValidationError(
            code="upload.type_not_allowed",
            message=str(_("That file type is not accepted here.")),
        )

    # Extension and content must agree. `invoice.pdf` that is really a PNG is either a
    # mistake or an attempt, and neither should be stored.
    expected = {
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "image/webp": {".webp"},
        "application/pdf": {".pdf"},
    }[sniffed]
    if extension not in expected:
        raise ValidationError(
            code="upload.type_mismatch",
            message=str(_("The file contents do not match its extension.")),
        )

    content_type = sniffed
    if policy.reencode_images and sniffed in IMAGE_TYPES:
        data, content_type = _reencode_image(data, sniffed)

    digest = hashlib.sha256(data).hexdigest()
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}.get(
        content_type, extension
    )
    filename = f"{uuid.uuid4().hex}{suffix}"

    return SafeUpload(
        content=ContentFile(data, name=filename),
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
        original_filename=original_name,
    )
