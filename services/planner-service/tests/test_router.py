from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_eligible_course():
    body = {
        "planned_codes": ["CS1428"],
        "completed_courses": [{"code": "MATH1315", "grade": "B"}],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "eligible"

def test_eligible_course_with_whitespace():
    body = {
        "planned_codes": ["CS   1428"],
        "completed_courses": [{"code": "MATH1315", "grade": "B"}],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "eligible"

def test_lowercase_grade():
    body = {
        "planned_codes": ["CS1428"],
        "completed_courses": [{"code": "MATH1315", "grade": "b"}],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 422

def test_missing_prereqs():
    body = {
        "planned_codes": ["CS1428"],
        "completed_courses": [],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "cannot_verify"

def test_bad_grade():
    body = {
        "planned_codes": ["CS3360"],
        "completed_courses": [{"code": "CS2318", "grade": "D"}, {"code": "CS3358", "grade": "A"}],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "not_eligible"

def test_unknown_course():
    body = {
        "planned_codes": ["CS3361"],
        "completed_courses": [{"code": "CS2325", "grade": "B"}],
    }
    response = client.post("/eligibility-checks", json=body)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "unknown_course"
