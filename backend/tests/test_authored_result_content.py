"""Pure authored-result contracts; no provider, account, or network access."""

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from backend.apps.ai.utils.authored_result_fences import (
    get_authored_results_schema,
    get_authoring_definitions,
    is_authored_results_fence,
    normalize_authored_results_source,
)

# Representative supplied facts, also available for subsequent transport/UI
# fixtures. They describe resources; tests do not assert resource availability.
VALID_KIND_DETAILS = {
    "events.event": {
        "date_start": "2027-01-30", "date_end": "2027-01-31", "timezone": "Europe/Brussels",
        "venue": {"name": "ULB", "city": "Brussels", "lat": 50.813, "lon": 4.382},
        "organizer": {"name": "Community organizers"}, "fee": {"amount": 0, "currency": "EUR"},
        "url": "https://example.org/conference", "image_url": "https://example.org/conference.jpg",
    },
    "home.listing": {
        "price_label": "EUR 1,400 / month", "size_sqm": 62, "rooms": 2,
        "city": "Berlin", "location_precision": "approximate", "location_approximate": True,
        "location_area": {"name": "Moabit", "lat": 52.532, "lon": 13.34, "radius_m": 500},
        "rent_components": {"base_rent": 1200, "utilities": 200, "currency": "EUR", "period": "month"},
        "available_from": "2027-02-01", "amenities": ["Balcony"],
    },
    "health.appointment": {
        "doctor_name": "Dr Example", "speciality": "Dermatology", "telehealth": True,
        "slot_datetime": "2027-02-01T09:00:00+01:00", "timezone": "Europe/Berlin",
        "insurance": "User-supplied coverage statement", "booking_url": "https://example.org/clinic",
    },
    "travel.connection": {
        "origin": {"name": "Berlin Hbf", "lat": 52.525, "lon": 13.369},
        "destination": {"name": "Brussels Midi", "lat": 50.836, "lon": 4.336},
        "departure": "2027-01-29T07:00:00+01:00", "arrival": "2027-01-29T14:00:00+01:00",
        "transport_method": "train", "price": 120, "currency": "EUR",
        "legs": [{"origin": "Berlin Hbf", "destination": "Cologne Hbf", "departure": "2027-01-29T07:00:00+01:00", "arrival": "2027-01-29T11:00:00+01:00"}],
    },
    "travel.stay": {
        "name": "Example guesthouse", "check_in": "2027-01-29", "check_out": "2027-02-01",
        "currency": "EUR", "rate_per_night": {"amount": 90}, "amenities": ["Wi-Fi"],
    },
    "maps.place": {"display_name": "Example cafe", "coordinates": {"lat": 50.85, "lon": 4.35}, "category": "cafe"},
    "fitness.location": {"name": "Example studio", "city": "Brussels", "disciplines": ["Yoga"]},
    "fitness.class": {"name": "Morning yoga", "date": "2027-01-30", "time_range": "08:00–09:00", "venue_name": "Example studio", "spots_left": 3},
    "shopping.product": {"title": "Example kettle", "brand": "Example", "price_cents": 2499, "currency_symbol": "€", "specifications": [{"name": "Capacity", "value": "1.5 L"}]},
    "jobs.job_result": {"title": "Software engineer", "company": "Example", "remote": True, "work_arrangement": "Remote", "salary": {"min": 60000, "max": 80000, "currency": "EUR", "basis": "annual"}},
    "nutrition.recipe": {"title": "Lentil soup", "servings": 2, "total_time_minutes": 30, "ingredients": [{"name": "Red lentils", "amount": 150, "unit": "g"}], "instructions": ["Rinse lentils.", "Simmer until tender."]},
    "code.repo": {"url": "https://github.com/example/project", "full_name": "example/project", "primary_language": "Rust", "license_spdx_id": "MIT", "stars": 42},
    "web.website": {"url": "https://example.org/reference", "description": "Reference supplied by the user."},
    "news.website": {"url": "https://example.org/news", "published_at": "2026-10-26T10:00:00Z", "description": "Dated announcement."},
    "electronics.component": {"title": "Example buck regulator", "part_number": "EX123", "topology": "Buck", "efficiency_percent": 92, "bom_count": 8},
    "business.company_financial_result": {"company": "Example plc", "fiscal_year": 2025, "period_type": "annual", "currency": "EUR", "revenue": 2000000, "net_income": -20000, "filed": "2026-03-01"},
    "weather.weather_day": {"date": "2026-10-27", "location_name": "Brussels", "temperature_min_c": 8, "temperature_max_c": 14, "hourly": [{"time": "09:00", "temperature_c": 10}]},
    "hosting.hosting_domain": {"domain_ascii": "example.org", "availability": "registered", "checked_at": "2026-10-26T10:00:00Z", "registration_tiers": [{"years": 1, "price": 12, "currency": "EUR"}]},
    "social_media.social_post": {"body": "A user-supplied post.", "platform": "Mastodon", "published_at": "2026-10-25T12:00:00Z", "likes_count": 3},
    "design.icon_result": {"icon_id": "mdi:calendar", "prefix": "mdi", "name": "calendar", "license_spdx": "Apache-2.0"},
    "images.image_result": {"image_url": "https://example.org/real-image.jpg", "thumbnail_url": "https://example.org/thumb.jpg", "attribution": "Photographer supplied by user"},
    "videos.video": {"url": "https://example.org/video", "video_id": "supplied-video", "channel": "Example", "duration_seconds": 120},
    "models3d.model_result": {"source_page_url": "https://example.org/model", "provider": "User source", "creator_name": "Example", "license": "CC BY 4.0", "files_count": 2},
    "tv.movie": {
        "synopsis": "A supplied film synopsis.", "release_date": "2026-09-15", "year": 2026,
        "runtime_minutes": 112, "genres": ["Drama"], "directors": ["Example Director"],
        "cast": ["Example Actor"], "original_language": "en", "country_codes": ["GB"],
        "content_rating": "12A", "poster_url": "https://example.org/movie-poster.jpg",
        "source_url": "https://example.org/movie",
        "score": {"value": 8.2, "scale": 10, "source_url": "https://example.org/movie-score", "source_label": "Supplied score", "votes": 1200, "observed_at": "2026-10-26T10:00:00Z"},
    },
    "tv.series": {
        "synopsis": "A supplied series synopsis.", "first_air_date": "2023-03-01", "start_year": 2023,
        "last_air_date": "2026-10-01", "end_year": 2026, "series_status": "Ended",
        "genres": ["Comedy"], "creators": ["Example Creator"], "cast": ["Example Actor"],
        "original_language": "en", "content_rating": "TV-14", "episode_runtime_minutes": 25,
        "season_count": 4, "episode_count": 30, "poster_url": "https://example.org/series-poster.jpg",
        "source_url": "https://example.org/series",
        "seasons": [
            {"season_number": 0, "title": "Specials", "episode_count": 2},
            {"season_number": 1, "title": "Season one", "synopsis": "Supplied first-season synopsis.", "first_air_date": "2023-03-01", "episode_count": 8, "poster_url": "https://example.org/season-one.jpg"},
        ],
    },
}


