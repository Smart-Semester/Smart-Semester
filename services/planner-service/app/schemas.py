from pydantic import BaseModel, Field
from typing import List, Union, Literal, Annotated
from enum import Enum

# eligibility request and result are in there completed form
# elibility response is temporary and depends on the catalogs implementation
# hopefully we can just use this one anyways

# defines eligibility requests (JSON structure for what courses need to be checked)
class CompletedCourse(BaseModel):
    code: str
    grade: Literal["A", "B", "C", "D", "F", "IP", "W"]

class EligibilityRequest(BaseModel):
    planned_codes: List[str]
    completed_courses: List[CompletedCourse] = Field(default_factory=list) 

# JSON example for a catalog response
# this is not final and is dependent on the catalog service
# implementation
# {
#   "code": "CS3358",
#   "title": "Data Structures and Algorithms",
#   "prereqs": {
#     "kind": "all_of",
#     "children": [
#       { "kind": "course", "code": "CS1428", "min_grade": "C" },
#       { "kind": "course", "code": "CS2318", "min_grade": "C" },
#       {
#         "kind": "any_of",
#         "children": [
#           { "kind": "course", "code": "PHIL1305", "min_grade": "D" },
#           { "kind": "course", "code": "COMM1315", "min_grade": "D" }
#         ]
#       }
#     ]
#   },
#   "coreqs": null
# }

# defines a (temporary) structure for the catalog response
class CourseNode(BaseModel):
    kind: Literal["course"] = "course"  
    code: str
    min_grade: Literal["A", "B", "C", "D"] 

class AllOfNode(BaseModel):
    kind: Literal["all_of"] = "all_of"
    children: List["RequirementNode"] = Field(default_factory=list)

class AnyOfNode(BaseModel):
    kind: Literal["any_of"] = "any_of"
    children: List["RequirementNode"] = Field(default_factory=list)

class ManualNode(BaseModel):
    kind: Literal["manual"] = "manual"
    requirements: str

# builds a tree structure that can uses the above nodes to define prereqs/coreqs
RequirementNode = Annotated[Union[CourseNode, AllOfNode, AnyOfNode, ManualNode], Field(discriminator="kind")]
# rebuilds now that RequirementNode is defined
AllOfNode.model_rebuild()
AnyOfNode.model_rebuild()

class CatalogResponse(BaseModel):
    code: str
    title: str
    prereqs: RequirementNode | None = None
    coreqs: RequirementNode | None = None

# defines the response to an eligibility check
class CourseStatus(str, Enum):
    ELIGIBLE = 'eligible'
    NOT_ELIGIBLE = 'not_eligible'
    CANNOT_VERIFY = 'cannot_verify'
    UNKNOWN_COURSE = 'unknown_course'

class CourseResponse(BaseModel):
    status: CourseStatus
    status_description: str | None = None # used to explain cannot_verify errors
    code: str
    unmet_prereqs: RequirementNode | None = None
    unmet_coreqs: RequirementNode | None = None

class EligibilityResponse(BaseModel):
    results: List[CourseResponse] = Field(default_factory=list) 
