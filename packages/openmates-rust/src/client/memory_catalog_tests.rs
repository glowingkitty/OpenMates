//! Memory catalog of a send and local Memory request decisions (web `buildMemoryCatalog` / `decideMemoryRequest`).
use super::*;

const NOW: i64 = 1_793_000_000_000; // 2026-10-26
const AUTO: &str = "---\ntitle: \"  Diet  \"\nwhen_to_use: Food and recipes\n---\nVegetarian.\n";
const ASK: &str = "---\ntitle: Career profile\nload_mode: ask_first\n---\nSenior Rust engineer.\n";
const MENTION: &str = "---\ntitle: Health\nload_mode: mention_only\n---\nPrivate.\n";
const EXPIRED: &str = "---\ntitle: Trip\nvalid_until: 2020-01-01\n---\nIn Rome.\n";
const LATER: &str = "---\ntitle: Move\nvalid_from: \"2030-01-01T00:00:00.000Z\"\n---\nNew city.\n";

fn doc(id: &str, document: &str) -> PersonalMemoryDocument {
    PersonalMemoryDocument {
        id: id.into(),
        document: Zeroizing::new(document.into()),
    }
}

fn documents() -> Vec<PersonalMemoryDocument> {
    vec![
        doc("personal:auto", AUTO),
        doc("personal:ask", ASK),
        doc("personal:mention", MENTION),
        doc("personal:expired", EXPIRED),
        doc("personal:later", LATER),
    ]
}

#[test]
fn catalog_lists_only_in_window_auto_and_ask_memories_as_backend_rows() {
    let catalog = build_memory_catalog(&documents(), NOW).unwrap();
    let wire = serde_json::to_string(&catalog).unwrap();
    assert_eq!(
        wire,
        r#"[{"id":"personal:auto","title":"Diet","when_to_use":"Food and recipes","load_mode":"auto_include","source":"personal"},{"id":"personal:ask","title":"Career profile","when_to_use":"","load_mode":"ask_first","source":"personal"}]"#
    );
}

#[test]
fn catalog_reads_folded_yaml_like_the_web_parser() {
    // `yaml.stringify` folds long plain scalars onto continuation lines.
    let folded = "---\ntitle: Long\nwhen_to_use: When planning meals for the week and choosing\n  recipes at restaurants\n---\nBody.\n";
    let catalog = build_memory_catalog(&[doc("personal:f", folded)], NOW).unwrap();
    assert_eq!(
        catalog[0].when_to_use,
        "When planning meals for the week and choosing recipes at restaurants"
    );
}

#[test]
fn catalog_skips_memories_beyond_the_character_budget() {
    let big = format!("---\ntitle: Big\n---\n{}\n", "x".repeat(19_000));
    let list: Vec<_> = (0..4)
        .map(|i| doc(&format!("personal:{i}"), &big))
        .collect();
    let catalog = build_memory_catalog(&list, NOW).unwrap();
    assert_eq!(catalog.len(), 3);
}

#[test]
fn one_unreadable_document_makes_the_send_catalog_unavailable() {
    let bad = "---\ntitle: Bad\nload_mode: sometimes\n---\nBody.\n";
    assert!(build_memory_catalog(&[doc("personal:a", AUTO), doc("personal:b", bad)], NOW).is_err());
    let settings =
        serde_json::to_string(&json!({"memory_documents":[{"id":"personal:b","document":bad}]}))
            .unwrap();
    assert!(send_memory_catalog(&settings, NOW).is_empty());
    assert!(send_memory_catalog("", NOW).is_empty());
    let settings =
        serde_json::to_string(&json!({"memory_documents":[{"id":"personal:a","document":AUTO}]}))
            .unwrap();
    assert_eq!(send_memory_catalog(&settings, NOW)[0].id, "personal:a");
}