def valid_authored_item(kind="events.event", local_id="one", *, origin="user_provided"):
    """Build an isolated eligible fixture without sharing mutable test state."""
    return {
        "id": local_id, "kind": kind, "title": "Supplied " + kind,
        "origin": origin, "details": copy.deepcopy(VALID_KIND_DETAILS[kind]),
        "sources": [{"url": "https://example.org/reference", "label": "User-supplied reference"}],
        "observed_at": "2026-10-26T10:00:00Z",
    }


def normalize(items, **envelope):
    return normalize_authored_results_source(json.dumps({"schemaVersion": 1, "items": items, **envelope}))


@pytest.mark.parametrize("kind", VALID_KIND_DETAILS)
# contract-test: supporting surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
def test_every_eligible_kind_preserves_real_fields_and_provenance(kind):
    supplied = valid_authored_item(kind)
    result = normalize([supplied])
    assert result.status == "valid", result.warnings
    item = result.items[0]
    assert item.local_id == "one" and item.kind == kind
    assert item.app_id == kind.split(".")[0]
    assert item.backend_type == get_authoring_definitions()[kind]["backend_type"]
    for key, value in supplied["details"].items():
        if key != "title":
            assert item.content[key] == value
    assert item.content["authoring"] == {
        "schema_version": 1, "kind": kind, "origin": "user_provided",
        "sources": supplied["sources"], "observed_at": supplied["observed_at"],
    }
    assert normalize_authored_results_source(result.source_json) == result


