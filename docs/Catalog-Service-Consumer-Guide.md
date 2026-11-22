# Using the Catalog API from another service

The Catalog service is the supported way for other microservices to read course
data. A consumer sends an HTTP request to Catalog; Catalog queries PostgreSQL
and returns a JSON response. Consumer services should not connect to Catalog's
database directly or depend on its internal tables.

```text
Your microservice  -- HTTP -->  Catalog service  -- SQL -->  PostgreSQL
```

The API shape and field definitions are maintained in the
[Catalog API contract](./Catalog-API-Contract.md). The examples below show the
common integration path.

## 1. Find the Catalog service URL

- When your service runs on your development machine, use
  `http://localhost:8001`.
- When your service runs in the same Docker Compose network as Catalog, use
  `http://catalog-service:8001`. The Compose service name is the hostname; do
  not use `localhost` from inside another container.
- Configure the base URL per environment (for example with a `CATALOG_URL`
  environment variable) rather than hard-coding it in service logic.

Start the database and Catalog service from the repository root with:

```bash
docker compose up --build
```

Catalog's interactive API documentation is available at
[`http://localhost:8001/docs`](http://localhost:8001/docs) when running locally.
Use `/health` to check that the process is up and `/ready` to check that it can
reach the database.

## 2. Request course data

Use `GET /courses` with one repeated `codes` query parameter per course. A
request can contain 1–20 codes; codes must be uppercase and contain no spaces.

```bash
curl --get 'http://localhost:8001/courses' \
  --data-urlencode 'codes=CS3358' \
  --data-urlencode 'codes=CS1428'
```

The same request from a service in the Compose network is:

```bash
curl --get 'http://catalog-service:8001/courses' \
  --data-urlencode 'codes=CS3358' \
  --data-urlencode 'codes=CS1428'
```

Catalog returns a JSON array, with one object per known code. For example:

```json
[
  {
    "code": "CS3358",
    "title": "Data Structures and Algorithms",
    "prereqs": {
      "kind": "all_of",
      "children": [
        { "kind": "course", "code": "CS1428", "min_grade": "C" }
      ]
    },
    "coreqs": null,
    "requirements_parsed": true,
    "syllabus_documents": []
  }
]
```

The real response may include additional requirement nodes and syllabus
documents. Clients should ignore fields they do not need and should not assume
that a known course has a syllabus document.

## 3. Call it from a Python microservice

This standard-library example encodes repeated query parameters, applies a
timeout, and surfaces HTTP and connection errors to the caller:

```python
import json
import os
import urllib.error
import urllib.parse
import urllib.request

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:8001").rstrip("/")


def get_courses(codes: list[str]) -> list[dict]:
    if not codes:
        raise ValueError("Provide at least one course code.")

    courses = []
    for start in range(0, len(codes), 20):
        batch = codes[start : start + 20]
        query = urllib.parse.urlencode([("codes", code) for code in batch])
        url = f"{CATALOG_URL}/courses?{query}"

        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                courses.extend(json.load(response))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Catalog returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Catalog service is unreachable or timed out: {exc}") from exc

    return courses


courses = get_courses(["CS3358", "CS1428"])
courses_by_code = {course["code"]: course for course in courses}
```

For production code, use your service's existing HTTP-client conventions and
error mapping. Send no more than 20 codes per request; split larger sets into
batches. The Planner service's
[`CatalogClient`](../services/planner-service/app/clients/catalog.py) is an
existing example that batches requests and maps an unavailable Catalog service
to an upstream-service error.

## 4. Interpret the response correctly

- **Unknown code:** Catalog omits unknown codes from the array; it does not
  return a per-code 404. Compare requested codes with response `code` values if
  you need to identify missing ones.
- **Requirements not yet parsed:** `requirements_parsed: false` means
  prerequisite/corequisite data is unknown. Do not treat null `prereqs` or
  `coreqs` in this case as confirmation that the course has no requirements.
- **No requirements:** `requirements_parsed: true` with a null requirement
  field means that requirement is confirmed absent. `all_of` and `any_of`
  nodes always have at least one child.
- **Syllabus documents:** `syllabus_documents` is an array and can be empty.
  Syllabus-only courses may appear even without a canonical course record;
  their requirements are unparsed. The server-local `file_path` is never
  exposed by the API.
- **Validation and service errors:** an empty code list, more than 20 codes,
  lowercase codes, or codes containing spaces produce HTTP 422. A database
  connectivity problem produces HTTP 503. Handle non-success responses and
  timeouts explicitly instead of treating them as empty results.

Refer to the [full API contract](./Catalog-API-Contract.md) for all response
fields, including the syllabus-document schema and requirement-tree node types.
