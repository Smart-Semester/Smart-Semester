"""Eligibility router — POST /eligibility/checks."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.clients.catalog import CatalogClient, CatalogUnavailableError
from app.schemas import EligibilityRequest, EligibilityResponse
from app.services import evaluator

router = APIRouter(prefix="/eligibility", tags=["eligibility"])


@router.post("/checks", response_model=EligibilityResponse)
def create_eligibility_check(request: EligibilityRequest) -> EligibilityResponse:
    """Check eligibility for a list of planned course codes.

    1. Normalize planned_codes (strip whitespace, uppercase).
    2. Fetch catalog data for all codes in one (batched) call.
    3. Evaluate prereqs/coreqs for each code.
    4. Return the results.
    """
    # Step 1 — normalize
    planned_codes = [c.strip().upper() for c in request.planned_codes]

    # Step 2 — build client and fetch catalog data
    catalog_url = os.environ.get("CATALOG_URL", "http://localhost:8001")
    client = CatalogClient(base_url=catalog_url)

    try:
        catalog_responses = client.get_courses(planned_codes)
    except CatalogUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Catalog service unavailable: {exc}",
        ) from exc

    # Step 3 — build lookup map
    catalog_map = {resp.code: resp for resp in catalog_responses}

    # Step 4 — evaluate
    results = evaluator.evaluate(planned_codes, catalog_map, request.completed_courses)

    # Step 5 — return
    return EligibilityResponse(results=results)
