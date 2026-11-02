//! CLI parsing/presentation only; encrypted link policy belongs to the SDK.
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use openmates_sdk::work::ProjectItemType;

fn arguments(i: &Invocation) -> Result<Option<(ProjectItemType, &str)>, CliError> {
    if i.positionals.len() != 1 {
        return Err(CliError::Invalid(
            "Supply exactly one Project selector.".into(),
        ));
    }
    match i.command_path().as_str() {
        "projects items list" => {
            check(i, &[])?;
            Ok(None)
        }
        "projects items remove" => {
            check(i, &["type", "target", "confirm"])?;
            let kind = match input::text(i, "type")? {
                Some("embed") => ProjectItemType::Embed,
                Some("chat") => ProjectItemType::Chat,
                Some("workflow") => ProjectItemType::Workflow,
                _ => {
                    return Err(CliError::Contract {
                        code: "invalid_item_type",
                        message: "Item type must be embed, chat, or workflow.".into(),
                    });
                }
            };
            let target = input::text(i, "target")?
                .filter(|s| !s.is_empty())
                .ok_or_else(|| CliError::Invalid("Provide --target <id>.".into()))?;
            if !i.boolean("confirm") {
                return Err(CliError::Contract {
                    code: "confirmation_required",
                    message: "Project item removal requires --confirm.".into(),
                });
            }
            Ok(Some((kind, target)))
        }
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This Project item command is not ported.".into(),
        }),
    }
}

fn list_text(value: &Value) -> String {
    let mut lines = vec![];
    for (collection, prefix, label, fallback) in [
        ("folders", Some("folder"), "name", "folder_id"),
        ("items", None, "display_name", "target_id"),
    ] {
        for row in value[collection].as_array().into_iter().flatten() {
            let kind = prefix.unwrap_or_else(|| row["type"].as_str().unwrap_or(""));
            let name = row[label]
                .as_str()
                .filter(|s| !s.is_empty())
                .or_else(|| row[fallback].as_str())
                .unwrap_or("");
            lines.push(format!("{kind}  {name}"));
        }
    }
    if lines.is_empty() {
        "No Project items.".into()
    } else {
        lines.join("\n")
    }
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    let removal = arguments(i)?;
    let selector = input::positional(i, 0, "Project ID")?;
    if let Some((kind, target)) = removal {
        let value = service.unlink_item(selector, kind, target, true).await?;
        let text = if value["deleted"] == true {
            "Project item removed."
        } else {
            "Project item was not linked."
        };
        output(i, value, text.into())
    } else {
        let value = service.items(selector).await?;
        let text = list_text(&value);
        output(i, value, text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn invocation(args: &[&str]) -> Invocation {
        super::super::super::parse_from(args.iter().copied())
            .unwrap_or_else(|error| panic!("{error}"))
            .invocation
            .unwrap()
    }
    #[test]
    fn original_selector_layout_and_unlink_flags_are_not_silently_ignored() {
        let list = invocation(&[
            "openmates",
            "projects",
            "items",
            "list",
            "engineering",
            "--personal",
            "--json",
        ]);
        assert!(supported(&list));
        assert_eq!(list.positionals, ["engineering"]);
        assert!(arguments(&list).ok().unwrap().is_none());
        let remove = invocation(&[
            "openmates",
            "projects",
            "items",
            "remove",
            "engineering",
            "--type",
            "chat",
            "--target",
            "exact-target",
            "--confirm",
            "--team",
            "ccbbccdd-1111-4111-8111-aabbccddeeff",
            "--json",
        ]);
        assert!(remove.boolean("confirm"));
        assert_eq!(arguments(&remove).ok().unwrap().unwrap().1, "exact-target");
        for (flag, value) in [
            ("confirm", json!(false)),
            ("type", json!("upload")),
            ("type", json!(["chat", "embed"])),
            ("target", json!(true)),
            ("limit", json!(1)),
        ] {
            let mut bad = Invocation {
                path: remove.path.clone(),
                positionals: remove.positionals.clone(),
                flags: remove.flags.clone(),
            };
            bad.flags.insert(flag.into(), value);
            assert!(arguments(&bad).is_err());
        }
    }
    #[test]
    fn legacy_output_preserves_raw_ids_nulls_and_terminal_safety() {
        let mut i = invocation(&[
            "openmates",
            "projects",
            "items",
            "list",
            "engineering",
            "--json",
        ]);
        let value = json!({"project_id":"canonical","folders":[{"folder_id":"folder","parent_folder_id":null,"name":"","position":0}],"items":[{"project_item_id":"link","type":"chat","target_id":"target","display_name":"Private\u{1b}[31mname","ownership_label":null,"position":2}]});
        let result = output(&i, value.clone(), list_text(&value)).ok().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&result.stdout).unwrap(),
            value
        );
        i.flags.remove("json");
        let text = output(&i, value.clone(), list_text(&value))
            .ok()
            .unwrap()
            .stdout;
        assert_eq!(text, "folder  folder\nchat  Private\\u001b[31mname\n");
        assert_eq!(
            list_text(&json!({"folders":[],"items":[]})),
            "No Project items."
        );
    }
    #[test]
    fn confirmation_arity_keeps_boolean_unlink_and_exact_project_delete_distinct() {
        for flags in [
            vec!["--confirm"],
            vec!["--confirm=true"],
            vec!["--confirm", "true"],
        ] {
            let mut args = vec![
                "openmates",
                "projects",
                "items",
                "remove",
                "engineering",
                "--type",
                "chat",
                "--target",
                "target",
            ];
            args.extend(flags);
            let i = invocation(&args);
            assert!(i.boolean("confirm"));
            assert!(arguments(&i).is_ok());
        }
        let ordered = invocation(&[
            "openmates",
            "projects",
            "--confirm=true",
            "items",
            "remove",
            "engineering",
            "--target",
            "target",
            "--type",
            "chat",
        ]);
        assert!(arguments(&ordered).is_ok());
        for args in [
            vec![
                "openmates",
                "projects",
                "items",
                "remove",
                "engineering",
                "--type",
                "chat",
                "--target",
                "target",
            ],
            vec![
                "openmates",
                "projects",
                "items",
                "remove",
                "engineering",
                "--type",
                "chat",
                "--target",
                "target",
                "--confirm=false",
            ],
        ] {
            assert_eq!(
                arguments(&invocation(&args)).err().unwrap().code(),
                "confirmation_required"
            );
        }
        let id = "bbaaccdd-1111-4111-8111-aabbccddeeff";
        let deletion = invocation(&["openmates", "projects", "delete", id, "--confirm", id]);
        assert_eq!(input::text(&deletion, "confirm").ok().unwrap(), Some(id));
        assert!(!deletion.boolean("confirm"));
        // A bare value is not an exact-ID confirmation for Project deletion.
        let omitted = invocation(&["openmates", "projects", "delete", id, "--confirm"]);
        assert_ne!(input::text(&omitted, "confirm").ok().unwrap(), Some(id));
        let false_value = invocation(&["openmates", "projects", "delete", id, "--confirm=false"]);
        assert_eq!(
            input::text(&false_value, "confirm").ok().unwrap(),
            Some("false")
        );
    }
}