#[test]
fn header_refuses_what_parse_rule_document_refuses() {
    for bad in [
        "---\ntitle: 5\n---\nBody.\n",
        "---\ntitle: \"   \"\n---\nBody.\n",
        "---\ntitle: T\nvalid_from: soon\n---\nBody.\n",
        "---\ntitle: T\nvalid_from: 2027-01-02\nvalid_until: 2027-01-01\n---\nBody.\n",
        "---\ntitle: T\nwhen_to_use: [a]\n---\nBody.\n",
    ] {
        assert!(parse_memory_header(bad).is_err(), "{bad}");
    }
    let header = parse_memory_header(
        "---\ntitle: T\nvalid_from: 2026-01-01\nvalid_until: 2026-01-01T12:00:00+02:00\n---\nBody.\n",
    )
    .unwrap();
    assert_eq!(header.valid_from_ms, Some(1_767_225_600_000));
    assert_eq!(header.valid_until_ms, Some(1_767_261_600_000));
    assert!(header.is_active(1_767_261_600_000));
    assert!(!header.is_active(1_767_261_600_001));
}

#[test]
fn request_keys_strip_only_the_memory_prefix_and_dedupe() {
    let keys: Vec<String> = [
        "memory-personal:a-b",
        "code-tech",
        "memory-",
        "memory-personal:a-b",
    ]
    .map(String::from)
    .into();
    assert_eq!(memory_request_ids(&keys), ["personal:a-b"]);
    assert!(is_memory_request_key("memory-x") && !is_memory_request_key("memory-"));
}

#[test]
fn request_decision_uses_the_local_mode_and_withholds_the_rest() {
    let ids: Vec<String> = [
        "personal:auto",
        "personal:ask",
        "personal:mention",
        "personal:expired",
        "personal:later",
        "personal:unknown",
    ]
    .map(String::from)
    .into();
    let decision = decide_memory_request(&ids, &documents(), NOW);
    assert_eq!(decision.auto.len(), 1);
    assert_eq!(decision.ask.len(), 1);
    assert_eq!(decision.ask[0].title, "Career profile");
    assert_eq!(
        decision.withheld,
        [
            "personal:mention",
            "personal:expired",
            "personal:later",
            "personal:unknown"
        ]
    );
    // The stored document is answered unchanged under the `memory` app id.
    assert_eq!(
        decision.auto[0].response_entry(),
        json!({"app_id":"memory","item_key":"personal:auto","content":AUTO})
    );
    assert_eq!(decision.ask[0].key(), "memory-personal:ask");
    let item = ask_first_item(&decision.ask[0]);
    assert_eq!(item.id, "memory-personal:ask");
    assert!(item.fields.get("consent_kind").is_none());
    assert!(!item.fields.to_string().contains("Senior Rust engineer"));
}

#[test]
fn assistant_saved_ask_first_memory_is_offered_in_every_build() {
    // A document as the core writes it (quoted scalars, save stamps) is read
    // by the YAML-free reader, so browser and Apple builds offer it too.
    let mut fields = super::super::memory_document_fields::MemoryDocumentFields::default();
    fields.title = "Favourite test colour".into();
    fields.when_to_use = "When colours or visual preferences matter.".into();
    fields.body = "The user's favourite test colour is teal.".into();
    fields.load_mode = Some(MemoryLoadMode::AskFirst);
    fields.created_at = Some(1_793_000_000);
    fields.updated_at = Some(1_793_000_000);
    let document =
        super::super::memory_document_fields::serialize_memory_document(&fields).unwrap();
    let settings = serde_json::to_string(
        &json!({"memory_documents":[{"id":"personal:colour","document":document.as_str()}]}),
    )
    .unwrap();
    let catalog = send_memory_catalog(&settings, NOW);
    assert_eq!(catalog.len(), 1);
    assert_eq!(
        (
            catalog[0].id.as_str(),
            catalog[0].title.as_str(),
            catalog[0].load_mode
        ),
        ("personal:colour", "Favourite test colour", "ask_first")
    );
    let ids = memory_request_ids([&"memory-personal:colour".to_owned()]);
    let decision = decide_memory_request(&ids, &[doc("personal:colour", &document)], NOW);
    assert!(decision.auto.is_empty() && decision.withheld.is_empty());
    assert_eq!(decision.ask[0].key(), "memory-personal:colour");
    assert_eq!(decision.ask[0].document.as_str(), document.as_str());
}
