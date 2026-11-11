from app.schemas import CatalogResponse
FAKE_COURSES = {
    "CS3358": {
        "code": "CS3358",
        "title": "Data Structures and Algorithms",
        "prereqs": {
            "kind": "all_of",
            "children": [
                {"kind": "course", "code": "CS2308", "min_grade": "C"},
                {"kind": "course", "code": "MATH2358", "min_grade": "C"},
            ],
        },
        "coreqs": None,
    },
    "CS3360": {
        "code": "CS3360",
        "title": "Computing Systems Fundamentals",
        "prereqs": {
            "kind": "all_of",
            "children": [
                {"kind": "any_of", "children": [
                    {"kind": "course", "code": "CS2318", "min_grade": "C"},
                    {"kind": "course", "code": "CS2325", "min_grade": "C"},
                    {"kind": "course", "code": "EE3320", "min_grade": "C"},
                ]},
                {"kind": "course", "code": "CS3358", "min_grade": "C"},
            ],
        },
        "coreqs": None,
    },
    "CS2315": {
        "code": "CS2315",
        "title": "Computer Ethics",
        "prereqs": {
            "kind": "all_of",
            "children": [
                {"kind": "course", "code": "CS1428", "min_grade": "C"},
                {"kind": "any_of", "children": [
                    {"kind": "course", "code": "COMM1310", "min_grade": "C"},
                    {"kind": "course", "code": "COMM2338", "min_grade": "C"},
                ]},
                {"kind": "any_of", "children": [
                    {"kind": "course", "code": "ENG1310", "min_grade": "C"},
                    {"kind": "course", "code": "ENG1320", "min_grade": "C"},
                    {"kind": "course", "code": "ENG1321", "min_grade": "C"},
                    {"kind": "course", "code": "ENG3303", "min_grade": "C"},
                ]},
                {"kind": "any_of", "children": [
                    {"kind": "course", "code": "PHIL1305", "min_grade": "C"},
                    {"kind": "course", "code": "PHIL1320", "min_grade": "C"},
                ]},
            ],
        },
        "coreqs": None,
    },
    "CS1428": {
        "code": "CS1428",
        "title": "Foundations of Computer Science I",
        "prereqs": {
            "kind": "any_of",
            "children": [
                {"kind": "any_of", "children": [
                    {"kind": "course", "code": "MATH1315", "min_grade": "C"},
                    {"kind": "course", "code": "MATH1317", "min_grade": "C"},
                    {"kind": "course", "code": "MATH1319", "min_grade": "C"},
                    {"kind": "course", "code": "MATH1329", "min_grade": "C"},
                    {"kind": "course", "code": "MATH2417", "min_grade": "C"},
                    {"kind": "course", "code": "MATH2471", "min_grade": "C"},
                ]},
                {"kind": "manual", "requirements": "Math placement score: ACT Math 24+, New ACT Math 25+, SAT Math 520+, SAT Math Section 550+, Accuplacer College Math 86+, Compass College Algebra 46+, or Next-Generation Advanced Algebra and Functions 263+"},
            ],
        },
        "coreqs": None,
    },
}

def get_courses(codes):
    results = []
    for code in codes:
        if code in FAKE_COURSES:
            results.append(CatalogResponse.model_validate(FAKE_COURSES[code]))
    return results
