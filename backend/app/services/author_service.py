import json
from pathlib import Path

from app.schemas.author import AuthorResponse

AUTHORS_FILE = Path(__file__).resolve().parent.parent / "mock_data" / "authors.json"


class AuthorDataError(Exception):
    """Raised when author mock data cannot be loaded or parsed."""


def load_authors() -> list[dict]:
    """Load authors from the mock JSON file with clear error handling."""
    if not AUTHORS_FILE.exists():
        raise AuthorDataError(f"Authors data file not found: {AUTHORS_FILE}")

    try:
        with AUTHORS_FILE.open(encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise AuthorDataError(
            f"Authors data file contains invalid JSON: {AUTHORS_FILE}"
        ) from exc
    except OSError as exc:
        raise AuthorDataError(
            f"Unable to read authors data file: {AUTHORS_FILE}"
        ) from exc

    if not isinstance(data, list):
        raise AuthorDataError("Authors data must be a JSON array")

    return data


def search_authors(query: str, limit: int = 10) -> list[AuthorResponse]:
    """
    Search authors by name, institution, department, or field.

    Matching is case-insensitive. Results are ranked as:
    1. Exact name matches
    2. Names that start with the query
    3. Other partial matches across searchable fields
    """
    cleaned_query = query.strip()
    if len(cleaned_query) < 2:
        return []

    normalized_query = cleaned_query.lower()
    authors = load_authors()

    exact_name: list[AuthorResponse] = []
    name_prefix: list[AuthorResponse] = []
    partial: list[AuthorResponse] = []
    seen_ids: set[str] = set()

    for raw in authors:
        author_id = str(raw.get("id", "")).strip()
        if not author_id or author_id in seen_ids:
            continue

        name = str(raw.get("name", ""))
        institution = str(raw.get("institution", ""))
        department = str(raw.get("department", ""))
        field = str(raw.get("field", ""))
        email = raw.get("email")
        email_value = str(email) if email is not None else None

        name_lower = name.lower()
        institution_lower = institution.lower()
        department_lower = department.lower()
        field_lower = field.lower()

        matches = (
            normalized_query in name_lower
            or normalized_query in institution_lower
            or normalized_query in department_lower
            or normalized_query in field_lower
        )
        if not matches:
            continue

        author = AuthorResponse(
            id=author_id,
            name=name,
            institution=institution,
            department=department,
            field=field,
            email=email_value,
        )
        seen_ids.add(author_id)

        if name_lower == normalized_query:
            exact_name.append(author)
        elif name_lower.startswith(normalized_query):
            name_prefix.append(author)
        else:
            partial.append(author)

    ranked = exact_name + name_prefix + partial
    return ranked[: max(limit, 0)]
