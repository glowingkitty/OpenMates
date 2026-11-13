//! `SendOptionsRecord` attachments, exclusions and PII mappings map onto the core options and are validated before anything is shown.
use crate::view_core_tests::private_dir;
use crate::view_record_details::PiiMappingRecord;
use crate::view_send_options_tests::{opened, options};
use crate::view_window_tests::CHAT;
use crate::*;
use openmates_sdk::view_model::SendTurnOptions;

const EMBED: &str = "55555555-5555-4555-8555-555555555555";

fn image() -> SendEmbedRecord {
    SendEmbedRecord {
        embed_id: EMBED.into(),
        embed_type: "image".into(),
        reference_type: None,
        status: "finished".into(),
        content: Some("type: image\nfilename: garden-shed.png".into()),
        text_preview: Some("garden-shed.png".into()),
        child_embed_ids: None,
    }
}

#[test]
fn records_map_onto_core_attachments_exclusions_and_mappings() {
    let record = SendOptionsRecord {
        embeds: vec![
            image(),
            SendEmbedRecord {
                embed_id: "66666666-6666-4666-8666-666666666666".into(),
                embed_type: "code-code".into(),
                reference_type: Some("code".into()),
                content: None,
                text_preview: None,
                child_embed_ids: Some(vec![EMBED.into()]),
                ..image()
            },
        ],
        excluded_pii_originals: vec!["alice@example.org".into()],
        excluded_pii_placeholders: vec!["[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]".into()],
        pii_mappings: vec![PiiMappingRecord {
            placeholder: "[EMAIL_1]".into(),
            original: "bob@example.org".into(),
            kind: "EMAIL".into(),
        }],
        ..options()
    };
    let debug = format!("{record:?}");
    assert!(!debug.contains("alice@example.org") && !debug.contains("garden-shed.png\n"));
    let turn = SendTurnOptions::from(record);
    assert_eq!(turn.embeds.len(), 2);
    let (first, second) = (&turn.embeds[0], &turn.embeds[1]);
    assert_eq!(
        (
            first.embed_id.as_str(),
            first.kind.as_str(),
            first.status.as_str()
        ),
        (EMBED, "image", "finished")
    );
    assert_eq!(
        first.content.as_deref().map(String::as_str),
        Some("type: image\nfilename: garden-shed.png")
    );
    assert_eq!(
        first.text_preview.as_deref().map(String::as_str),
        Some("garden-shed.png")
    );
    assert_eq!(second.reference_type.as_deref(), Some("code"));
    assert!(second.content.is_none());
    assert_eq!(second.embed_ids.as_deref(), Some(&[EMBED.to_owned()][..]));
    assert_eq!(turn.pii_exclusions.originals.len(), 1);
    assert_eq!(
        turn.pii_exclusions.originals[0].as_str(),
        "alice@example.org"
    );
    assert_eq!(
        turn.pii_exclusions.placeholders,
        ["[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]"]
    );
    assert_eq!(turn.pii_mappings.len(), 1);
    assert_eq!(
        (
            turn.pii_mappings[0].placeholder.as_str(),
            turn.pii_mappings[0].original.as_str(),
            turn.pii_mappings[0].kind.as_str()
        ),
        ("[EMAIL_1]", "bob@example.org", "EMAIL")
    );
    let plain = SendTurnOptions::from(options());
    assert!(
        plain.embeds.is_empty() && plain.pii_exclusions.is_empty() && plain.pii_mappings.is_empty()
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn malformed_attachments_exclusions_and_mappings_are_invalid_before_anything_is_shown() {
    let dir = private_dir();
    let (core, events) = opened(dir.path()).await;
    let before = events.all().len();
    let refused = [
        SendOptionsRecord {
            embeds: vec![SendEmbedRecord {
                embed_id: "bad\"id".into(),
                ..image()
            }],
            ..options()
        },
        SendOptionsRecord {
            embeds: vec![image(), image()],
            ..options()
        },
        SendOptionsRecord {
            embeds: vec![SendEmbedRecord {
                content: Some(String::new()),
                ..image()
            }],
            ..options()
        },
        SendOptionsRecord {
            embeds: vec![SendEmbedRecord {
                embed_type: String::new(),
                ..image()
            }],
            ..options()
        },
        SendOptionsRecord {
            excluded_pii_originals: vec![String::new()],
            ..options()
        },
        SendOptionsRecord {
            excluded_pii_placeholders: vec!["not-a-token".into()],
            ..options()
        },
        SendOptionsRecord {
            pii_mappings: vec![PiiMappingRecord {
                placeholder: "EMAIL".into(),
                original: "bob@example.org".into(),
                kind: String::new(),
            }],
            ..options()
        },
    ];
    for (index, record) in refused.into_iter().enumerate() {
        let result = core
            .send_with_options(
                10 + index as u64,
                Some(CHAT.into()),
                "Synthetic question".into(),
                record,
                None,
            )
            .await;
        assert!(
            matches!(result, Err(CoreError::Invalid { .. })),
            "{index}: {result:?}"
        );
    }
    // A stored reference cannot enter a volatile chat.
    let incognito = SendOptionsRecord {
        incognito: true,
        embeds: vec![SendEmbedRecord {
            content: None,
            ..image()
        }],
        ..options()
    };
    let result = core
        .send_with_options(30, None, "Synthetic question".into(), incognito, None)
        .await;
    assert!(
        matches!(result, Err(CoreError::Invalid { .. })),
        "{result:?}"
    );
    assert_eq!(events.all().len(), before, "nothing is shown or sent");
}