# contract-test: supporting surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.creation.relevant-and-independent
def test_catalog_matches_explicit_app_admissions_and_specification_inventory():
    root = Path(__file__).resolve().parents[2]
    specification = yaml.safe_load((root / "specifications/features/assistant-authored-result-embeds/specification.yml").read_text())
    base_inventory = set(specification["eligibility"]["informational_records"] + specification["eligibility"]["real_asset_records"])
    assert len(base_inventory) == 23
    tv_specification = yaml.safe_load((root / "specifications/features/tv-title-embeds/specification.yml").read_text())
    assert tv_specification["id"] == "feature.tv-title-embeds"
    assert {"Movie", "Series"} <= set(tv_specification["models"])
    expected = base_inventory | {"tv.movie", "tv.series"}
    definitions = get_authoring_definitions()
    assert set(definitions) == expected == set(VALID_KIND_DETAILS)
    assert len(definitions) == 25
    admissions = []
    for path in (root / "backend/apps").glob("*/app.yml"):
        app = yaml.safe_load(path.read_text())
        for embed in app.get("embed_types", []):
            if "authoring" in embed:
                metadata = embed["authoring"]
                kind = metadata["kind"]
                assert kind in definitions and metadata["schema_id"] == definitions[kind]["schema_id"]
                assert path.parent.name == definitions[kind]["app_id"]
                admissions.append(kind)
    assert sorted(admissions) == sorted(expected)


# contract-test: supporting surface=rest_api assertions=authored-results.creation.relevant-and-independent,authored-results.eligibility.all-suitable-results
def test_selected_schema_context_excludes_unrelated_kinds_and_deduplicates_shared_details():
    Draft202012Validator.check_schema(get_authored_results_schema())
    schema = get_authored_results_schema(["web.website", "news.website", "web.website"])
    Draft202012Validator.check_schema(schema)
    assert len(schema["properties"]["items"]["items"]["oneOf"]) == 2
    assert "website" in schema["$defs"] and "event" not in schema["$defs"]
    assert Draft202012Validator(schema).is_valid({"schemaVersion": 1, "items": [valid_authored_item("web.website")]})
    assert not Draft202012Validator(schema).is_valid({"schemaVersion": 1, "items": [valid_authored_item()]})
    assert get_authored_results_schema([])["properties"]["items"]["items"] is False
    definitions = get_authoring_definitions()
    definitions["events.event"]["backend_type"] = "fake"
    assert get_authoring_definitions()["events.event"]["backend_type"] == "event"
    with pytest.raises(ValueError, match="Unknown authored result kind"):
        get_authored_results_schema(["ai.app_skill_use"])


# contract-test: supporting surface=rest_api assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
def test_unknown_numeric_facts_are_absent_and_zero_is_preserved():
    entries = [valid_authored_item(kind, "n" + str(i)) for i, kind in enumerate(["events.event", "home.listing", "health.appointment", "travel.connection"])]
    for entry in entries:
        entry["details"] = {key: value for key, value in entry["details"].items() if key in {"origin", "destination", "doctor_name"}}
        entry.pop("sources")
        entry.pop("observed_at")
    result = normalize(entries)
    assert result.status == "valid"
    for item in result.items:
        assert not {"price", "currency", "rating", "reviews", "availability", "insurance", "transport_method", "lat", "lon"}.intersection(item.content)
        assert item.content["authoring"]["sources"] == []
        assert "observed_at" not in item.content["authoring"]
    zero = valid_authored_item("shopping.product")
    zero["details"].update({"price_cents": 0, "rating": 0, "reviews": 0})
    assert normalize([zero]).items[0].content["price_cents"] == 0


@pytest.mark.parametrize("kind,patch", [
    ("events.event", {"date_start": "2027-02-29"}),
    ("events.event", {"date_start": "2027-01-30T09:00:00"}),
    ("events.event", {"date_start": "2027-01-30", "date_end": "2027-01-29"}),
    ("events.event", {"date_start": "2027-01-30T09:00:00+04:00", "date_end": "2027-01-30T10:00:00+04:00", "timezone": "Europe/Brussels"}),
    ("events.event", {"timezone": "MadeUp/Timezone"}),
    ("events.event", {"venue": {"name": "Bad location", "lat": 91, "lon": 4}}),
    ("home.listing", {"lat": -91}),
    ("home.listing", {"size_sqm": -2}),
    ("health.appointment", {"slot_datetime": "2027-02-01T10:00:00"}),
    ("travel.connection", {"origin": ""}),
    ("travel.connection", {"arrival": "2027-01-28T10:00:00Z"}),
    ("travel.connection", {"geometry": {"type": "LineString", "coordinates": [[180.01, 0], [4, 50]]}}),
    ("travel.stay", {"check_out": "2027-01-28"}),
    ("shopping.product", {"price_cents": True}),
    ("shopping.product", {"rating": 8}),
    ("business.company_financial_result", {"fiscal_quarter": 5}),
    ("weather.weather_day", {"temperature_min_c": 20, "temperature_max_c": 10}),
    ("hosting.hosting_domain", {"checked_at": "2026-10-26T10:00:00"}),
    ("nutrition.recipe", {"servings": 0}),
    ("social_media.social_post", {"likes_count": -1}),
])
# contract-test: supporting surface=rest_api assertions=authored-results.content.typed-and-useful,authored-results.maps.source-faithful-geometry,authored-results.groups.same-response-and-reuse
def test_invalid_facts_do_not_break_independent_items(kind, patch):
    bad = valid_authored_item(kind, "bad")
    bad["details"].update(patch)
    result = normalize([bad, valid_authored_item("events.event", "good")])
    assert result.status == "partial"
    assert [item.local_id for item in result.items] == ["good"]
    assert {"code": "invalid_item", "path": "items[0]"} in result.warnings


