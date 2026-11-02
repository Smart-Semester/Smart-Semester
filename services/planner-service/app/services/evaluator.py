from schemas import EligibilityRequest, EligibilityResponse, CatalogResponse, CourseResponse
from typing import List
from clients/fake_catalog import get_courses

def evaluate(eligibilityRequest: EligibilityRequest) -> EligibilityResponse:
    results: EligibilityResponse
    if (eligibilityRequest.completed_courses = [])
        # return all courses cannot_verify except ones without prereqs   
    catalogResponseList = get_courses(eligibilityRequest)
    for i in range(len(eligibilityRequest.planned_codes)):
       code = eligibilityRequest.planned_codes[i]
       courseResponse: CourseResponse
       catalogResponseList[i].prereqs:
       #traverse prereqs
       #if allof node
       #   traverse through all of node
       #   if course node then check if it's in eligibilityRequest.completedCourses then if it is, keep the status as eligible and otherwise keep it as eligible
