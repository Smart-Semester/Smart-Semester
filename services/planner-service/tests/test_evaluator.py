from app.schemas import EligibilityRequest, CatalogResponse, CourseStatus
from app.services.evaluator import evaluate


def course(code, min_grade="C"):
    # Shortcut for a course node
    return {"kind": "course", "code": code, "min_grade": min_grade}


# Fake catalog, same JSON shape as the API contract.
FAKE_COURSES = {
    # a placement-score alternative is a manual node inside an any_of
    "CS1428": {
        "code": "CS1428", "title": "Foundations of Computer Science I",
        "prereqs": {"kind": "any_of", "children": [
            {"kind": "any_of", "children": [course("MATH1315"), course("MATH2471")]},
            {"kind": "manual", "requirements": "Math placement score"},
        ]},
        "coreqs": None,
    },
    # all_of containing an any_of
    "CS3360": {
        "code": "CS3360", "title": "Computing Systems Fundamentals",
        "prereqs": {"kind": "all_of", "children": [
            {"kind": "any_of", "children": [course("CS2318"), course("CS2325")]},
            course("CS3358"),
        ]},
        "coreqs": None,
    },
    # only a coreq
    "CS4000": {
        "code": "CS4000", "title": "Made-up Course",
        "prereqs": None, "coreqs": course("CS3358", "D"),
    },
    # no requirements at all
    "CS0001": {
        "code": "CS0001", "title": "No Requirements",
        "prereqs": None, "coreqs": None,
    },
}
CATALOG = [CatalogResponse.model_validate(c) for c in FAKE_COURSES.values()]


def run(planned, completed=()):
    """Run evaluate and return {code: status} so tests stay short."""
    request = EligibilityRequest(
        planned_codes=planned,
        completed_courses=[{"code": c, "grade": g} for c, g in completed],
    )
    response = evaluate(request, CATALOG)
    return {r.code: r.status for r in response.results}


def test_any_of_with_manual_node_and_no_math_course_cannot_verify():
    assert run(["CS1428"], [("ENG1310", "A")]) == {"CS1428": CourseStatus.CANNOT_VERIFY}


def test_any_of_with_one_course_satisfied_is_eligible():
    assert run(["CS1428"], [("MATH1315", "B")]) == {"CS1428": CourseStatus.ELIGIBLE}


def test_grade_below_minimum_is_not_eligible():
    done = [("CS2318", "D"), ("CS3358", "A")]
    assert run(["CS3360"], done) == {"CS3360": CourseStatus.NOT_ELIGIBLE}


def test_all_requirements_met_is_eligible():
    done = [("CS2325", "C"), ("CS3358", "B")]
    assert run(["CS3360"], done) == {"CS3360": CourseStatus.ELIGIBLE}


def test_failed_or_withdrawn_course_does_not_count():
    for grade in ("F", "W", "IP"):
        done = [("CS2318", grade), ("CS3358", "A")]
        assert run(["CS3360"], done) == {"CS3360": CourseStatus.NOT_ELIGIBLE}


def test_coreq_satisfied_by_planned_course():
    result = run(["CS4000", "CS3358"], [("ENG1310", "A")])
    assert result["CS4000"] == CourseStatus.ELIGIBLE


def test_coreq_not_planned_or_completed_is_not_eligible():
    assert run(["CS4000"], [("ENG1310", "A")]) == {"CS4000": CourseStatus.NOT_ELIGIBLE}


def test_coreq_satisfied_by_in_progress_course():
    assert run(["CS4000"], [("CS3358", "IP")]) == {"CS4000": CourseStatus.ELIGIBLE}


def test_planned_course_does_not_satisfy_a_prereq():
    # CS3358 planned, but CS3360 needs it as a PREREQ
    result = run(["CS3360", "CS3358"], [("CS2318", "A")])
    assert result["CS3360"] == CourseStatus.NOT_ELIGIBLE


def test_unknown_code():
    assert run(["ZZ9999"], [("ENG1310", "A")]) == {"ZZ9999": CourseStatus.UNKNOWN_COURSE}


def test_no_transcript_course_without_requirements_is_eligible():
    assert run(["CS0001"]) == {"CS0001": CourseStatus.ELIGIBLE}


def test_no_transcript_course_with_requirements_cannot_verify():
    assert run(["CS3360"]) == {"CS3360": CourseStatus.CANNOT_VERIFY}


def test_no_transcript_unknown_code():
    assert run(["ZZ9999"]) == {"ZZ9999": CourseStatus.UNKNOWN_COURSE}