# contract-test: supporting surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
def test_duplicate_labels_are_never_rebound_and_view_keeps_valid_order():
    entries = [valid_authored_item(local_id=label) for label in ["duplicate", "good", "duplicate", "last"]]
    result = normalize(entries, view={"mode": "map", "items": ["last", "duplicate", "missing", "good"]})
    assert [item.local_id for item in result.items] == ["good", "last"]
    assert result.view == {"mode": "map", "items": ["last", "good"]}
    assert [w["code"] for w in result.warnings].count("duplicate_label") == 2
    assert {"code": "unresolved_view_label", "path": "view.items"} in result.warnings
    assert "duplicate" not in result.source_json
    assert normalize(entries, view={"mode": "cards", "items": ["duplicate"]}).view is None


@pytest.mark.parametrize("kind", ["ai.app_skill_use", "tasks.task", "workflows.workflow", "images.generated_image", "images.image", "calendar.event", "event", "not-an-app.result"])
# contract-test: supporting surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.actions.truthful-and-explicit
def test_unknown_internal_operation_and_generated_asset_kinds_are_rejected(kind):
    bad = valid_authored_item()
    bad["kind"] = kind
    assert normalize([bad]).status == "invalid_source"


@pytest.mark.parametrize("field", ["status", "booked", "upload_id", "embed_id", "user_id", "app_skill_use", "execution_status"])
# contract-test: supporting surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.actions.truthful-and-explicit
def test_details_cannot_claim_authority_or_override_assigned_identity(field):
    bad = valid_authored_item()
    bad["details"][field] = "fabricated"
    assert normalize([bad]).status == "invalid_source"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:image/png;base64,AAA", "file:///tmp/image.jpg",
    "https://localhost/image.jpg", "https://metadata.internal/image.jpg", "https://127.0.0.1/image.jpg",
    "https://10.0.0.1/image.jpg", "https://169.254.169.254/image.jpg", "https://[::1]/image.jpg",
    "https://[::ffff:127.0.0.1]/image.jpg", "https://2130706433/image.jpg", "https://127.1/image.jpg",
    "https://0177.0.0.1/image.jpg", "https://username:private@example.org/image.jpg",
    "https://example.org:99999/image.jpg", "https://example.org\\@127.0.0.1/image.jpg",
    "https://example.org/%0Asecret", "https://example.org/image.jpg\n", "http://example.org/image.jpg",
])
# contract-test: supporting surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.groups.same-response-and-reuse
def test_disallowed_images_leave_readable_card_without_private_diagnostics(url):
    entry = valid_authored_item()
    entry["images"] = [url, {"url": "https://example.org/good.jpg", "caption": "A venue", "attribution": "User photographer"}]
    entry["details"]["image_url"] = url
    result = normalize([entry])
    assert result.status == "partial"
    assert result.items[0].content["image_url"] == "https://example.org/good.jpg"
    assert result.items[0].content["images"] == entry["images"][1:]
    assert url not in json.dumps(result.warnings)
    assert url not in result.source_json


# contract-test: supporting surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.facts.provenance-and-drafts
def test_ordered_reference_images_and_provenance_references_remain_unresolved_data():
    entry = valid_authored_item()
    entry["sources"] = [{"embed_ref": "research-upload-AB12", "label": "My itinerary"}]
    entry["images"] = [{"embed_ref": "existing-image-CD34", "caption": "Venue"}, "https://example.org/second.jpg"]
    result = normalize([entry])
    assert result.status == "valid"
    assert result.items[0].content["images"] == entry["images"]
    assert result.items[0].content["authoring"]["sources"] == entry["sources"]
    assert "embed_id" not in result.items[0].content


@pytest.mark.parametrize("kind", ["images.image_result", "videos.video", "models3d.model_result", "design.icon_result"])
# contract-test: supporting surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.media.safe-and-attributed
def test_media_resources_require_real_resource_identity_not_only_a_title(kind):
    entry = valid_authored_item(kind)
    entry["details"] = {"title": "Imagined resource"} if kind != "design.icon_result" else {"display_name": "Imagined icon"}
    assert normalize([entry]).status == "invalid_source"


