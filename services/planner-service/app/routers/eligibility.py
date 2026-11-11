from fastapi import APIRouter
from app.schemas import EligibilityRequest, EligibilityResponse, CatalogResponse
from app.services import evaluator
from app.clients import fake_catalog
from typing import List

router = APIRouter()

@router.post("/eligibility-checks", response_model=EligibilityResponse)
def create_eligibility_check(eligibilityRequest: EligibilityRequest):
    # normalize course codes
    eligibilityRequest.planned_codes = [c.upper().replace(" ","") for c in eligibilityRequest.planned_codes]
    for completed_course in eligibilityRequest.completed_courses:
        completed_course.code = completed_course.code.upper().replace(" ","")

    catalogResponseList = fake_catalog.get_courses(eligibilityRequest.planned_codes)

    results = evaluator.evaluate(eligibilityRequest, catalogResponseList)

    return results
