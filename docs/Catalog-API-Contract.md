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
  "requirements_parsed": true    // false = not yet parsed (treat null as UNKNOWN, not "no requirements")
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
  "coreqs": null
}
```