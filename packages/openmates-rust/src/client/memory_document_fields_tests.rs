//! Memory document fields: web (`yaml.stringify`) and server (PyYAML) shapes read back, round trips, refusals, stamps and expiry.
use super::*;

/// What `serializeRuleDocument` (eemeli `yaml`) writes for a full Memory.
const WEB: &str = "---\ntitle: Career profile\nwhen_to_use: When writing applications.\nload_mode: ask_first\nvalid_until: 2026-12-31T23:59:59.000Z\nreferences:\n  - kind: embed\n    id: embed-1\ncreated_at: 1762000000\nupdated_at: 1762100000\napp_id: jobs\n---\nSenior Rust engineer in Berlin.\n";

#[test]
fn reads_every_field_of_a_web_document() {
    let fields = parse_memory_document(WEB).unwrap();
    assert_eq!(fields.title, "Career profile");
    assert_eq!(fields.when_to_use, "When writing applications.");
    assert_eq!(fields.load_mode, Some(MemoryLoadMode::AskFirst));
    assert_eq!(
        fields.valid_until.as_deref(),
        Some("2026-12-31T23:59:59.000Z")
    );
    assert_eq!(fields.references, ["embed-1"]);
    assert_eq!(
        (fields.created_at, fields.updated_at),
        (Some(1_762_000_000), Some(1_762_100_000))
    );
    assert_eq!(fields.app_id.as_deref(), Some("jobs"));
    assert_eq!(fields.body, "Senior Rust engineer in Berlin.");
}

#[test]
fn reads_quoted_folded_and_block_scalars() {
    let doc = "---\ntitle: 'It''s mine'\ndescription: \"Line\\none \\u00e9\"\nwhen_to_use: >-\n  When asked\n  about jobs\n---\nBody\n";
    let fields = parse_memory_document(doc).unwrap();
    assert_eq!(fields.title, "It's mine");
    assert_eq!(fields.description.as_deref(), Some("Line\none \u{e9}"));
    assert_eq!(fields.when_to_use, "When asked about jobs");
    let literal = "---\ntitle: Notes\nwhen_to_use: |\n  first\n  second\n---\nBody\n";
    assert_eq!(
        parse_memory_document(literal).unwrap().when_to_use,
        "first\nsecond"
    );
    let plain =
        "---\ntitle: A long title\n  that wraps\nwhen_to_use: \"folded\n  double\"\n---\nBody\n";
    let fields = parse_memory_document(plain).unwrap();
    assert_eq!(fields.title, "A long title that wraps");
    assert_eq!(fields.when_to_use, "folded double");
}

#[test]
fn reads_the_server_document_shape() {
    // `build_memory_document` (PyYAML safe_dump) quotes date-like strings.
    let doc = "---\ntitle: Interview prep\nwhen_to_use: 'Before interviews: ask first'\nvalid_from: '2026-11-01'\nload_mode: ask_first\n---\nPrepare answers.\n";
    let fields = parse_memory_document(doc).unwrap();
    assert_eq!(fields.when_to_use, "Before interviews: ask first");
    assert_eq!(fields.valid_from.as_deref(), Some("2026-11-01"));
}

#[test]
fn drops_legacy_chat_references_like_the_web_parser() {
    let doc = "---\ntitle: T\nreferences:\n  - kind: chat\n    id: chat-1\n  - kind: embed\n    id: \"embed-2\"\n---\nBody\n";
    assert_eq!(parse_memory_document(doc).unwrap().references, ["embed-2"]);
}

