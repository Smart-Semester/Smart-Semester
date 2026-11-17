from fastapi import APIRouter
from app.schemas import CompletedCourse
from app.services import transcript_parser
from typing import List

router = APIRouter()

@router.post("/transcript", response_model=List[CompletedCourse])
def get_parsed_transcript(inputString: str):
    results = transcript_parser.parse_transcript(inputString)

    return results