# contract-test: supporting surface=rest_api assertions=authored-results.media.safe-and-attributed
def test_media_reference_identity_is_accepted_without_claiming_ownership():
    entry = valid_authored_item("images.image_result")
    entry["details"] = {"embed_ref": "existing-image-CD34"}
    result = normalize([entry])
    assert result.status == "valid"
    assert result.items[0].content["embed_ref"] == "existing-image-CD34"
    assert not {"user_id", "upload_id", "generated", "is_owner"}.intersection(result.items[0].content)


# contract-test: supporting surface=rest_api assertions=authored-results.facts.provenance-and-drafts,authored-results.actions.truthful-and-explicit
def test_social_drafts_do_not_claim_publication_or_engagement():
    entry = valid_authored_item("social_media.social_post", origin="draft")
    assert normalize([entry]).status == "invalid_source"
    entry["details"] = {"body": "A proposed post", "platform": "Mastodon"}
    result = normalize([entry])
    assert result.status == "valid"
    assert result.items[0].content["authoring"]["origin"] == "draft"
    assert "published_at" not in result.items[0].content


# contract-test: supporting surface=rest_api assertions=authored-results.maps.source-faithful-geometry,authored-results.facts.provenance-and-drafts
def test_approximate_areas_online_items_and_endpoint_only_connections_stay_source_faithful():
    event = valid_authored_item(local_id="online")
    event["details"] = {"online": True, "online_url": "https://example.org/event"}
    appointment = valid_authored_item("health.appointment", "telehealth")
    appointment["details"] = {"doctor_name": "Dr Example", "telehealth": True}
    connection = valid_authored_item("travel.connection", "trip")
    connection["details"] = {"origin": "Berlin", "destination": "Brussels"}
    listing = valid_authored_item("home.listing", "area")
    result = normalize([event, appointment, connection, listing], view={"mode": "map"})
    assert result.status == "valid"
    assert all("lat" not in item.content and "lon" not in item.content for item in result.items)
    assert "geometry" not in result.items[2].content and "legs" not in result.items[2].content
    assert result.items[3].content["location_precision"] == "approximate"
    assert result.items[3].content["location_area"] == listing["details"]["location_area"]


# contract-test: supporting surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
def test_item_count_size_and_nonfinite_limits_isolate_failures():
    entries = [valid_authored_item(local_id="item" + str(i)) for i in range(51)]
    result = normalize(entries)
    assert len(result.items) == 50 and result.status == "partial"
    assert {"code": "item_limit", "path": "items"} in result.warnings
    # Duplicates after the truncation limit still cannot rebind accepted labels.
    entries[-1]["id"] = "item0"
    assert "item0" not in [item.local_id for item in normalize(entries).items]
    good = valid_authored_item(local_id="good")
    huge = valid_authored_item(local_id="huge")
    huge["details"]["description"] = "A" * 60000
    nan = valid_authored_item("home.listing", "nan")
    nan["details"]["size_sqm"] = float("nan")
    result = normalize([huge, nan, good])
    assert [item.local_id for item in result.items] == ["good"]
    assert result.status == "partial"


@pytest.mark.parametrize("source", [
    "", "{", "[]", '{"schemaVersion":true,"items":[]}', '{"schemaVersion":2,"items":[]}',
    '{"schemaVersion":1,"items":[]}', '{"schemaVersion":1,"items":"private content"}',
    '{"schemaVersion":1,"items":[],"secret":"sensitive"}', "A" * 262145,
])
# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_invalid_envelopes_return_private_safe_outcomes(source):
    result = normalize_authored_results_source(source)
    assert result.status == "invalid_source"
    assert result.items == [] and result.source_json == ""
    assert result.parse_error
    assert source not in result.parse_error if source else True


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_only_explicit_fence_language_is_recognized():
    assert is_authored_results_fence("openmates_embeds")
    assert is_authored_results_fence(" OpenMates_Embeds ")
    assert not is_authored_results_fence("json")
    assert not is_authored_results_fence(None)


@pytest.mark.parametrize("local_id", ["one\n", "one two", "1one", "one:two", "one" * 30])
# contract-test: supporting surface=rest_api assertions=authored-results.groups.same-response-and-reuse
def test_local_labels_are_unambiguous_tokens(local_id):
    result = normalize([valid_authored_item(local_id=local_id)])
    assert result.status == "invalid_source"