#[test]
fn refuses_documents_the_web_parser_refuses() {
    for doc in [
        "---\nwhen_to_use: x\n---\nBody\n",
        "---\ntitle: T\nload_mode: sometimes\n---\nBody\n",
        "---\ntitle: 42\n---\nBody\n",
        "---\ntitle: T\ncreated_at: -5\n---\nBody\n",
        "---\ntitle: T\ncreated_at: '5'\n---\nBody\n",
        "---\ntitle: T\nvalid_from: not a date\n---\nBody\n",
        "---\ntitle: T\nvalid_from: 2026-12-02\nvalid_until: 2026-12-01\n---\nBody\n",
        "---\ntitle: T\nreferences: [{kind: embed, id: x}]\n---\nBody\n",
        "---\ntitle: T\nreferences:\n  - kind: embed\n    id: a\n  - kind: embed\n    id: a\n---\nBody\n",
        "---\ntitle: &a T\n---\nBody\n",
        "---\ntitle: a: b\n---\nBody\n",
        "---\ntitle: T\n---\n   \n",
    ] {
        assert_eq!(
            parse_memory_document(doc).unwrap_err(),
            MemoryDocumentError::InvalidDocument,
            "{doc}"
        );
    }
}

#[test]
fn serialized_fields_read_back_unchanged_including_yaml_line_breaks() {
    let mut fields = parse_memory_document(WEB).unwrap();
    fields.title = "  Quote \" and \\ and \u{2028} and # not a comment  ".into();
    fields.when_to_use = "Line one\nline two: with colon".into();
    fields.description = Some("Legacy".into());
    fields.valid_from = Some("2026-01-01".into());
    let document = serialize_memory_document(&fields).unwrap();
    assert!(
        document
            .starts_with("---\ntitle: \"Quote \\\" and \\\\ and \\u2028 and # not a comment\"\n")
    );
    let back = parse_memory_document(&document).unwrap();
    assert_eq!(
        back.title,
        "Quote \" and \\ and \u{2028} and # not a comment"
    );
    assert_eq!(back.when_to_use, fields.when_to_use);
    assert_eq!(back.description, fields.description);
    assert_eq!(back.references, fields.references);
    assert_eq!(back.body, fields.body);
    assert_eq!(back.valid_from, fields.valid_from);
    assert_eq!(
        (back.created_at, back.app_id.as_deref()),
        (Some(1_762_000_000), Some("jobs"))
    );
}

#[test]
fn serialize_refuses_a_blank_title_or_body() {
    let mut fields = MemoryDocumentFields::default();
    fields.body = "Body".into();
    assert!(serialize_memory_document(&fields).is_err());
    fields.title = "T".into();
    fields.body = "  ".into();
    assert!(serialize_memory_document(&fields).is_err());
}

#[test]
fn stamp_keeps_the_first_save_time_and_moves_the_update_time() {
    let mut first = MemoryDocumentFields::default();
    stamp_memory_save(&mut first, None, 100);
    assert_eq!((first.created_at, first.updated_at), (Some(100), Some(100)));
    let mut next = MemoryDocumentFields::default();
    stamp_memory_save(&mut next, Some(&first), 200);
    assert_eq!((next.created_at, next.updated_at), (Some(100), Some(200)));
}

#[test]
fn expiry_follows_valid_until_and_skips_unreadable_documents() {
    let until = iso_millis("2026-12-31T23:59:59.000Z").unwrap();
    assert_eq!(until, 1_798_761_599_000);
    assert_eq!(iso_millis("2026-12-31"), Some(1_798_675_200_000));
    assert_eq!(
        iso_millis("2026-12-31T01:00:00+01:00"),
        Some(1_798_675_200_000)
    );
    assert_eq!(iso_millis("2026-02-30"), None);
    let fields = parse_memory_document(WEB).unwrap();
    assert!(!is_memory_expired(&fields, until));
    assert!(is_memory_expired(&fields, until + 1));
    let documents = [
        PersonalMemoryDocument {
            id: "personal:a".into(),
            document: Zeroizing::new(WEB.into()),
        },
        PersonalMemoryDocument {
            id: "personal:b".into(),
            document: Zeroizing::new("---\ntitle: T\nvalid_until: [x]\n---\nBody\n".into()),
        },
    ];
    assert_eq!(expired_memory_ids(&documents, until + 1), ["personal:a"]);
}
