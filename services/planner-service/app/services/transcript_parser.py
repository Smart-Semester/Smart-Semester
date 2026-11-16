from app.schemas import CompletedCourse
from typing import List
import re

# compile raegex with python raw string and compile it with re.compile()
REGEX = re.compile(r"""
^                          # anchors at the start of the line
(?P<code>[A-Z]{2,4})       # puts code (CS, MATH, etc.) into 'code' capture group 
\s?                        # white space
(?P<number>\d{4})          # puts numbers (3358, 1234, etc.) into 'number' capture group
\s+
(?P<title>.+?)             # course title (DATA STRUCTURES, etc.)
\s+
(?P<grade>[A-Z]{1,2})      # grade (A, B, C, W, IP, etc.)
\s+
(?P<credits>\d+(?:\.\d+)?) # credits (3, 4, etc.)
\s*$
""", re.VERBOSE)
   
def parse_transcript(transcript: str) -> List[CompletedCourse]:
    # split input string into multi-line input strings
    lines = transcript.splitlines()

    response = []
    for line in lines:
        # put results into a group dict
        results = REGEX.match(line.strip())

        # not a course line
        if results is None:
            continue

        group = results.groupdict()
        
        # add to response
        response.append(CompletedCourse(
            code = group["code"] + group["number"],
            grade = group["grade"],
        ))

    return response