# contract-test: supporting surface=rest_api assertions=authored-results.content.typed-and-useful,authored-results.lifecycle.encrypted-and-stable
def test_duplicate_json_fields_do_not_silently_replace_facts():
    encoded = json.dumps(valid_authored_item())
    encoded = encoded.replace('"id": "one"', '"id": "one", "id": "replaced"')
    result = normalize_authored_results_source('{"schemaVersion":1,"items":[' + encoded + ']}')
    assert result.status == "invalid_source"
    assert result.source_json == ""
    assert "replaced" not in result.parse_error


# contract-test: supporting surface=rest_api assertions=authored-results.content.typed-and-useful
def test_same_day_event_dates_are_preserved_without_inventing_an_exclusive_end():
    entry = valid_authored_item()
    entry["details"]["date_end"] = entry["details"]["date_start"]
    result = normalize([entry])
    assert result.status == "valid"
    assert result.items[0].content["date_start"] == result.items[0].content["date_end"] == "2027-01-30"


@pytest.mark.parametrize("reference", [
    "Venue photo.jpg", "Bühne 東京.jpg", "venue.jpg (2)", " exact index value ",
    "https://example.org/photo.jpg", "é" * 256,
])
# contract-test: supporting surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.facts.provenance-and-drafts
def test_exact_context_references_allow_filenames_and_unicode_without_normalization(reference):
    entry = valid_authored_item("images.image_result")
    entry["sources"] = [{"embed_ref": reference}]
    entry["images"] = [{"embed_ref": reference, "caption": "Supplied image"}]
    entry["details"] = {"embed_ref": reference}
    result = normalize([entry])
    assert result.status == "valid"
    content = result.items[0].content
    assert content["authoring"]["sources"][0]["embed_ref"] == reference
    assert content["images"][0]["embed_ref"] == reference
    assert content["embed_ref"] == reference
    # The shared schema includes the same exact-reference constraints for other
    # clients, independent of the Python custom format checker.
    schema = get_authored_results_schema(["images.image_result"])
    assert Draft202012Validator(schema).is_valid({"schemaVersion": 1, "items": [entry]})


@pytest.mark.parametrize("reference", [
    "", " ", "\t", "x" * 257, "photo\n.jpg", "photo\r.jpg", "photo\t.jpg",
    "photo\x00.jpg", "photo\x1f.jpg", "photo\x7f.jpg", "photo\x85.jpg",
    "photo\u2028.jpg", "photo\u2029.jpg",
])
@pytest.mark.parametrize("position", ["sources", "images", "details"])
# contract-test: supporting surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
def test_context_reference_controls_blank_values_and_limits_are_rejected(reference, position):
    entry = valid_authored_item("images.image_result")
    if position == "details":
        entry["details"] = {"embed_ref": reference}
    else:
        entry[position] = [{"embed_ref": reference}]
    schema = get_authored_results_schema(["images.image_result"])
    assert not Draft202012Validator(schema).is_valid({"schemaVersion": 1, "items": [entry]})
    result = normalize([entry])
    if position == "images" and result.items:
        assert result.status == "partial"
        assert result.items[0].content["images"] == []
    else:
        assert result.status == "invalid_source"
    assert all(reference not in warning.values() for warning in result.warnings)


# contract-test: supporting surface=rest_api assertions=tv-titles.authoring.relevant-and-flexible,tv-titles.lifecycle.groups-and-actions
def test_tv_registrations_are_direct_admissions_without_discovery_or_memory_actions():
    root = Path(__file__).resolve().parents[2]
    app = yaml.safe_load((root / "backend/apps/tv/app.yml").read_text())
    from backend.shared.python_schemas.app_metadata_schemas import EmbedTypeDefinition
    assert app["skills"] == [] and "providers" not in app
    assert [memory["id"] for memory in app["settings_and_memories"]] == ["watched_movies", "watched_tv_shows", "to_watch_list"]
    assert [entry["id"] for entry in app["embed_types"]] == ["movie", "series"]
    for entry in app["embed_types"]:
        validated = EmbedTypeDefinition.model_validate(entry)
        kind = "tv." + entry["id"]
        assert validated.category == "direct" and validated.groupable
        assert validated.frontend_type == "tv-" + entry["id"]
        assert validated.backend_type == "tv_" + entry["id"]
        assert validated.authoring == {"kind": kind, "schema_id": kind}
        assert validated.preview_component == "tv/TVTitleEmbedPreview.svelte"
        assert validated.fullscreen_component == "tv/TVTitleEmbedFullscreen.svelte"
        assert validated.gradient_var == "--color-app-tv"
        assert validated.content_catalog["enabled"] is True
        assert validated.content_catalog["content_type_id"] == validated.backend_type
        definition = get_authoring_definitions()[kind]
        assert definition["skill_id"] == entry["id"]
        assert definition["real_asset"] is False


