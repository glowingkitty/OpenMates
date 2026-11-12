//! Argument parsing, scope choice, error wording and output of `embeds enhance` / `embeds restore`.
use super::*;
use openmates_sdk::client::embed_updated_event::{EmbedUpdateAction, EmbedUpdateSurface};
use openmates_sdk::client::embed_user_revision::{CommittedUserRevision, UserRevisionCommit};

const EMBED: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const PROJECT: &str = "33333333-3333-4333-8333-333333333333";
const OPERATION: &str = "44444444-4444-4444-8444-444444444444";

fn parsed(argv: &[&str]) -> Invocation {
    let mut full = vec!["openmates"];
    full.extend_from_slice(argv);
    super::super::parse_from(full)
        .unwrap_or_else(|_| panic!("synthetic argv parses"))
        .invocation
        .unwrap_or_else(|| panic!("synthetic argv is a command"))
}

fn committed(
    action: EmbedUpdateAction,
    version: i64,
    restored_from: Option<i64>,
) -> CommittedUserRevision {
    CommittedUserRevision {
        embed_id: EMBED.into(),
        operation_id: OPERATION.into(),
        version,
        base_version: version - 1,
        action,
        restored_from,
        surface: EmbedUpdateSurface::Chat,
        encrypted_content: "ciphertext".into(),
        encrypted_text_preview: None,
        content_hash: "hash".into(),
        updated_at: 1_700_000_000,
        history_rows: vec![],
        idempotent: false,
        pending_notice: true,
        hashed_chat_id: None,
        media_index_repointed: false,
    }
}

fn outcome(
    action: EmbedUpdateAction,
    version: i64,
    restored_from: Option<i64>,
    event: EventDelivery,
) -> EmbedRevisionOutcome {
    EmbedRevisionOutcome {
        commit: UserRevisionCommit {
            committed: committed(action, version, restored_from),
            cache_synchronized: true,
        },
        event,
    }
}

// contract-test: supporting surface=cli assertions=embed-user-edits.enhance.faithful-2k,embed-user-edits.restore.creates-version
#[test]
fn declared_grammar_routes_both_commands_to_the_cookie_shell_with_their_flags() {
    let enhance = parsed(&["embeds", "enhance", EMBED, "--project", PROJECT, "--json"]);
    assert_eq!(enhance.command_path(), "embeds enhance");
    assert!(supported(&enhance));
    assert!(!super::super::sdk_embeds_supported(&enhance));
    let options = parse(&enhance).unwrap_or_else(|_| panic!("synthetic enhance"));
    assert_eq!(options.scope, ScopeArg::Project(PROJECT.into()));
    assert_eq!((options.version, options.resume), (None, None));

    let resume = parsed(&["embeds", "enhance", EMBED, "--resume", OPERATION]);
    let options = parse(&resume).unwrap_or_else(|_| panic!("synthetic resume"));
    assert_eq!(options.resume.as_deref(), Some(OPERATION));
    assert_eq!(options.scope, ScopeArg::Chat(None));

    let restore = parsed(&["embeds", "restore", EMBED, "--version", "2", "--chat", CHAT]);
    assert!(supported(&restore));
    let options = parse(&restore).unwrap_or_else(|_| panic!("synthetic restore"));
    assert_eq!(options.version, Some(2));
    assert_eq!(options.scope, ScopeArg::Chat(Some(CHAT.into())));
}

// contract-test: supporting surface=cli assertions=embed-user-edits.restore.creates-version
#[test]
fn invalid_arguments_are_refused_before_any_request() {
    for argv in [
        vec!["embeds", "restore", EMBED],
        vec!["embeds", "restore", EMBED, "--version", "0"],
        vec!["embeds", "restore", "short-id", "--version", "1"],
        vec![
            "embeds",
            "enhance",
            EMBED,
            "--chat",
            CHAT,
            "--project",
            PROJECT,
        ],
        vec!["embeds", "enhance", EMBED, "--resume", "not-a-uuid"],
        vec!["embeds", "enhance", EMBED, "--version", "2"],
        vec![
            "embeds",
            "restore",
            EMBED,
            "--version",
            "1",
            "--resume",
            OPERATION,
        ],
    ] {
        // Refused by the declared grammar or by this module's parse.
        let mut full = vec!["openmates"];
        full.extend_from_slice(&argv);
        let refused = match super::super::parse_from(full) {
            Err(_) => true,
            Ok(parsed) => parsed.invocation.is_none_or(|i| parse(&i).is_err()),
        };
        assert!(refused, "{argv:?} must be refused");
    }
}

// contract-test: supporting surface=cli assertions=embed-user-edits.edit.next-version
#[test]
fn chat_scope_uses_the_named_or_found_chat_and_project_scope_keeps_the_team() {
    let found = scope(&ScopeArg::Chat(None), Some(CHAT.into()), None)
        .unwrap_or_else(|_| panic!("synthetic scope"));
    assert_eq!(
        found,
        RevisionScope::Chat {
            chat_id: CHAT.into(),
            team_id: None
        }
    );
    assert!(matches!(
        scope(&ScopeArg::Chat(None), None, None),
        Err(CliError::Contract {
            code: "chat_unknown",
            ..
        })
    ));
    let project = scope(
        &ScopeArg::Project(PROJECT.into()),
        None,
        Some("team".into()),
    )
    .unwrap_or_else(|_| panic!("synthetic scope"));
    assert_eq!(
        project,
        RevisionScope::Project {
            project_id: PROJECT.into(),
            team_id: Some("team".into())
        }
    );
}

