from fastapi.testclient import TestClient

from app.main import app
from app.services.author_service import search_authors

client = TestClient(app)


def test_search_alice_returns_both_alices():
    results = search_authors("alice")
    names = [author.name for author in results]

    assert "Alice Smith" in names
    assert "Alice Johnson" in names


def test_search_berkeley_finds_uc_berkeley_authors():
    results = search_authors("berkeley")

    assert len(results) >= 1
    assert all("berkeley" in author.institution.lower() for author in results)


def test_search_quantum_finds_matching_fields_or_departments():
    results = search_authors("quantum")

    assert len(results) >= 1
    assert all(
        "quantum" in author.field.lower() or "quantum" in author.department.lower()
        for author in results
    )


def test_search_david_lee_returns_both_records():
    results = search_authors("david lee")

    assert len(results) == 2
    assert all(author.name == "David Lee" for author in results)

    institutions = {author.institution for author in results}
    assert "UC Berkeley" in institutions
    assert "University of Chicago" in institutions


def test_search_is_case_insensitive():
    lower = search_authors("alice")
    upper = search_authors("ALICE")
    mixed = search_authors("AlIcE")

    assert [author.id for author in lower] == [author.id for author in upper]
    assert [author.id for author in lower] == [author.id for author in mixed]


def test_search_returns_no_exact_duplicate_records():
    results = search_authors("chen")
    ids = [author.id for author in results]

    assert len(ids) == len(set(ids))


def test_search_limit_is_respected():
    results = search_authors("quantum", limit=2)

    assert len(results) <= 2


def test_search_short_query_returns_empty_list():
    assert search_authors("") == []
    assert search_authors("a") == []
    assert search_authors(" ") == []


def test_api_authors_search_endpoint():
    response = client.get("/api/authors/search", params={"query": "alice"})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert {item["name"] for item in payload} >= {"Alice Smith", "Alice Johnson"}


def test_api_authors_search_respects_limit():
    response = client.get(
        "/api/authors/search",
        params={"query": "quantum", "limit": 1},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_api_authors_search_rejects_short_query():
    response = client.get("/api/authors/search", params={"query": "a"})

    assert response.status_code == 422