@pytest.mark.parametrize("kind", ["tv.movie", "tv.series"])
# contract-test: supporting surface=rest_api assertions=tv-titles.authoring.relevant-and-flexible,tv-titles.presentation.posters-and-details
def test_tv_schema_selection_and_unknown_facts_preserve_explicit_drafts(kind):
    entry = valid_authored_item(kind, origin="draft")
    entry["details"] = {"synopsis": "An explicitly requested fictional title."}
    entry.pop("sources")
    entry.pop("observed_at")
    result = normalize([entry])
    assert result.status == "valid"
    assert result.items[0].content == {
        "title": entry["title"], "synopsis": entry["details"]["synopsis"],
        "type": get_authoring_definitions()[kind]["backend_type"],
        "authoring": {"schema_version": 1, "kind": kind, "origin": "draft", "sources": []},
    }
    schema = get_authored_results_schema([kind])
    assert "tv_score" in schema["$defs"]
    assert "event" not in schema["$defs"] and "website" not in schema["$defs"]
    assert ("tv_season" in schema["$defs"]) == (kind == "tv.series")
    assert Draft202012Validator(schema).is_valid({"schemaVersion": 1, "items": [entry]})


@pytest.mark.parametrize("kind,patch", [
    ("tv.movie", {"release_date": "2026-02-30"}),
    ("tv.movie", {"release_date": "2026-09-15T00:00:00Z"}),
    ("tv.movie", {"year": 2025}),
    ("tv.movie", {"year": -1}),
    ("tv.movie", {"runtime_minutes": -1}),
    ("tv.movie", {"runtime_minutes": 1.5}),
    ("tv.series", {"first_air_date": "2023-02-29"}),
    ("tv.series", {"last_air_date": "2022-12-31"}),
    ("tv.series", {"start_year": 2022}),
    ("tv.series", {"end_year": 2025}),
    ("tv.series", {"episode_runtime_minutes": -1}),
    ("tv.series", {"season_count": -1}),
    ("tv.series", {"season_count": True}),
    ("tv.series", {"season_count": 0}),
    ("tv.series", {"episode_count": -1}),
    ("tv.series", {"episode_count": 9}),
    ("tv.series", {"seasons": [{"season_number": 1}, {"season_number": 1}]}),
    ("tv.series", {"seasons": [{"season_number": 0}, {"season_number": 0}]}),
    ("tv.series", {"seasons": [{"season_number": -1}]}),
    ("tv.series", {"seasons": [{"season_number": 1.5}]}),
    ("tv.series", {"seasons": [{"title": "Missing supplied number"}]}),
    ("tv.series", {"seasons": [{"season_number": 1, "first_air_date": "2023-13-01"}]}),
    ("tv.series", {"seasons": [{"season_number": 1, "episode_count": -1}]}),
    ("tv.series", {"seasons": [{"season_number": 5}]}),
])
# contract-test: supporting surface=rest_api assertions=tv-titles.series.supplied-seasons,tv-titles.presentation.posters-and-details,tv-titles.lifecycle.groups-and-actions
def test_conflicting_tv_facts_reject_only_the_affected_item(kind, patch):
    bad = valid_authored_item(kind, "bad")
    bad["details"].update(patch)
    result = normalize([bad, valid_authored_item("tv.movie", "good")])
    assert result.status == "partial"
    assert [item.local_id for item in result.items] == ["good"]
    assert {"code": "invalid_item", "path": "items[0]"} in result.warnings


@pytest.mark.parametrize("score", [
    {"value": 10.1, "scale": 10, "source_url": "https://example.org/score"},
    {"value": -1, "scale": 10, "source_url": "https://example.org/score"},
    {"value": 0, "scale": 0, "source_url": "https://example.org/score"},
    {"value": 8.2, "scale": 10},
    {"value": 8.2, "scale": 10, "source_url": "javascript:alert(1)"},
    {"value": 8.2, "scale": 10, "source_url": "https://127.0.0.1/score"},
    {"value": 8.2, "scale": 10, "source_url": "https://secret@example.org/score"},
    {"value": 8.2, "scale": 10, "source_url": "https://example.org/score", "votes": -1},
    {"value": 8.2, "scale": 10, "source_url": "https://example.org/score", "votes": 1.5},
    {"value": 8.2, "scale": 10, "source_url": "https://example.org/score", "observed_at": "2026-10-26T10:00:00"},
])
@pytest.mark.parametrize("kind", ["tv.movie", "tv.series"])
# contract-test: supporting surface=rest_api assertions=tv-titles.presentation.posters-and-details
def test_tv_scores_require_real_source_context_and_consistent_scale(kind, score):
    entry = valid_authored_item(kind)
    entry["details"]["score"] = score
    assert normalize([entry]).status == "invalid_source"


