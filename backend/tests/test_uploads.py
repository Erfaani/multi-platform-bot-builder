"""Upload validation (SECURITY.md §7).

Receipts are attacker-controlled files that a finance agent opens in a browser session.
Every test here is a specific way that could go wrong.
"""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.errors import ValidationError
from apps.core.files import (
    RECEIPT_POLICY,
    sniff_content_type,
    validate_and_sanitise,
)


def png_bytes(width: int = 8, height: int = 8, **save_kwargs) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG", **save_kwargs)
    return buffer.getvalue()


def jpeg_bytes(width: int = 8, height: int = 8) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def upload(data: bytes, name: str, content_type: str = "image/png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type=content_type)


class TestSniffing:
    def test_recognises_png(self):
        assert sniff_content_type(png_bytes()[:32]) == "image/png"

    def test_recognises_jpeg(self):
        assert sniff_content_type(jpeg_bytes()[:32]) == "image/jpeg"

    def test_recognises_pdf(self):
        assert sniff_content_type(b"%PDF-1.7\n...") == "application/pdf"

    def test_unknown_bytes_return_none(self):
        assert sniff_content_type(b"just some text") is None


class TestAcceptance:
    def test_a_genuine_png_is_accepted(self):
        safe = validate_and_sanitise(upload(png_bytes(), "receipt.png"), RECEIPT_POLICY)
        assert safe.content_type == "image/png"
        assert safe.sha256

    def test_a_genuine_jpeg_is_accepted(self):
        safe = validate_and_sanitise(
            upload(jpeg_bytes(), "receipt.jpg", "image/jpeg"), RECEIPT_POLICY
        )
        assert safe.content_type == "image/jpeg"

    def test_a_pdf_is_accepted(self):
        safe = validate_and_sanitise(
            upload(b"%PDF-1.7\n" + b"0" * 200, "receipt.pdf", "application/pdf"),
            RECEIPT_POLICY,
        )
        assert safe.content_type == "application/pdf"


class TestRejection:
    def test_a_script_disguised_as_an_image_is_rejected(self):
        """`evil.png` containing HTML is the classic stored-XSS delivery."""
        payload = b"<html><script>alert(document.cookie)</script></html>"
        with pytest.raises(ValidationError) as exc:
            validate_and_sanitise(upload(payload, "evil.png"), RECEIPT_POLICY)
        assert exc.value.code == "upload.unrecognised_type"

    def test_a_png_renamed_to_pdf_is_rejected(self):
        """Extension and content must agree, or neither can be trusted."""
        with pytest.raises(ValidationError) as exc:
            validate_and_sanitise(
                upload(png_bytes(), "receipt.pdf", "application/pdf"), RECEIPT_POLICY
            )
        assert exc.value.code == "upload.type_mismatch"

    def test_svg_is_rejected(self):
        """SVG is script-capable — an XSS vector by design."""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(ValidationError):
            validate_and_sanitise(upload(svg, "logo.svg", "image/svg+xml"), RECEIPT_POLICY)

    def test_an_executable_is_rejected(self):
        with pytest.raises(ValidationError):
            validate_and_sanitise(upload(b"MZ\x90\x00", "invoice.exe"), RECEIPT_POLICY)

    def test_a_disallowed_extension_is_rejected_before_reading(self):
        with pytest.raises(ValidationError) as exc:
            validate_and_sanitise(upload(png_bytes(), "receipt.gif"), RECEIPT_POLICY)
        assert exc.value.code == "upload.extension_not_allowed"

    def test_an_oversized_file_is_rejected(self):
        oversized = SimpleUploadedFile("big.png", b"x" * (RECEIPT_POLICY.max_bytes + 1))
        with pytest.raises(ValidationError) as exc:
            validate_and_sanitise(oversized, RECEIPT_POLICY)
        assert exc.value.code == "upload.too_large"

    def test_an_empty_file_is_rejected(self):
        with pytest.raises(ValidationError):
            validate_and_sanitise(SimpleUploadedFile("empty.png", b""), RECEIPT_POLICY)

    def test_a_path_traversal_filename_cannot_escape(self):
        safe = validate_and_sanitise(
            upload(png_bytes(), "../../../etc/passwd.png"), RECEIPT_POLICY
        )
        assert "/" not in safe.filename
        assert ".." not in safe.filename


class TestSanitisation:
    def test_the_filename_is_regenerated(self):
        safe = validate_and_sanitise(upload(png_bytes(), "receipt.png"), RECEIPT_POLICY)
        assert safe.filename != "receipt.png"
        assert safe.original_filename == "receipt.png"

    def test_exif_is_stripped_by_re_encoding(self):
        """Camera metadata in a receipt photo is a real privacy leak (GPS, device id)."""
        from PIL import Image

        buffer = io.BytesIO()
        image = Image.new("RGB", (8, 8), "red")
        exif = image.getexif()
        exif[0x010E] = "secret-location-note"  # ImageDescription
        exif[0x010F] = "SecretPhoneModel"  # Make
        image.save(buffer, format="JPEG", exif=exif)

        original = buffer.getvalue()
        assert b"secret-location-note" in original, "fixture must actually carry EXIF"

        safe = validate_and_sanitise(
            upload(original, "photo.jpg", "image/jpeg"), RECEIPT_POLICY
        )
        cleaned = safe.content.read()
        assert b"secret-location-note" not in cleaned
        assert b"SecretPhoneModel" not in cleaned

    def test_appended_payload_does_not_survive_re_encoding(self):
        """A polyglot file with a payload after the image data is neutralised."""
        poisoned = png_bytes() + b"<script>alert(1)</script>"
        safe = validate_and_sanitise(upload(poisoned, "receipt.png"), RECEIPT_POLICY)
        assert b"<script>" not in safe.content.read()

    def test_identical_content_produces_an_identical_hash(self):
        data = png_bytes()
        first = validate_and_sanitise(upload(data, "a.png"), RECEIPT_POLICY)
        second = validate_and_sanitise(upload(data, "b.png"), RECEIPT_POLICY)
        assert first.sha256 == second.sha256

    def test_different_content_produces_different_hashes(self):
        first = validate_and_sanitise(upload(png_bytes(8, 8), "a.png"), RECEIPT_POLICY)
        second = validate_and_sanitise(upload(png_bytes(16, 16), "b.png"), RECEIPT_POLICY)
        assert first.sha256 != second.sha256
