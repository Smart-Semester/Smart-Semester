from app.schemas import EligibilityRequest, EligibilityResponse, CatalogResponse, CourseResponse, CourseStatus
from typing import List

def evaluate(eligibilityRequest: EligibilityRequest, completedCourses: List[str]) -> EligibilityResponse:
    response = EligibilityResponse()
    if (eligibilityRequest.completed_courses == []):
        # return all courses cannot_verify except ones without prereqs
        for i in range(len(eligibilityRequest.planned_codes)):
            code = eligibilityRequest.planned_codes[i]
            if ((completedCourses[i].prereqs) == None and (completedCourses[i].coreqs) == None):
                courseResponse = CourseResponse(status=CourseStatus.ELIGIBLE, code=code)
            else:
                courseResponse = CourseResponse(status=CourseStatus.CANNOT_VERIFY, code=code)
            response.results.append(courseResponse)
        return response

    for i in range(len(eligibilityRequest.planned_codes)):
        code = eligibilityRequest.planned_codes[i]
        # completedCourses[i].prereqs
        # traverse prereqs
        # if allof node
        #   traverse through all of node
        #   if course node then check if it's in eligibilityRequest.completedCourses then if it is, keep the status as eligible and otherwise keep it as eligible
        pass
