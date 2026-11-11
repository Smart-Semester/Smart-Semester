"""CatalogClient — calls the Catalog service's GET /courses endpoint using
urllib (stdlib only, no extra dependency).

Raises CatalogUnavailableError when the upstream service cannot be reached
or times out.  Unknown course codes are silently absent from the returned list.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from app.schemas import CatalogResponse


class CatalogUnavailableError(Exception):
    """Raised when the Catalog service cannot be reached or times out."""


class CatalogClient:
    """HTTP client for the Catalog service.

    Args:
        base_url: Base URL of the catalog service, e.g. "http://catalog-service:8001".
                  Trailing slashes are stripped.
    """

    _BATCH_SIZE = 20
    _TIMEOUT = 5  # seconds

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_courses(self, codes: List[str]) -> List[CatalogResponse]:
        """Fetch CatalogResponse objects for the given course codes.

        Splits *codes* into batches of at most 20 (the catalog contract limit),
        merges the results and returns them.  Codes not found in the catalog are
        simply absent from the returned list.

        Raises:
            CatalogUnavailableError: If any batch request fails due to a
                connection error or timeout.
        """
        results: List[CatalogResponse] = []
        for batch in self._batches(codes):
            results.extend(self._fetch_batch(batch))
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _batches(codes: List[str]):
        """Yield successive slices of *codes* of size <= _BATCH_SIZE."""
        for i in range(0, len(codes), CatalogClient._BATCH_SIZE):
            yield codes[i : i + CatalogClient._BATCH_SIZE]

    def _fetch_batch(self, codes: List[str]) -> List[CatalogResponse]:
        """Perform one GET /courses request for a single batch of codes."""
        # Build query string: ?codes=A&codes=B&...
        query = urllib.parse.urlencode([("codes", c) for c in codes])
        url = f"{self._base_url}/courses?{query}"

        try:
            with urllib.request.urlopen(url, timeout=self._TIMEOUT) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise CatalogUnavailableError(
                f"Catalog service unavailable: {exc}"
            ) from exc

        payload = json.loads(raw)
        return [CatalogResponse(**item) for item in payload]
