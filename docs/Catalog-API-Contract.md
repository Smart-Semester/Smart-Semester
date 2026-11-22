### API ENDPOINT
GET /courses?codes=CS3358&codes=ENG2254&codes=CS2254
- Codes are uppercase with no spaces. Max 20 per request; returns HTTP 422 (Unprocessable Entity) if there are no codes or more than 20.
- Returns a JSON array with one object per code. Unknown codes are just left out.
- Extra fields (credit hours etc.) are fine, the planner just ignores them.

### JSON STRUCTURE
> Note: my (Jonathan) implementation is already defined [here](../services/planner-service/app/schemas.py)

Each course:
```jsonc
{
  "code": "CS3358",
  "title": "Data Structures and Algorithms",
  "prereqs": <node or null>,
  "coreqs": <node or null>,      // null = no requirements, never an empty node
  "requirements_parsed": true,   // false = not yet parsed (treat null as UNKNOWN, not "no requirements")
  "syllabus_documents": [ ... ]  // list of SyllabusDocument objects; [] when none exist
}
```

The prereqs and coreqs are either a single root node (for a tree) or null. Each node in the tree has a "kind" which is either "course", "all_of", "any_of", "manual".
- courses have the "code", "min_grade" (which is between an A and a D)
- "all_of" has a "children" field which is a list of nodes, all of the nodes in "children" need to be satisfied.
- "any_of" has a "children" field which is a list of nodes, at least one node in "children" needs to be satisfied.
- "manual" is just for anything that doesn't fit neatly into any of the other requirements (consent, standing, etc.)

**Contract rules (decided Nov 2026):**
- `all_of` and `any_of` nodes MUST have at least one child. An empty `children` list is invalid. Use `null` at the `prereqs`/`coreqs` level to represent no requirements.
- `requirements_parsed: false` means the catalog parser has not yet processed this course's requirement text. The planner must treat this as "requirements unknown" and show a warning, NOT treat the null prereqs/coreqs as confirmed empty.
- `requirements_parsed: true` + `null` prereqs/coreqs means the course genuinely has no requirements.

### SYLLABUS DOCUMENTS

Each `syllabus_documents` item exposes the following fields (joined from
`catalog.syllabi → catalog.syllabus_documents`).  The server-local `file_path`
column is **never** returned.

```jsonc
{
  // from catalog.syllabus_documents
  "document_id":            "uuid-string",
  "source_url":             "https://...",
  "content_type":           "application/pdf",   // null if not yet determined
  "original_filename":      "syllabus.pdf",       // null if not yet determined
  "content_hash":           "sha256hex",          // null if not downloaded
  "file_size":              102400,               // bytes; null if not downloaded
  "download_status":        "DOWNLOADED",         // PENDING | DOWNLOADING | DOWNLOADED | FAILED | ...
  "extraction_status":      "EXTRACTED",          // PENDING | EXTRACTED | FAILED | MANUAL_REVIEW | ...
  "extracted_text":         "...",                // null if not extracted / manual review pending
  "page_count":             5,                    // null if not extracted
  "character_count":        2000,                 // null if not extracted
  "manual_review_required": false,
  "manual_review_reason":   null,                 // e.g. "SCANNED_DOCUMENT"
  "manual_review_notes":    null,                 // human-entered resolution notes
  "downloaded_at":          "2024-09-01T12:00:00Z",  // null if not yet downloaded
  "extracted_at":           "2024-09-01T12:01:00Z",  // null if not yet extracted

  // denormalised from catalog.syllabi (via syllabus_id join)
  "semester":               "Fall 2024",
  "semester_code":          "202410",
  "section":                "001",
  "instructor_name":        "Dr. Smith",          // null if not recorded
  "has_syllabus":           true
}
```

**Data-source rules:**
- Join path: `catalog.courses.course_code = catalog.syllabi.course_code`,
  then `catalog.syllabi.syllabus_id = catalog.syllabus_documents.syllabus_id`.
- For a **canonical course** (exists in `catalog.courses`) with no matching
  syllabus rows, `syllabus_documents` is `[]`.
- For a **syllabus-only course** (exists in `catalog.syllabi` but NOT in
  `catalog.courses`), the title comes from `catalog.syllabi.course_name`,
  `prereqs` and `coreqs` are `null`, and `requirements_parsed` is `false`.
- Codes matched by neither table are silently omitted (existing contract).

Example:
```json
{
  "code": "CS3358",
  "title": "Data Structures and Algorithms",
  "requirements_parsed": true,
  "prereqs": {
    "kind": "all_of",
    "children": [
      {"kind": "course", "code": "CS1428", "min_grade": "C"},
      {"kind": "course", "code": "CS2318", "min_grade": "C"},
      {"kind": "any_of", "children": [
        {"kind": "course", "code": "PHIL1305", "min_grade": "D"},
        {"kind": "course", "code": "COMM1315", "min_grade": "D"}
      ]}
    ]
  },
  "coreqs": null,
  "syllabus_documents": [
    {
      "document_id": "aaaaaaaa-0000-0000-0000-000000000001",
      "source_url": "https://hb2504.txst.edu/.../syllabus.pdf",
      "content_type": "application/pdf",
      "original_filename": "syllabus_CS3358_001.pdf",
      "content_hash": "e3b0c44298fc1c149afb",
      "file_size": 204800,
      "download_status": "DOWNLOADED",
      "extraction_status": "EXTRACTED",
      "extracted_text": "Course syllabus for CS3358...",
      "page_count": 8,
      "character_count": 4200,
      "manual_review_required": false,
      "manual_review_reason": null,
      "manual_review_notes": null,
      "downloaded_at": "2024-09-01T12:00:00Z",
      "extracted_at": "2024-09-01T12:01:00Z",
      "semester": "Fall 2024",
      "semester_code": "202410",
      "section": "001",
      "instructor_name": "Dr. Smith",
      "has_syllabus": true
    }
  ]
}
```
