from fastapi import APIRouter
from app.schemas import CompletedCourse, TranscriptRequest
from app.services import transcript_parser
from typing import List

router = APIRouter()

@router.post("/transcript", response_model=List[CompletedCourse])
def get_parsed_transcript(transcriptRequest: TranscriptRequest):
    results = transcript_parser.parse_transcript(transcriptRequest.text)

    return results
