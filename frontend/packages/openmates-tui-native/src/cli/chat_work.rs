//! Legacy chat-scoped work aliases. Only syntax is adapted here: the existing
//! Tasks/Plans dispatcher owns auth, selectors, validation, delivery and output.
//! Provenance: cli.ts handleChats delegates with { ...flags, chat: subcommand }.
use super::{CliError, Invocation};
use serde_json::Value;

pub(super) fn supported(invocation: &Invocation) -> bool {
    let [family, namespace, action] = invocation.path.as_slice() else {
        return false;
    };
    family == "chats"
        && match namespace.as_str() {
            "tasks" => matches!(action.as_str(), "list" | "board" | "create"),
            "plans" => matches!(action.as_str(), "list" | "create" | "approve"),
            _ => false,
        }
}

/// Preserve the legacy positional-chat precedence, including over a supplied
/// --chat. Do not resolve/trim selectors or reject flags on behalf of the
/// delegated handler. Eligibility of Cookie/API-key dispatch remains the
/// application's responsibility; normalization does not grant a capability.
pub fn normalize(invocation: &Invocation) -> Result<Option<Invocation>, CliError> {
    if !supported(invocation) {
        return Ok(None);
    }
    let chat = invocation
        .positionals
        .first()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| CliError::Invalid("Missing chat selector for chat-scoped work.".into()))?;
    let mut flags = invocation.flags.clone();
    flags.insert("chat".into(), Value::String(chat.clone()));
    Ok(Some(Invocation {
        path: invocation.path[1..].to_vec(),
        positionals: invocation.positionals[1..].to_vec(),
        flags,
    }))
}

#[cfg(test)]
mod tests {
    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    use super::*;
    use serde_json::json;
    use std::collections::BTreeMap;

    fn invocation(namespace: &str, action: &str, positionals: &[&str]) -> Invocation {
        Invocation {
            path: ["chats", namespace, action]
                .into_iter()
                .map(str::to_owned)
                .collect(),
            positionals: positionals.iter().map(|value| (*value).into()).collect(),
            flags: BTreeMap::new(),
        }
    }

    fn normalized(value: &Invocation) -> Invocation {
        normalize(value)
            .unwrap_or_else(|error| panic!("{error}"))
            .expect("recognized chat work alias")
    }

    #[test]
    fn all_six_parser_namespaces_delegate_without_changing_tail_positionals() {
        for (namespace, action) in [
            ("tasks", "list"),
            ("tasks", "board"),
            ("tasks", "create"),
            ("plans", "list"),
            ("plans", "create"),
            ("plans", "approve"),
        ] {
            let mut arguments = vec!["openmates", "chats", "chat-selector", namespace, action];
            if action == "approve" {
                arguments.push("PLAN-12");
            }
            let parsed = super::super::parse_from(arguments)
                .unwrap_or_else(|error| panic!("{error}"))
                .invocation
                .expect("chat work parser invocation");
            assert!(supported(&parsed));
            assert_eq!(parsed.path, ["chats", namespace, action]);
            assert_eq!(parsed.positionals[0], "chat-selector");
            let delegated = normalized(&parsed);
            assert_eq!(delegated.path, [namespace, action]);
            assert_eq!(delegated.text("chat"), Some("chat-selector"));
            assert_eq!(delegated.positionals, parsed.positionals[1..]);
        }
    }

    #[test]
    fn real_parser_preserves_variadic_positional_titles_for_create_aliases() {
        for namespace in ["tasks", "plans"] {
            let parsed = super::super::parse_from([
                "openmates",
                "chats",
                "chat-selector",
                namespace,
                "create",
                "Quoted title",
                "continued",
                "--json",
            ])
            .unwrap_or_else(|error| panic!("{error}"))
            .invocation
            .expect("chat-scoped create invocation");
            assert_eq!(
                parsed.positionals,
                ["chat-selector", "Quoted title", "continued"]
            );
            let delegated = normalized(&parsed);
            assert_eq!(delegated.path, [namespace, "create"]);
            assert_eq!(delegated.text("chat"), Some("chat-selector"));
            assert_eq!(delegated.positionals, ["Quoted title", "continued"]);
            assert!(delegated.boolean("json"));
        }
    }

