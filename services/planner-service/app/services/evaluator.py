from app.schemas import EligibilityRequest, EligibilityResponse, CatalogResponse, CourseResponse, CourseStatus
from typing import List
from enum import Enum

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
class NodeStatus(Enum):
   MET = "met"
   UNMET = "unmet"
   UNKNOWN = "unknown"

def check_node(node, completed, planned, is_coreq) -> NodeStatus:
    if (node == None):
        return NodeStatus.MET
    elif (node.kind == "course"):
        grade = completed.get(node.code)
        if (grade in GRADE_RANK and GRADE_RANK[grade] >= GRADE_RANK[node.min_grade]):
            return NodeStatus.MET
        elif (is_coreq and (node.code in planned or grade == "IP")):
            return NodeStatus.MET
        else:
            return NodeStatus.UNMET
    elif (node.kind == "manual"):
        return NodeStatus.UNKNOWN
    elif (node.kind == "all_of"):
        results = [check_node(child, completed, planned, is_coreq) for child in node.children]
        if NodeStatus.UNMET in results:      # any child unmet
            return NodeStatus.UNMET
        elif NodeStatus.UNKNOWN in results:
            return NodeStatus.UNKNOWN
        else:
            return NodeStatus.MET
    elif (node.kind == "any_of"):
        results = [check_node(child, completed, planned, is_coreq) for child in node.children]
        if NodeStatus.MET in results:
            return NodeStatus.MET
        elif NodeStatus.UNKNOWN in results:
            return NodeStatus.UNKNOWN
        else:
            return NodeStatus.UNMET

def evaluate(eligibilityRequest: EligibilityRequest, catalogResponseList: List[CatalogResponse]) -> EligibilityResponse:
    completed = {c.code: c.grade for c in eligibilityRequest.completed_courses}
    planned = set(eligibilityRequest.planned_codes)
    catalog_by_code = {c.code: c for c in catalogResponseList}

    response = EligibilityResponse()
    if (eligibilityRequest.completed_courses == []):
        # return all courses cannot_verify except ones without prereqs
        for i in range(len(eligibilityRequest.planned_codes)):
            code = eligibilityRequest.planned_codes[i]
            course = catalog_by_code.get(code)
            if course is None:
               response.results.append(CourseResponse(status=CourseStatus.UNKNOWN_COURSE, code=code))
               continue
            if ((course.prereqs) == None and (course.coreqs) == None):
                courseResponse = CourseResponse(status=CourseStatus.ELIGIBLE, code=code)
            else:
                courseResponse = CourseResponse(status=CourseStatus.CANNOT_VERIFY, code=code)
            response.results.append(courseResponse)
        return response

    for i in range(len(eligibilityRequest.planned_codes)):
        code = eligibilityRequest.planned_codes[i]
        course = catalog_by_code.get(code)
        if course is None:
            response.results.append(CourseResponse(status=CourseStatus.UNKNOWN_COURSE, code=code))
            continue

        prereq_result = check_node(course.prereqs, completed, planned, is_coreq=False)
        coreq_result = check_node(course.coreqs, completed, planned, is_coreq=True)

        if (prereq_result == NodeStatus.UNMET or coreq_result == NodeStatus.UNMET):
            status = CourseStatus.NOT_ELIGIBLE
        elif (prereq_result == NodeStatus.UNKNOWN or coreq_result == NodeStatus.UNKNOWN):
            status = CourseStatus.CANNOT_VERIFY
        else:
            status = CourseStatus.ELIGIBLE

        courseResponse = CourseResponse(status=status, code=code)
        response.results.append(courseResponse)

    return response
# ---- LATER (not in the first version) ----
#   fill unmet_prereqs / unmet_coreqs. check_node would also return the
#   part of the tree that failed (all_of: only the failed children;
#   any_of: the whole any_of if none passed).
