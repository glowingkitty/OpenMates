//! npm-parity Project selector ranking over the shared embeds family selector vectors.
use super::*;

const FIXTURE: &str =
    include_str!("../../../../../tests/sdk-conformance/fixtures/sdk-api-key-embeds-family.json");

fn suite() -> Value {
    let document: Value = serde_json::from_str(FIXTURE).expect("checked-in fixture is valid JSON");
    document["capabilities"]["sdk.embeds.family"].clone()
}

#[test]
fn canonical_uuid_accepts_only_hyphenated_text_in_any_case() {
    assert!(is_canonical_uuid("aaaaaaaa-1111-4111-8111-111111111111"));
    assert!(is_canonical_uuid("AAAAAAAA-1111-4111-8111-111111111111"));
    assert!(!is_canonical_uuid("{aaaaaaaa-1111-4111-8111-111111111111}"));
    assert!(!is_canonical_uuid("urn:uuid:aaaaaaaa-1111-4111-8111-111111111111"));
    assert!(!is_canonical_uuid("aaaaaaaa111141118111111111111111"));
    assert!(!is_canonical_uuid("aaaaaaaa-1111-4111-8111-11111111111g"));
}

#[test]
fn shared_selector_vectors_rank_like_npm() {
    let suite = suite();
    let projects = suite["selector_projects"].as_array().expect("selector projects");
    let candidates = projects
        .iter()
        .map(|p| SelectorCandidate {
            project_id: p["project_id"].as_str().expect("id"),
            slug: p["slug"].as_str().expect("slug"),
            name: p["name"].as_str().expect("name"),
        })
        .collect::<Vec<_>>();
    let vectors = suite["vectors"].as_array().expect("vectors");
    let mut seen = 0;
    for vector in vectors.iter().filter(|v| v.get("resolved_project_id").is_some()) {
        seen += 1;
        let selector = vector["project_id"].as_str().expect("selector");
        let expected = vector["resolved_project_id"].as_str();
        if is_canonical_uuid(selector) {
            assert_eq!(Some(selector), expected, "{}", vector["id"]);
            continue;
        }
        let actual = rank_project_selector(selector, &candidates)
            .ok()
            .map(|index| candidates[index].project_id);
        assert_eq!(actual, expected, "{}", vector["id"]);
    }
    assert_eq!(seen, 7);
}

#[test]
fn exact_id_wins_before_any_other_tier() {
    let candidates = [
        SelectorCandidate { project_id: "project-alpha-1", slug: "x", name: "y" },
        SelectorCandidate { project_id: "project-alpha-12", slug: "z", name: "w" },
    ];
    assert_eq!(rank_project_selector("project-alpha-1", &candidates).ok(), Some(0));
    assert!(matches!(
        rank_project_selector("PROJECT-ALPHA", &candidates),
        Err(Error::Invalid(_))
    ));
}
