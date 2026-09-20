# contract-test-file: tooling

from scripts import ci_schema_bundle as bundle


def test_schema_bundle_profile_runs_only_canonical_database_initializer():
    profile = bundle.producer_profile("a" * 40)
    assert set(profile["services"]) == set(bundle.SCHEMA_SERVICES)
    assert (
        profile["services"]["cms"]["environment"]["ADMIN_PASSWORD"]
        == bundle.PREPARED_SCHEMA_ADMIN_PASSWORD
    )
    assert not any("ports" in service for service in profile["services"].values())


def test_schema_bundle_sanitizes_application_and_transient_rows():
    sql = bundle.SANITIZE_SQL
    assert "tablename NOT LIKE 'directus" in sql
    assert "TRUNCATE TABLE directus_sessions" in sql
    assert "DELETE FROM directus_users" in sql
    assert "runtime@example.com" in sql