// contract-test: supporting surface=cli assertions=embed-user-edits.enhance.faithful-2k,embed-user-edits.edit.next-version
#[test]
fn enhance_refusals_keep_the_core_code_and_say_what_to_do() {
    let resume = format!("openmates embeds enhance {EMBED} --project {PROJECT}");
    let cases: Vec<(ImageEnhanceError, &str, &str)> = vec![
        (
            ImageEnhanceError::InsufficientCredits,
            "insufficient_credits",
            "Not enough credits",
        ),
        (
            ImageEnhanceError::TeamUnavailable,
            "team_enhance_unavailable",
            "not available for Team",
        ),
        (
            ImageEnhanceError::InvalidSource {
                code: "not_an_image",
            },
            "not_an_image",
            "not an image",
        ),
        (
            ImageEnhanceError::VersionConflict {
                current_version: Some(4),
            },
            "embed_version_conflict",
            "now version 4",
        ),
        (
            ImageEnhanceError::Failed {
                operation_id: OPERATION.into(),
                code: "safety_refused".into(),
            },
            "enhance_failed",
            "nothing was charged",
        ),
        (
            ImageEnhanceError::ProjectContextRequired,
            "project_context_required",
            "--project",
        ),
    ];
    for (error, want_code, want_text) in cases {
        match enhance_error(error, &resume) {
            CliError::Contract { code, message } => {
                assert_eq!(code, want_code);
                assert!(message.contains(want_text), "{message}");
            }
            _ => panic!("contract error expected"),
        }
    }
    match enhance_error(
        ImageEnhanceError::Timeout {
            operation_id: OPERATION.into(),
        },
        &resume,
    ) {
        CliError::Contract { code, message } => {
            assert_eq!(code, "enhance_timeout");
            assert!(
                message.contains(&format!("{resume} --resume {OPERATION}")),
                "{message}"
            );
        }
        _ => panic!("contract error expected"),
    }
}

// contract-test: supporting surface=cli assertions=embed-user-edits.enhance.faithful-2k,embed-user-edits.event.chat-notice
#[test]
fn enhance_output_names_the_new_version_and_the_chat_event() {
    let saved = ImageEnhanceSaved::Committed {
        operation_id: OPERATION.into(),
        outcome: Box::new(outcome(
            EmbedUpdateAction::Enhance,
            3,
            None,
            EventDelivery::Written,
        )),
    };
    let text = enhance_output(false, EMBED, &saved).unwrap_or_else(|_| panic!("synthetic output"));
    assert_eq!(
        text.stdout,
        format!(
            "Image enhanced: saved as version 3 of {EMBED} (about 2K, same picture).\nChat notice: written\n"
        )
    );
    let json: Value = serde_json::from_str(
        &enhance_output(true, EMBED, &saved)
            .unwrap_or_else(|_| panic!("synthetic output"))
            .stdout,
    )
    .unwrap_or_else(|_| panic!("json output"));
    assert_eq!(json["version"], 3);
    assert_eq!(json["action"], "enhance");
    assert_eq!(json["revision_origin"], "user");
    assert_eq!(json["chat_event"]["state"], "written");
    assert!(!json.to_string().contains("ciphertext"));
    let again = ImageEnhanceSaved::AlreadyCommitted {
        operation_id: OPERATION.into(),
        version: 3,
    };
    assert!(
        enhance_output(false, EMBED, &again)
            .unwrap_or_else(|_| panic!("synthetic output"))
            .stdout
            .contains("already saved as version 3")
    );
}

// contract-test: supporting surface=cli assertions=embed-user-edits.restore.creates-version,embed-user-edits.event.chat-notice
#[test]
fn restore_output_reports_a_new_version_and_a_deferred_event() {
    let restored = outcome(
        EmbedUpdateAction::Restore,
        4,
        Some(1),
        EventDelivery::Deferred {
            code: "home_chat_unavailable",
        },
    );
    let text = restore_output(false, &restored).unwrap_or_else(|_| panic!("synthetic output"));
    assert!(text.stdout.starts_with(&format!("Restored version 1 of {EMBED} as new version 4.\nChat notice: deferred (home_chat_unavailable)")));
    let json: Value = serde_json::from_str(
        &restore_output(true, &restored)
            .unwrap_or_else(|_| panic!("synthetic output"))
            .stdout,
    )
    .unwrap_or_else(|_| panic!("json output"));
    assert_eq!(
        (json["version"].as_i64(), json["restored_from"].as_i64()),
        (Some(4), Some(1))
    );
    assert_eq!(
        json["chat_event"],
        json!({"state": "deferred", "code": "home_chat_unavailable"})
    );
    match revision_error(UserRevisionError::Validation {
        code: "invalid_restored_from",
    }) {
        CliError::Contract { code, .. } => assert_eq!(code, "invalid_restored_from"),
        _ => panic!("contract error expected"),
    }
}
