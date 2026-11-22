"""Syllabus PDF downloader with integrity checks, size limits, and change detection.

Key features:
- Download integrity checks: streams bytes, computes SHA-256 hash.
- Size limits: verifies Content-Length header and aborts stream if size limit exceeded
  (default 10 MB, configurable).
- Content-type validation: ensures application/pdf or %PDF- magic bytes; rejects
  HTML error pages and unsupported formats.
- Filename handling: parses Content-Disposition (RFC 6266 / RFC 5987), sanitizes
  against directory traversal, and provides canonical fallback names.
- Duplicate detection: identifies identical documents by SHA-256 hash.
- Missing / changed document behavior: handles HTTP 404/410/5xx cleanly without
  swallowing errors; detects when upstream content changes.
- Retention: stores PDFs in a configurable directory (default data/syllabi).
"""
from __future__ import annotations

import email.message
import hashlib
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .models import DownloadStatus, SyllabusDocumentRecord, SyllabusRecord

logger = logging.getLogger(__name__)

# Default maximum allowed PDF size: 10 MB
DEFAULT_MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024
DEFAULT_STORAGE_DIR = "data/syllabi"
CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal and unsafe characters."""
    # Strip path components and directory traversal
    name = os.path.basename(filename.strip().replace("\\", "/"))
    # Remove null bytes and control chars
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    # Replace dangerous or reserved characters
    name = re.sub(r'[/\\:*?"<>|]', "_", name)
    # Ensure it's not empty and ends with .pdf
    if not name or name.strip(".") == "":
        name = "syllabus.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def parse_content_disposition_filename(header_value: str) -> Optional[str]:
    """Parse filename from Content-Disposition header.

    Supports both standard `filename="foo.pdf"` and RFC 5987 `filename*=UTF-8''foo%20bar.pdf`.
    """
    if not header_value:
        return None

    # Use email.message to parse the Content-Disposition header properly
    msg = email.message.EmailMessage()
    msg["Content-Disposition"] = header_value
    params = msg.get_params(header="Content-Disposition")
    if not params:
        return None

    for param, val in params:
        if param.lower() == "filename*":
            # RFC 5987 format: charset'lang'encoded-value
            if "''" in val:
                _, _, encoded = val.partition("''")
                return sanitize_filename(urllib.parse.unquote(encoded))
            return sanitize_filename(val)
        if param.lower() == "filename":
            return sanitize_filename(val.strip('"\''))

    return None


class SyllabusDownloader:
    """Downloads syllabus PDF documents with verification, size limits, and change detection."""

    def __init__(
        self,
        storage_dir: Optional[str | Path] = None,
        max_size_bytes: int = DEFAULT_MAX_PDF_SIZE_BYTES,
        retain_pdf: bool = True,
        timeout: int = 15,
        user_agent: str = "SmartSemester-Bot/1.0 (PDF Ingest; university project)",
        rate_limit_delay: float = 0.25,
        opener: Optional[Callable] = None,
    ) -> None:
        self.storage_dir = Path(storage_dir or os.environ.get("SYLLABUS_STORAGE_DIR", DEFAULT_STORAGE_DIR))
        self.max_size_bytes = max_size_bytes
        self.retain_pdf = retain_pdf
        self.timeout = timeout
        self.user_agent = user_agent
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0
        self._opener = opener or urllib.request.urlopen
        self._seen_hashes: dict[str, str] = {}  # content_hash -> first source_url seen

        if self.retain_pdf:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _throttle(self) -> None:
        """Enforce rate limiting between requests."""
        if self.rate_limit_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def download_document(
        self,
        syllabus: SyllabusRecord,
        existing_doc: Optional[SyllabusDocumentRecord] = None,
    ) -> tuple[SyllabusDocumentRecord, Optional[bytes]]:
        """Download and verify a syllabus PDF.

        Returns (document_record, downloaded_bytes_or_none).
        """
        # If section has no syllabus or no download URL
        if not syllabus.has_syllabus or not syllabus.source_url:
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    download_status=DownloadStatus.MISSING,
                    error_message="Section has no syllabus available (has_syllabus=False)",
                    manual_review_required=False,
                ),
                None,
            )

        self._throttle()

        req = urllib.request.Request(syllabus.source_url)
        req.add_header("User-Agent", self.user_agent)

        try:
            resp = self._opener(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            logger.warning("HTTP %d error downloading %s: %s", exc.code, syllabus.source_url, exc.reason)
            is_missing = exc.code in (404, 410)
            status = DownloadStatus.MISSING if is_missing else DownloadStatus.DOWNLOAD_FAILED
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    download_status=status,
                    error_message=f"HTTP {exc.code}: {exc.reason}",
                    manual_review_required=not is_missing,
                    manual_review_reason=f"Download failed with HTTP {exc.code}" if not is_missing else None,
                ),
                None,
            )
        except Exception as exc:
            logger.warning("Network error downloading %s: %s", syllabus.source_url, exc)
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    download_status=DownloadStatus.DOWNLOAD_FAILED,
                    error_message=f"Network error: {exc}",
                    manual_review_required=True,
                    manual_review_reason=f"Network or connection failure: {exc}",
                ),
                None,
            )

        # ── Check Content-Length upfront ──────────────────────────────────────
        content_length_header = resp.headers.get("Content-Length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
                if content_length > self.max_size_bytes:
                    logger.warning(
                        "File size %d exceeds limit of %d bytes for %s",
                        content_length,
                        self.max_size_bytes,
                        syllabus.source_url,
                    )
                    return (
                        SyllabusDocumentRecord(
                            syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                            source_url=syllabus.source_url,
                            file_size=content_length,
                            download_status=DownloadStatus.EXCEEDS_SIZE_LIMIT,
                            error_message=(
                                f"Content-Length ({content_length} bytes) exceeds limit "
                                f"({self.max_size_bytes} bytes)"
                            ),
                            manual_review_required=True,
                            manual_review_reason="Document exceeds size limit; requires manual review.",
                        ),
                        None,
                    )
            except ValueError:
                pass

        # ── Check Content-Type ───────────────────────────────────────────────
        content_type = resp.headers.get("Content-Type", "")
        # Detect HTML responses (e.g. error/login page with 200 OK)
        if "text/html" in content_type.lower():
            logger.warning(
                "Upstream returned HTML content-type '%s' for %s",
                content_type,
                syllabus.source_url,
            )
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    content_type=content_type,
                    download_status=DownloadStatus.UNSUPPORTED_TYPE,
                    error_message=f"Received Content-Type '{content_type}' instead of PDF (likely HTML landing or error page)",
                    manual_review_required=True,
                    manual_review_reason="Document returned HTML instead of PDF; manual review needed.",
                ),
                None,
            )

        # ── Stream body chunks & compute SHA-256 ─────────────────────────────
        hasher = hashlib.sha256()
        chunks: list[bytes] = []
        total_bytes = 0

        try:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > self.max_size_bytes:
                    logger.warning(
                        "Download stream exceeded max size %d bytes for %s",
                        self.max_size_bytes,
                        syllabus.source_url,
                    )
                    return (
                        SyllabusDocumentRecord(
                            syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                            source_url=syllabus.source_url,
                            file_size=total_bytes,
                            content_type=content_type,
                            download_status=DownloadStatus.EXCEEDS_SIZE_LIMIT,
                            error_message=(
                                f"Streamed bytes ({total_bytes}) exceeded maximum allowed limit "
                                f"({self.max_size_bytes} bytes)"
                            ),
                            manual_review_required=True,
                            manual_review_reason="Streamed document exceeded size limit.",
                        ),
                        None,
                    )
                hasher.update(chunk)
                chunks.append(chunk)
        except Exception as exc:
            logger.warning("Error streaming bytes for %s: %s", syllabus.source_url, exc)
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    download_status=DownloadStatus.DOWNLOAD_FAILED,
                    error_message=f"Streaming interrupted: {exc}",
                    manual_review_required=True,
                    manual_review_reason=f"Download stream error: {exc}",
                ),
                None,
            )

        full_bytes = b"".join(chunks)
        content_hash = hasher.hexdigest()

        # ── Duplicate & Change Detection ─────────────────────────────────────
        if content_hash in self._seen_hashes:
            logger.info(
                "Duplicate syllabus document detected: %s shares identical SHA-256 hash (%s) with %s",
                syllabus.source_url,
                content_hash,
                self._seen_hashes[content_hash],
            )
        self._seen_hashes[content_hash] = syllabus.source_url

        if existing_doc and existing_doc.content_hash:
            if existing_doc.content_hash == content_hash:
                logger.debug(
                    "Document content unchanged for %s (hash: %s)",
                    syllabus.source_url,
                    content_hash,
                )
            else:
                logger.info(
                    "Document content changed for %s: old hash %s -> new hash %s",
                    syllabus.source_url,
                    existing_doc.content_hash,
                    content_hash,
                )

        # ── Verify PDF magic header ──────────────────────────────────────────
        # Valid PDFs start with %PDF-
        if not full_bytes.startswith(b"%PDF-"):
            # Check if it looks like HTML or plain text error
            is_html = b"<html" in full_bytes[:200].lower() or b"<!doctype html" in full_bytes[:200].lower()
            err_msg = "Content is an HTML page disguised as PDF" if is_html else "Missing %PDF- magic header"
            logger.warning("%s for %s", err_msg, syllabus.source_url)
            return (
                SyllabusDocumentRecord(
                    syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
                    source_url=syllabus.source_url,
                    content_type=content_type,
                    content_hash=content_hash,
                    file_size=total_bytes,
                    download_status=DownloadStatus.UNSUPPORTED_TYPE,
                    error_message=err_msg,
                    manual_review_required=True,
                    manual_review_reason=f"Invalid PDF header: {err_msg}",
                ),
                None,
            )

        # ── Extract / Determine Filename ─────────────────────────────────────
        disposition = resp.headers.get("Content-Disposition", "")
        filename = parse_content_disposition_filename(disposition)
        if not filename:
            # Fallback to URL path basename
            url_path = urllib.parse.urlparse(syllabus.source_url).path
            base = os.path.basename(url_path)
            if base and base.lower().endswith(".pdf"):
                filename = sanitize_filename(base)
            else:
                # Canonical naming fallback
                filename = sanitize_filename(
                    f"{syllabus.course_code}_{syllabus.section}_{syllabus.semester_code}.pdf"
                )

        # ── Save to disk if retention enabled ─────────────────────────────────
        saved_file_path: Optional[str] = None
        if self.retain_pdf:
            # Content-addressed naming with course metadata for readability
            save_name = f"{syllabus.course_code}_{syllabus.semester_code}_{syllabus.section}_{content_hash[:10]}.pdf"
            dest = self.storage_dir / save_name
            try:
                dest.write_bytes(full_bytes)
                saved_file_path = str(dest)
            except Exception as exc:
                logger.error("Failed to save PDF to %s: %s", dest, exc)
                # Still proceed since bytes are available in memory

        now = datetime.now(timezone.utc)
        doc_record = SyllabusDocumentRecord(
            syllabus_id=getattr(syllabus, "syllabus_id", "") or syllabus.source_url,
            source_url=syllabus.source_url,
            file_path=saved_file_path,
            content_type=content_type or "application/pdf",
            original_filename=filename,
            content_hash=content_hash,
            file_size=total_bytes,
            download_status=DownloadStatus.DOWNLOADED,
            downloaded_at=now,
            manual_review_required=False,
        )

        return doc_record, full_bytes
