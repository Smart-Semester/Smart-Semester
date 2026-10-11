from fastapi import APIRouter
from app.schemas import EligibilityRequest, EligibilityResponse
from app.services import evaluator
from app.clients import catalog


router = APIRouter()

# TODO: add response_model=<your response model> to the decorator so FastAPI
#       validates and documents the output shape.
@router.post("/eligibility-checks")
def create_eligibility_check(eligibility_request: EligibilityRequest):
    # TODO: take the request model as the parameter (FastAPI reads it from the
    #       JSON body automatically because it is a Pydantic model).

    # TODO step 2: normalize codes (uppercase, strip spaces).

    # TODO step 3: fetch planned courses from Catalog in one batch call.
    #   - Codes Catalog doesn't return are "unknown_course" results,
    #     NOT a 404 for the whole request. One bad code must not sink the batch.
    #   - If Catalog is down or times out, return 503 with a clear message.

    # TODO step 4: results = evaluator.evaluate(...)
    #   The evaluator never touches the network or DB, so it can be unit
    #   tested with hand-written trees.

    # TODO step 5: return {"results": results}
    return {"results": []}  # placeholder so the app imports and runs