    #[test]
    fn positional_selector_wins_and_all_other_flags_are_preserved() {
        let mut original = invocation("tasks", "create", &["unresolved-chat-slug", "quoted title"]);
        original.flags = BTreeMap::from([
            ("chat".into(), json!(["overridden", "also-overridden"])),
            ("title".into(), json!("Explicit title")),
            ("label".into(), json!(["backend", "privacy"])),
            ("project".into(), json!("engineering")),
            ("external-chat".into(), json!("codex:synthetic-thread")),
            ("team".into(), json!("explicit-team")),
            ("personal".into(), json!(false)),
            ("profile".into(), json!("codex-personal")),
            ("api-key".into(), json!("synthetic-credential")),
            ("delivery-id".into(), json!("a".repeat(64))),
            ("json".into(), json!(true)),
            ("unsupported-option".into(), json!("callee-must-reject")),
        ]);
        let delegated = normalized(&original);
        assert_eq!(delegated.positionals, ["quoted title"]);
        assert_eq!(delegated.text("chat"), Some("unresolved-chat-slug"));
        for (name, value) in &original.flags {
            if name != "chat" {
                assert_eq!(delegated.flags.get(name), Some(value));
            }
        }
        // No external owner, unsupported option, conflicting scope or API-key
        // grant is accepted here. The original typed dispatcher must validate it.
        assert_eq!(
            original.flags["chat"],
            json!(["overridden", "also-overridden"])
        );
        assert_eq!(
            original.positionals,
            ["unresolved-chat-slug", "quoted title"]
        );
        assert_eq!(original.path, ["chats", "tasks", "create"]);
    }

    #[test]
    fn raw_selector_and_approve_target_are_not_rewritten_or_pre_resolved() {
        let original = invocation("plans", "approve", &[" chat-selector ", "PLAN-42"]);
        let delegated = normalized(&original);
        assert_eq!(delegated.text("chat"), Some(" chat-selector "));
        assert_eq!(delegated.positionals, ["PLAN-42"]);
        let missing_plan = invocation("plans", "approve", &["chat-selector"]);
        assert!(normalized(&missing_plan).positionals.is_empty());
    }

    #[test]
    fn missing_chat_is_invalid_and_other_paths_are_not_claimed() {
        for positionals in [&[][..], &[""][..], &[" \t"][..]] {
            let missing = invocation("tasks", "list", positionals);
            assert!(matches!(normalize(&missing), Err(CliError::Invalid(_))));
        }
        for (namespace, action) in [
            ("tasks", "delete"),
            ("tasks", "watch"),
            ("plans", "show"),
            ("plans", "activate"),
            ("projects", "create"),
        ] {
            let other = invocation(namespace, action, &["chat"]);
            assert!(!supported(&other));
            assert!(
                normalize(&other)
                    .unwrap_or_else(|error| panic!("{error}"))
                    .is_none()
            );
        }
        let mut other = invocation("tasks", "list", &["chat"]);
        other.path.remove(0);
        assert!(!supported(&other));
        assert!(
            normalize(&other)
                .unwrap_or_else(|error| panic!("{error}"))
                .is_none()
        );
        other.path = vec![
            "chats".into(),
            "tasks".into(),
            "list".into(),
            "extra".into(),
        ];
        assert!(!supported(&other));
    }

    #[tokio::test]
    async fn alias_and_explicit_chat_commands_have_the_same_real_journal_intent() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().expect("private unit directory");
        let store =
            crate::runtime_store::RuntimeStore::new(Some(directory.path().to_owned()), true)
                .await
                .expect("synthetic native store");
        let journal = crate::task_delivery::Journal::new(
            store,
            "synthetic-owner".into(),
            r#"["https://api.example.test",null]"#.into(),
            zeroize::Zeroizing::new([7; 32]),
        );
        let mut alias = invocation("tasks", "create", &["chat-selector"]);
        alias.flags = BTreeMap::from([
            ("title".into(), json!("Synthetic title")),
            ("project".into(), json!("engineering")),
            ("delivery-id".into(), json!("a".repeat(64))),
            ("chat".into(), json!("ignored-selector")),
        ]);
        let delegated = normalized(&alias);
        let canonical = Invocation {
            path: vec!["tasks".into(), "create".into()],
            positionals: vec![],
            flags: BTreeMap::from([
                ("title".into(), json!("Synthetic title")),
                ("project".into(), json!("engineering")),
                ("delivery-id".into(), json!("a".repeat(64))),
                ("chat".into(), json!("chat-selector")),
            ]),
        };
        let intent = journal.intent(&delegated).expect("alias intent");
        assert_eq!(
            intent,
            journal.intent(&canonical).expect("canonical intent")
        );
        alias.positionals[0] = "different-chat".into();
        assert_ne!(
            intent,
            journal
                .intent(&normalized(&alias))
                .expect("different chat intent")
        );
    }
}
