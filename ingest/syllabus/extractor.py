"""PDF text extraction with failure handling and manual-review routing.

Key requirements:
- Extract text using pypdf.
- Handle malformed, corrupted, or encrypted PDFs gracefully.
- Explicitly detect scanned / image-only PDFs (lack of extractable text layer)
  and route them to manual review; do NOT silently treat them as empty text.
- Provide clear error reasons and manual-review flags.
"""
from __future__ import annotations

import dataclasses
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import pypdf
import pypdf.errors

from .models import DownloadStatus, ExtractionStatus, SyllabusDocumentRecord

logger = logging.getLogger(__name__)

# Minimum characters extracted across all pages before considering a document
# to be a scanned image / missing a text layer.
MIN_TEXT_CHARS_THRESHOLD = 50


class PDFTextExtractor:
    """Extracts text from syllabus PDF files with explicit manual-review routing."""

    def __init__(self, min_chars_threshold: int = MIN_TEXT_CHARS_THRESHOLD) -> None:
        self.min_chars_threshold = min_chars_threshold

    def extract_text(
        self,
        doc_record: SyllabusDocumentRecord,
        pdf_source: Union[bytes, str, Path],
    ) -> SyllabusDocumentRecord:
        """Extract text from PDF bytes or a file path.

        Updates and returns the SyllabusDocumentRecord.
        If extraction fails or the document is scanned, sets manual_review_required=True
        and assigns an appropriate extraction_status and reason.
        """
        now = datetime.now(timezone.utc)

        # If the document failed to download, extraction cannot proceed
        if doc_record.download_status != DownloadStatus.DOWNLOADED:
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.EXTRACTION_FAILED,
                error_message=doc_record.error_message or "Cannot extract text from un-downloaded document",
            )

        # Prepare stream
        if isinstance(pdf_source, (str, Path)):
            path = Path(pdf_source)
            if not path.is_file():
                return dataclasses.replace(
                    doc_record,
                    extraction_status=ExtractionStatus.EXTRACTION_FAILED,
                    error_message=f"PDF file not found at path: {path}",
                    manual_review_required=True,
                    manual_review_reason=f"File missing on disk: {path}",
                    extracted_at=now,
                )
            try:
                stream = io.BytesIO(path.read_bytes())
            except Exception as exc:
                return dataclasses.replace(
                    doc_record,
                    extraction_status=ExtractionStatus.EXTRACTION_FAILED,
                    error_message=f"Failed to read file from disk: {exc}",
                    manual_review_required=True,
                    manual_review_reason=f"Disk read error: {exc}",
                    extracted_at=now,
                )
        else:
            stream = io.BytesIO(pdf_source)

        # Try parsing PDF
        try:
            reader = pypdf.PdfReader(stream)
        except (pypdf.errors.PdfReadError, pypdf.errors.EmptyFileError) as exc:
            logger.warning("Malformed PDF for %s: %s", doc_record.source_url, exc)
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.MALFORMED_PDF,
                error_message=f"Malformed or corrupt PDF: {exc}",
                manual_review_required=True,
                manual_review_reason=f"Malformed PDF syntax: {exc}",
                extracted_text=None,
                extracted_at=now,
            )
        except Exception as exc:
            logger.warning("Unexpected parser error for %s: %s", doc_record.source_url, exc)
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.EXTRACTION_FAILED,
                error_message=f"Parser error: {exc}",
                manual_review_required=True,
                manual_review_reason=f"Parser exception: {exc}",
                extracted_text=None,
                extracted_at=now,
            )

        # Check encryption
        if reader.is_encrypted:
            logger.warning("Encrypted PDF for %s", doc_record.source_url)
            page_count = None
            try:
                page_count = len(reader.pages)
            except Exception:
                page_count = None
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.PASSWORD_PROTECTED,
                error_message="PDF is encrypted or password-protected",
                manual_review_required=True,
                manual_review_reason="Password-protected PDF; requires manual review or credentials",
                extracted_text=None,
                page_count=page_count,
                extracted_at=now,
            )

        # Extract text page by page
        page_texts: list[str] = []
        try:
            for page in reader.pages:
                text = page.extract_text() or ""
                page_texts.append(text)
        except Exception as exc:
            logger.warning("Error reading pages for %s: %s", doc_record.source_url, exc)
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.MALFORMED_PDF,
                error_message=f"Error reading page content streams: {exc}",
                manual_review_required=True,
                manual_review_reason=f"Page stream parsing error: {exc}",
                extracted_text=None,
                page_count=len(reader.pages),
                extracted_at=now,
            )

        full_text = "\n\n".join(page_texts).strip()
        page_count = len(reader.pages)
        char_count = len(full_text)

        # Check for empty document (0 pages)
        if page_count == 0:
            logger.warning("Document %s contains 0 pages", doc_record.source_url)
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.MALFORMED_PDF,
                extracted_text=None,  # Never represent failed extraction as empty text!
                page_count=0,
                character_count=0,
                error_message="Document contains 0 pages",
                manual_review_required=True,
                manual_review_reason="Document contains 0 pages; empty or malformed PDF.",
                extracted_at=now,
            )

        # Check for scanned image or insufficient text layer
        if char_count < self.min_chars_threshold:
            logger.info(
                "Document %s has %d pages but only %d chars of text (scanned PDF suspected)",
                doc_record.source_url,
                page_count,
                char_count,
            )
            return dataclasses.replace(
                doc_record,
                extraction_status=ExtractionStatus.SCANNED_NEEDS_OCR,
                extracted_text=None,  # Do NOT silently treat failures as empty text!
                page_count=page_count,
                character_count=char_count,
                error_message=f"Insufficient text layer ({char_count} chars across {page_count} page(s))",
                manual_review_required=True,
                manual_review_reason=(
                    f"Document contains {page_count} page(s) but has no embedded text layer "
                    f"({char_count} chars found). Appears to be a scanned image requiring OCR "
                    "or manual review."
                ),
                extracted_at=now,
            )

        # Successful extraction
        return dataclasses.replace(
            doc_record,
            extraction_status=ExtractionStatus.SUCCESS,
            extracted_text=full_text,
            page_count=page_count,
            character_count=char_count,
            error_message=None,
            manual_review_required=False,
            manual_review_reason=None,
            extracted_at=now,
        )
