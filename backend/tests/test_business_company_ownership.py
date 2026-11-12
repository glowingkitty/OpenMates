"""business.company_ownership: routing, privacy stripping, caching and register mapping.

All register responses are synthetic and served through ``httpx.MockTransport``;
no network is used.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest
import yaml

from backend.apps.business.skills.company_ownership import (
    CACHE_TTL_SECONDS,
    CompanyOwnershipSkill,
    parse_requests,
)
from backend.shared.app_packages import loader
from backend.shared.providers.company_registers import (
    CompaniesHouseClient,
    OpenRegisterClient,
    RechercheEntreprisesClient,
    RegisterProviderError,
    provider_api_key,
)
from backend.shared.providers.company_registers.models import PRIVATE_PERSON_FIELDS, ownership_record

PRIVATE_VALUES = ("1980-01-01", "1980-01", "1980", "Example Street 1", "Française", "British", "England", "Engineer")


def _client(routes: Dict[str, Any], seen: List[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        seen.append(key)
        value = routes.get(key)
        if value is None:
            return httpx.Response(404, json={})
        if callable(value):
            return value(request)
        return httpx.Response(200, json=value)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _assert_no_private_data(record: Dict[str, Any]) -> None:
    text = json.dumps(record)
    for value in PRIVATE_VALUES:
        assert value not in text, value
    for key in PRIVATE_PERSON_FIELDS:
        assert f'"{key}"' not in text, key


class FakeCache:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.ttls: List[int | None] = []

    async def get(self, key: str) -> Any:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.data[key] = value
        self.ttls.append(ttl)
        return True


class FakeRegister:
    provider_name = "Fake register"

    def __init__(self, record: Dict[str, Any] | None = None, error: RegisterProviderError | None = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.record = record
        self.error = error

    async def lookup(self, query: str, *, subject: str, include: List[str]) -> Dict[str, Any]:
        self.calls.append({"query": query, "subject": subject, "include": include})
        if self.error:
            raise self.error
        return self.record or {}


def _record(name: str, provider: str = "Fake register") -> Dict[str, Any]:
    return ownership_record(subject={"name": name, "type": "company", "country": "DE"}, provider=provider)


def _skill() -> CompanyOwnershipSkill:
    return object.__new__(CompanyOwnershipSkill)


# --- request validation -------------------------------------------------------

# contract-test: supporting surface=rest_api assertions=ownership.request
def test_parse_requests_defaults_and_normalizes():
    [item] = parse_requests([{"query": "  Example GmbH ", "country": "de", "include": ["officers", "owners", "owners"]}])
    assert item.query == "Example GmbH" and item.country == "DE" and item.subject == "company"
    assert item.include == ["owners", "officers"]
    assert parse_requests([{"query": "x", "country": "uk"}])[0].country == "GB"
    assert parse_requests([{"query": "x", "country": "FR"}])[0].include == ["owners"]


@pytest.mark.parametrize("requests", [
    None,
    [],
    [{"query": "x", "country": "DE"}] * 6,
    [{"query": "", "country": "DE"}],
    [{"query": "   ", "country": "DE"}],
    [{"query": "x" * 161, "country": "DE"}],
    [{"query": "x", "country": "Germany"}],
    [{"query": "x"}],
    [{"query": "x", "country": "DE", "include": ["revenue"]}],
    [{"query": "x", "country": "DE", "subject": "fund"}],
    [{"query": "x", "country": "DE", "extra": 1}],
])
# contract-test: supporting surface=rest_api assertions=ownership.request
def test_parse_requests_rejects_invalid(requests):
    with pytest.raises(ValueError):
        parse_requests(requests)


# --- skill routing, caching, errors -------------------------------------------

# contract-test: supporting surface=rest_api assertions=ownership.routing
@pytest.mark.anyio
async def test_routes_by_country_and_never_falls_back():
    german = FakeRegister(_record("Example GmbH", "OpenRegister"))
    french = FakeRegister(_record("Example SAS", "Annuaire des Entreprises"))
    response = await _skill().execute(
        requests=[{"id": 1, "query": "Example GmbH", "country": "DE"},
                  {"id": 2, "query": "Example SAS", "country": "FR", "include": ["officers"]},
                  {"id": 3, "query": "Example Inc", "country": "US"}],
        cache_service=FakeCache(),
        provider_clients={"openregister": german, "recherche_entreprises": french},
    )
    assert response.success is True and response.result_count == 2
    assert [r["id"] for r in response.records] == [1, 2]
    assert german.calls == [{"query": "Example GmbH", "subject": "company", "include": ["owners"]}]
    assert french.calls[0]["include"] == ["officers"]
    assert response.providers == ["OpenRegister", "Annuaire des Entreprises"]
    [gap] = response.errors
    assert gap["code"] == "coverage_gap" and gap["id"] == 3 and "US" in gap["message"]


# contract-test: supporting surface=rest_api assertions=ownership.routing
@pytest.mark.anyio
async def test_only_uncovered_country_returns_error():
    response = await _skill().execute(requests=[{"query": "Example Inc", "country": "US"}],
                                      cache_service=FakeCache(), provider_clients={"openregister": FakeRegister()})
    assert response.success is False and response.error_code == "coverage_gap" and response.records == []


# contract-test: supporting surface=rest_api assertions=ownership.budget
@pytest.mark.anyio
async def test_cache_hit_skips_the_register_call():
    cache = FakeCache()
    register = FakeRegister(_record("Example GmbH"))
    request = [{"query": "Example GmbH", "country": "DE", "include": ["owners"]}]
    first = await _skill().execute(requests=request, cache_service=cache, provider_clients={"openregister": register})
    second = await _skill().execute(requests=[{"query": "example gmbh", "country": "de"}], cache_service=cache,
                                    provider_clients={"openregister": register})
    assert first.success and second.success and len(register.calls) == 1
    assert cache.ttls == [CACHE_TTL_SECONDS] and CACHE_TTL_SECONDS == 7 * 24 * 3600
    third = await _skill().execute(requests=[{**request[0], "include": ["owners", "officers"]}], cache_service=cache,
                                   provider_clients={"openregister": register})
    assert third.success and len(register.calls) == 2


# contract-test: supporting surface=rest_api assertions=ownership.budget,ownership.results
@pytest.mark.anyio
async def test_errors_are_not_cached_and_carry_candidates():
    cache = FakeCache()
    candidates = [{"name": "Example GmbH", "register_id": "HRB 1"}, {"name": "Example AG", "register_id": "HRB 2"}]
    register = FakeRegister(error=RegisterProviderError("ambiguous", "Several match", candidates=candidates))
    response = await _skill().execute(requests=[{"query": "Example", "country": "DE"}], cache_service=cache,
                                      provider_clients={"openregister": register})
    assert response.success is False and response.error_code == "ambiguous"
    assert response.errors[0]["candidates"] == candidates and cache.data == {}


# contract-test: supporting surface=rest_api assertions=ownership.unconfigured
@pytest.mark.anyio
async def test_keyed_register_without_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("SECRET__OPENREGISTER__API_KEY", raising=False)

    class NoSecrets:
        async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True):
            assert secret_path == "kv/data/providers/openregister" and secret_key == "api_key"
            return None

    response = await _skill().execute(requests=[{"query": "Example GmbH", "country": "DE"}],
                                      secrets_manager=NoSecrets(), cache_service=FakeCache())
    assert response.success is False and response.error_code == "provider_not_configured"


# contract-test: supporting surface=rest_api assertions=ownership.unconfigured
@pytest.mark.anyio
async def test_provider_api_key_reads_vault_then_env(monkeypatch):
    class Secrets:
        def __init__(self, value):
            self.value = value

        async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True):
            return self.value

    monkeypatch.setenv("SECRET__COMPANIES__HOUSE__API_KEY", " env-key ")
    assert await provider_api_key("companies_house", Secrets("'vault-key'")) == "vault-key"
    assert await provider_api_key("companies_house", Secrets(None)) == "env-key"
    assert await provider_api_key("companies_house", None) == "env-key"


# contract-test: supporting surface=rest_api assertions=ownership.privacy
def test_ownership_record_refuses_private_fields():
    with pytest.raises(RegisterProviderError):
        ownership_record(subject={"name": "x"}, provider="p", owners=[{"name": "y", "date_of_birth": "1980"}])


# contract-test: supporting surface=rest_api assertions=ownership.routing
def test_app_yml_declares_the_three_registers():
    config = yaml.safe_load((loader.BUILTIN_APPS_DIR / "business" / "app.yml").read_text(encoding="utf-8"))
    skill = next(item for item in config["skills"] if item["id"] == "company_ownership")
    assert [p["name"] for p in skill["providers"]] == ["openregister", "companies_house", "recherche_entreprises"]
    assert skill["providers"][2]["no_api_key"] is True
    assert skill["tool_schema"]["properties"]["requests"]["maxItems"] == 5
    assert any(e["id"] == "company_ownership" for e in config["embed_types"])


# --- German register mapping --------------------------------------------------

DE_MATCH = {"company_id": "DE-HRB-X1-1", "name": "Example Robotics GmbH", "register_number": "1",
            "register_type": "HRB", "register_court": "Berlin (Charlottenburg)", "active": True,
            "legal_form": "gmbh", "address": {"city": "Berlin", "street": "Example Street 1"}}
DE_OWNERS = {"owners": [
    {"id": "p1", "type": "natural_person", "relation_type": "shareholder", "name": "Jane Example",
     "natural_person": {"full_name": "Jane Example", "date_of_birth": "1980-01-01", "city": "Berlin", "country": "DE"},
     "nominal_share": 12500, "percentage_share": 50, "start": "2020-01-01"},
    {"id": "DE-HRB-X1-2", "type": "legal_person", "relation_type": "shareholder", "name": "Example Holding GmbH",
     "legal_person": {"name": "Example Holding GmbH", "city": "Munich", "country": "DE"},
     "nominal_share": 12500, "percentage_share": 50, "start": "2021-05-01"}],
    "sources": [{"document_url": "https://example.org/doc"}]}
DE_DETAIL = {"representation": [
    {"name": "Jane Example", "type": "natural_person", "role": "DIRECTOR",
     "role_detail": {"label_en": "Managing director"}, "start_date": "2020-01-01", "end_date": None,
     "natural_person": {"date_of_birth": "1980-01-01", "city": "Berlin"}},
    {"name": "Old Director", "type": "natural_person", "role": "DIRECTOR", "role_detail": {},
     "start_date": "2018-01-01", "end_date": "2019-12-31"}]}


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_openregister_company_maps_owners_and_officers_without_private_data():
    seen: List[str] = []
    routes = {"GET /v1/autocomplete/company": {"results": [DE_MATCH, {**DE_MATCH, "name": "Example Robotics Two GmbH"}]},
              "GET /v1/company/DE-HRB-X1-1/owners": DE_OWNERS,
              "GET /v1/company/DE-HRB-X1-1": DE_DETAIL}
    client = OpenRegisterClient("key", http_client=_client(routes, seen))
    record = await client.lookup("Example Robotics GmbH", subject="company", include=["owners", "officers"])
    assert seen == ["GET /v1/autocomplete/company", "GET /v1/company/DE-HRB-X1-1/owners", "GET /v1/company/DE-HRB-X1-1"]
    assert record["subject"]["register_id"] == "HRB 1, Berlin (Charlottenburg)" and record["subject"]["city"] == "Berlin"
    assert [(o["name"], o["type"], o["share_percent"]) for o in record["owners"]] == [
        ("Jane Example", "person", 50.0), ("Example Holding GmbH", "company", 50.0)]
    assert record["owners"][1]["register_id"] == "DE-HRB-X1-2" and record["owners"][0]["register_id"] is None
    assert record["officers"] == [{"name": "Jane Example", "type": "person", "role": "Managing director", "since": "2020-01-01"}]
    _assert_no_private_data(record)


# contract-test: supporting surface=rest_api assertions=ownership.budget
@pytest.mark.anyio
async def test_openregister_only_calls_what_include_needs():
    seen: List[str] = []
    routes = {"GET /v1/autocomplete/company": {"results": [DE_MATCH]}}
    record = await OpenRegisterClient("key", http_client=_client(routes, seen)).lookup(
        "Example", subject="company", include=["owners"])
    assert seen == ["GET /v1/autocomplete/company", "GET /v1/company/DE-HRB-X1-1/owners"]
    assert record["owners"] == [] and record["warnings"]


# contract-test: supporting surface=rest_api assertions=ownership.results
@pytest.mark.anyio
async def test_openregister_ambiguous_candidates_and_not_found():
    seen: List[str] = []
    other = {**DE_MATCH, "company_id": "DE-HRB-X1-9", "name": "Example Robotics Two GmbH"}
    client = OpenRegisterClient("key", http_client=_client({"GET /v1/autocomplete/company": {"results": [DE_MATCH, other]}}, seen))
    with pytest.raises(RegisterProviderError) as caught:
        await client.lookup("Example", subject="company", include=["owners"])
    assert caught.value.code == "ambiguous" and len(caught.value.candidates) == 2
    assert "street" not in json.dumps(caught.value.candidates).lower()
    empty = OpenRegisterClient("key", http_client=_client({"GET /v1/autocomplete/company": {"results": []}}, []))
    with pytest.raises(RegisterProviderError) as missing:
        await empty.lookup("Nothing", subject="company", include=["owners"])
    assert missing.value.code == "not_found"


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_openregister_person_holdings_and_positions():
    seen: List[str] = []
    routes = {
        "POST /v1/search/person": {"results": [{"id": "u1", "name": "Jane Example", "city": "Berlin",
                                                "date_of_birth": "1980-01-01", "active": True}]},
        "GET /v1/person/u1/holdings": {"holdings": [
            {"company_id": "DE-HRB-X1-1", "relation_type": "shareholder", "name": "Example Robotics GmbH",
             "percentage_share": 50, "start": "2020-01-01", "end": None},
            {"company_id": "DE-HRB-X1-3", "relation_type": "shareholder", "name": "Example Past GmbH",
             "percentage_share": 10, "start": "2015-01-01", "end": "2019-01-01"}]},
        "GET /v1/person/u1": {"first_name": "Jane", "last_name": "Example", "date_of_birth": "1980-01-01", "age": 46,
                              "management_positions": [{"register_id": "DE-HRB-X1-1", "company_name": "Example Robotics GmbH",
                                                        "role": "DIRECTOR", "role_detail": {"label_en": "Managing director"},
                                                        "start_date": "2020-01-01", "end_date": None}]},
    }
    record = await OpenRegisterClient("key", http_client=_client(routes, seen)).lookup(
        "Jane Example", subject="person", include=["holdings", "officers"])
    assert record["subject"] == {"name": "Jane Example", "type": "person", "country": "DE", "register_id": None,
                                 "legal_form": None, "status": None, "city": "Berlin", "source_url": None}
    assert [(h["name"], h["status"]) for h in record["holdings"]] == [
        ("Example Robotics GmbH", "current"), ("Example Past GmbH", "ended"), ("Example Robotics GmbH", "current")]
    assert record["holdings"][2]["relation"] == "Managing director"
    _assert_no_private_data(record)


# contract-test: supporting surface=rest_api assertions=ownership.unconfigured
@pytest.mark.anyio
@pytest.mark.parametrize(("status", "code"), [(401, "provider_not_configured"), (402, "rate_limited"),
                                              (429, "rate_limited"), (500, "provider_error"), (400, "provider_error")])
async def test_openregister_http_errors_map_to_codes(status, code, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("backend.shared.providers.company_registers.http.asyncio.sleep", no_sleep)
    seen: List[str] = []
    routes = {"GET /v1/autocomplete/company": lambda _r: httpx.Response(status, json={})}
    with pytest.raises(RegisterProviderError) as caught:
        await OpenRegisterClient("key", http_client=_client(routes, seen)).lookup("x", subject="company", include=["owners"])
    assert caught.value.code == code
    assert len(seen) == (3 if status in (429, 500) else 1)


# contract-test: supporting surface=rest_api assertions=ownership.unconfigured
def test_keyed_clients_require_a_key():
    for factory in (OpenRegisterClient, CompaniesHouseClient):
        with pytest.raises(RegisterProviderError) as caught:
            factory("")
        assert caught.value.code == "provider_not_configured"


# --- UK register mapping ------------------------------------------------------

UK_PSC = {"items": [
    {"name": "Ms Jane Example", "kind": "individual-person-with-significant-control",
     "natures_of_control": ["ownership-of-shares-50-to-75-percent", "voting-rights-50-to-75-percent"],
     "notified_on": "2020-02-02", "date_of_birth": {"month": 1, "year": 1980}, "nationality": "British",
     "country_of_residence": "England", "address": {"address_line_1": "Example Street 1"}},
    {"name": "Example Holdings Ltd", "kind": "corporate-entity-person-with-significant-control",
     "natures_of_control": ["ownership-of-shares-25-to-50-percent"], "notified_on": "2021-01-01",
     "identification": {"registration_number": "87654321"}},
    {"name": "Former Owner", "kind": "individual-person-with-significant-control", "ceased_on": "2019-01-01",
     "natures_of_control": ["ownership-of-shares-75-to-100-percent"]}]}
UK_OFFICERS = {"items": [
    {"name": "EXAMPLE, Jane", "officer_role": "director", "appointed_on": "2020-02-02",
     "date_of_birth": {"month": 1, "year": 1980}, "occupation": "Engineer", "nationality": "British"},
    {"name": "GONE, Old", "officer_role": "secretary", "appointed_on": "2010-01-01", "resigned_on": "2015-01-01"}]}


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_companies_house_company_by_number_maps_bands_and_officers():
    seen: List[str] = []
    routes = {"GET /company/12345678": {"company_name": "EXAMPLE ROBOTICS LTD", "company_status": "active", "type": "ltd",
                                        "registered_office_address": {"locality": "London", "address_line_1": "Example Street 1"}},
              "GET /company/12345678/persons-with-significant-control": UK_PSC,
              "GET /company/12345678/officers": UK_OFFICERS}
    record = await CompaniesHouseClient("key", http_client=_client(routes, seen)).lookup(
        "12345678", subject="company", include=["owners", "holdings", "officers"])
    assert seen == ["GET /company/12345678", "GET /company/12345678/persons-with-significant-control",
                    "GET /company/12345678/officers"]
    assert record["subject"]["source_url"].endswith("/company/12345678") and record["subject"]["city"] == "London"
    assert [(o["name"], o["share_band"], o["type"]) for o in record["owners"]] == [
        ("Ms Jane Example", "50-75%", "person"), ("Example Holdings Ltd", "25-50%", "company")]
    assert record["owners"][1]["register_id"] == "87654321"
    assert [o["name"] for o in record["officers"]] == ["EXAMPLE, Jane"]
    assert any("does not list" in w for w in record["warnings"])
    _assert_no_private_data(record)


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_companies_house_search_and_person_appointments():
    seen: List[str] = []
    routes = {"GET /search/companies": {"items": [{"company_number": "12345678", "title": "EXAMPLE ROBOTICS LTD",
                                                   "company_status": "active", "address": {"locality": "London"}}]},
              "GET /company/12345678/persons-with-significant-control": {"items": []},
              "GET /search/officers": {"items": [{"title": "Jane EXAMPLE", "links": {"self": "/officers/abc/appointments"},
                                                  "address_snippet": "Example Street 1", "date_of_birth": {"year": 1980}}]},
              "GET /officers/abc/appointments": {"items": [
                  {"appointed_to": {"company_name": "EXAMPLE ROBOTICS LTD", "company_number": "12345678",
                                    "company_status": "active"}, "officer_role": "director", "appointed_on": "2020-02-02"}]}}
    client = CompaniesHouseClient("key", http_client=_client(routes, seen))
    company = await client.lookup("Example Robotics", subject="company", include=["owners"])
    assert company["owners"] == [] and company["warnings"]
    person = await client.lookup("Jane Example", subject="person", include=["holdings"])
    assert person["holdings"][0]["relation"] == "director" and person["holdings"][0]["register_id"] == "12345678"
    _assert_no_private_data(person)


# --- French register mapping --------------------------------------------------

FR_RESULT = {"siren": "123456789", "nom_complet": "EXAMPLE ROBOTIQUE", "nature_juridique": "5710",
             "etat_administratif": "A", "siege": {"libelle_commune": "PARIS", "adresse": "1 EXAMPLE STREET 1"},
             "dirigeants": [
                 {"nom": "EXAMPLE", "prenoms": "JANE MARIE", "annee_de_naissance": "1980", "date_de_naissance": "1980-01",
                  "qualite": "Président de SAS", "nationalite": "Française", "type_dirigeant": "personne physique"},
                 {"siren": "987654321", "denomination": "EXAMPLE HOLDING", "qualite": "Directeur Général",
                  "type_dirigeant": "personne morale"}]}


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_recherche_entreprises_company_maps_directors_without_birth_data():
    seen: List[str] = []
    client = RechercheEntreprisesClient(http_client=_client({"GET /search": {"results": [FR_RESULT]}}, seen))
    record = await client.lookup("Example Robotique", subject="company", include=["owners", "officers"])
    assert record["subject"]["legal_form"] == "SAS" and record["subject"]["register_id"] == "SIREN 123456789"
    assert record["subject"]["source_url"] == "https://annuaire-entreprises.data.gouv.fr/entreprise/123456789"
    assert record["officers"] == [
        {"name": "Jane Example", "type": "person", "role": "Président de SAS", "since": None},
        {"name": "EXAMPLE HOLDING", "type": "company", "role": "Directeur Général", "since": None}]
    assert record["owners"] == [] and any("not published" in w for w in record["warnings"])
    _assert_no_private_data(record)


# contract-test: supporting surface=rest_api assertions=ownership.privacy,ownership.results
@pytest.mark.anyio
async def test_recherche_entreprises_person_retries_swapped_name_order():
    calls: List[Dict[str, str]] = []

    def search(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        found = params.get("nom_personne") == "EXAMPLE"
        return httpx.Response(200, json={"results": [FR_RESULT] if found else []})

    client = RechercheEntreprisesClient(http_client=_client({"GET /search": search}, []))
    record = await client.lookup("EXAMPLE Jane", subject="person", include=["holdings"])
    assert [c["nom_personne"] for c in calls] == ["Jane", "EXAMPLE"]
    assert record["holdings"][0]["name"] == "EXAMPLE ROBOTIQUE" and record["holdings"][0]["relation"] == "Président de SAS"
    _assert_no_private_data(record)


# contract-test: supporting surface=rest_api assertions=ownership.results
@pytest.mark.anyio
async def test_recherche_entreprises_picks_by_siren_or_raises_ambiguous():
    other = {**FR_RESULT, "siren": "111111111", "nom_complet": "EXAMPLE ROBOTIQUE BIS"}
    client = RechercheEntreprisesClient(http_client=_client({"GET /search": {"results": [other, FR_RESULT]}}, []))
    record = await client.lookup("123 456 789", subject="company", include=["officers"])
    assert record["subject"]["register_id"] == "SIREN 123456789"
    with pytest.raises(RegisterProviderError) as caught:
        await client.lookup("Example", subject="company", include=["officers"])
    assert caught.value.code == "ambiguous" and len(caught.value.candidates) == 2