@pytest.mark.parametrize("details", [
    {"start_year": 2026, "end_year": 2025},
    {"first_air_date": "2026-01-01", "end_year": 2025},
    {"start_year": 2026, "last_air_date": "2025-12-31"},
])
# contract-test: supporting surface=rest_api assertions=tv-titles.series.supplied-seasons
def test_partial_series_date_and_year_facts_cannot_conflict(details):
    entry = valid_authored_item("tv.series")
    entry["details"] = details
    assert normalize([entry]).status == "invalid_source"


# contract-test: supporting surface=rest_api assertions=tv-titles.series.supplied-seasons,tv-titles.presentation.posters-and-details
def test_partial_seasons_specials_zero_counts_and_source_score_remain_supplied_facts():
    entry = valid_authored_item("tv.series")
    entry["details"] = {
        "season_count": 4, "episode_count": 20,
        "seasons": [{"season_number": 1, "title": "First season"}, {"season_number": 0, "title": "Specials", "episode_count": 0}],
        "score": {"value": 0, "scale": 100, "source_url": "https://example.org/score", "votes": 0},
    }
    result = normalize([entry])
    assert result.status == "valid"
    content = result.items[0].content
    assert content["seasons"] == entry["details"]["seasons"]
    assert "episode_count" not in content["seasons"][0]
    assert [row["season_number"] for row in content["seasons"]] == [1, 0]
    assert content["season_count"] == 4 and content["episode_count"] == 20
    assert content["score"] == entry["details"]["score"]
    assert not {"complete", "guide_complete", "seasons_complete", "rating", "availability", "watched"}.intersection(content)
    del entry["details"]["season_count"]
    del entry["details"]["episode_count"]
    absent = normalize([entry]).items[0].content
    assert "season_count" not in absent and "episode_count" not in absent


@pytest.mark.parametrize("kind", ["tv.movie", "tv.series"])
# contract-test: supporting surface=rest_api assertions=tv-titles.presentation.posters-and-details
def test_tv_posters_are_optional_and_common_image_references_keep_exact_identity(kind):
    entry = valid_authored_item(kind)
    entry["details"]["poster_url"] = "https://127.0.0.1/private-poster.jpg"
    entry["images"] = [{"embed_ref": "海報 photo.jpg (2)", "caption": "Supplied poster"}]
    if kind == "tv.series":
        entry["details"]["seasons"][1]["poster_url"] = "javascript:bad-poster"
    result = normalize([entry])
    assert result.status == "partial"
    content = result.items[0].content
    assert "poster_url" not in content
    assert content["images"] == entry["images"]
    assert {"code": "invalid_image", "path": "items[0].details.poster_url"} in result.warnings
    if kind == "tv.series":
        assert "poster_url" not in content["seasons"][1]
        assert {"code": "invalid_image", "path": "items[0].details.seasons[1].poster_url"} in result.warnings
    assert "private-poster" not in result.source_json
    assert "private-poster" not in json.dumps(result.warnings)


@pytest.mark.parametrize("field", ["watched", "watchlist", "personal_rating", "rating", "streaming_availability", "playback_url"])
@pytest.mark.parametrize("kind", ["tv.movie", "tv.series"])
# contract-test: supporting surface=rest_api assertions=tv-titles.lifecycle.groups-and-actions,tv-titles.presentation.posters-and-details
def test_tv_authoring_does_not_set_personal_memory_or_playback_authority(kind, field):
    entry = valid_authored_item(kind)
    entry["details"][field] = "fabricated"
    assert normalize([entry]).status == "invalid_source"


# contract-test: supporting surface=rest_api assertions=tv-titles.lifecycle.groups-and-actions
def test_mixed_title_group_keeps_order_identity_and_exact_supplied_details():
    entries = [valid_authored_item(kind, label) for kind, label in [
        ("tv.movie", "first_movie"), ("tv.series", "series"), ("tv.movie", "second_movie"),
    ]]
    result = normalize(entries, view={"mode": "cards", "items": ["first_movie", "series", "second_movie"]})
    assert result.status == "valid"
    assert [item.local_id for item in result.items] == ["first_movie", "series", "second_movie"]
    assert [item.backend_type for item in result.items] == ["tv_movie", "tv_series", "tv_movie"]
    assert result.view["items"] == [item.local_id for item in result.items]
    assert normalize_authored_results_source(result.source_json) == result
