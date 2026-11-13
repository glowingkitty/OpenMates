//! The CLI parses exact natural syntax; the SDK owns resolution, versions and encryption.
use super::*;
use openmates_sdk::work::{ProjectAskDelete, ProjectAskOptions, ProjectAskUpdate};
use regex::Regex;
enum Intent {
    Create {
        short: bool,
    },
    Update {
        selector: String,
        patch: ProjectPatch,
    },
    Delete {
        selector: String,
    },
}
fn pattern(value: &str) -> Regex {
    Regex::new(value).expect("constant Project ask syntax")
}
fn unquote(value: &str) -> &str {
    let value = value.trim();
    if value.len() >= 2
        && ((value.starts_with('"') && value.ends_with('"'))
            || (value.starts_with('\'') && value.ends_with('\'')))
    {
        value[1..value.len() - 1].trim()
    } else {
        value
    }
}
fn syntax(instruction: &str) -> Result<Intent, CliError> {
    let targets = pattern(r#"(?i)@project:("[^"]+"|'[^']+'|[^\s,;]+)"#);
    let matches = targets.captures_iter(instruction).collect::<Vec<_>>();
    let destructive = pattern(r"(?i)\b(delete|remove)\b").is_match(instruction);
    if matches.len() > 1 {
        return Err(CliError::Unsupported{command:"projects ask".into(),reason:"Multiple Project selectors are ambiguous; address one exact Project per instruction.".into()});
    }
    if let Some(target) = matches.first() {
        let selector = unquote(target.get(1).unwrap().as_str())
            .trim_end_matches(['.', ')', '!', '?'])
            .trim()
            .to_owned();
        if selector.is_empty() {
            return Err(CliError::Invalid(
                "Project selector must not be empty.".into(),
            ));
        }
        if destructive {
            if !pattern(r"(?i)\b(?:delete|remove)\s+(?:(?:the|this)\s+)?(?:project\s+)?@project:")
                .is_match(instruction)
            {
                return Err(CliError::Unsupported{command:"projects ask".into(),reason:"Ambiguous destructive instruction; use an exact 'delete @project:<selector>' instruction.".into()});
            }
            return Ok(Intent::Delete { selector });
        }
        let name = if pattern(r"(?i)\b(rename|retitle|title|name|call)\b").is_match(instruction) {
            pattern(r"(?i)\bto\s+(.+)$")
                .captures(instruction)
                .and_then(|capture| {
                    capture.get(1).map(|value| {
                        unquote(value.as_str())
                            .trim_end_matches('.')
                            .trim()
                            .to_owned()
                    })
                })
                .filter(|value| !value.is_empty())
        } else {
            None
        };
        let archived = if pattern(r"(?i)\bunarchive\b").is_match(instruction) {
            Some(false)
        } else if pattern(r"(?i)\barchive|archived\b").is_match(instruction) {
            Some(true)
        } else {
            None
        };
        if name.is_some() || archived.is_some() {
            return Ok(Intent::Update {
                selector,
                patch: ProjectPatch {
                    name,
                    archived,
                    ..Default::default()
                },
            });
        }
        return Err(CliError::Unsupported {
            command: "projects ask".into(),
            reason: "This exact Project instruction has no supported rename or archive operation."
                .into(),
        });
    }
    if destructive
        || pattern(r"(?i)\b(archive|unarchive|rename|name|pin|unpin|retitle|edit|update|change)\b")
            .is_match(instruction)
    {
        return Err(CliError::Unsupported{command:"projects ask".into(),reason:"Mutation instructions require one explicit @project:<selector>; ambiguous instructions do not modify Projects.".into()});
    }
    let short = !instruction.contains('\n')
        && instruction.split_whitespace().count() <= 8
        && !pattern(r"(^|\s)([-*]|\d+\.)\s").is_match(instruction);
    Ok(Intent::Create { short })
}
fn input(i: &Invocation) -> Result<(String, Intent), CliError> {
    check(
        i,
        &[
            "text",
            "description",
            "slug",
            "pinned",
            "write-policy",
            "auto-approve",
            "auto-approve-memories",
            "no-pii-detection",
            "response-timeout-seconds",
        ],
    )?;
    let positional = i.positionals.join(" ");
    let instruction = input::text(i, "text")?.unwrap_or(&positional).trim();
    if instruction.is_empty() {
        // npm requiredAskInstruction: a runtime failure (exit 1), not a usage error.
        return Err(CliError::Contract {
            code: "command_failed",
            message: "Missing ask instruction. Example: openmates projects ask \"Launch workspace\"".into(),
        });
    }
    if instruction.chars().count() > 20_000 {
        return Err(CliError::Invalid(
            "Project instructions require 1–20,000 characters.".into(),
        ));
    }
    let intent = syntax(instruction)?;
    if !matches!(intent, Intent::Create { .. }) {
        for name in ["description", "slug", "pinned", "write-policy"] {
            if i.has(name) {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason: format!(
                        "--{name} applies to Project creation; this exact mutation does not use it."
                    ),
                });
            }
        }
    }
    Ok((instruction.to_owned(), intent))
}
fn defaults(i: &Invocation, instruction: &str) -> Result<ProjectCreate, CliError> {
    let write_mode = match input::text(i, "write-policy")?.ok_or_else(|| CliError::Contract {
        code: "write_policy_required",
        message:
            "Creating a Project through ask requires --write-policy apply_and_show|always_ask."
                .into(),
    })? {
        "apply_and_show" => ProjectWriteMode::ApplyAndShow,
        "always_ask" => ProjectWriteMode::AlwaysAsk,
        _ => {
            return Err(CliError::Contract {
                code: "invalid_write_policy",
                message: "--write-policy must be apply_and_show or always_ask.".into(),
            });
        }
    };
    Ok(ProjectCreate {
        name: instruction.into(),
        description: input::text(i, "description")?.unwrap_or("").into(),
        slug: input::text(i, "slug")?.map(str::to_owned),
        pinned: i.boolean("pinned"),
        write_mode: Some(write_mode),
        ..Default::default()
    })
}
async fn resolved(service: &mut Projects<'_>, selector: &str) -> Result<String, CliError> {
    let project = service.show(selector).await?;
    let id = project["project_id"]
        .as_str()
        .filter(|id| uuid::Uuid::parse_str(id).is_ok())
        .ok_or(CliError::Client(Error::Protocol))?;
    Ok(id.to_owned())
}
pub(super) async fn run(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<(String, Value), CliError> {
    let (instruction, intent) = input(i)?;
    let options = match intent {
        Intent::Create { short } => {
            let defaults = defaults(i, &instruction)?;
            if short {
                ProjectAskOptions {
                    create: Some(defaults),
                    ..Default::default()
                }
            } else {
                ProjectAskOptions {
                    defaults,
                    ..Default::default()
                }
            }
        }
        Intent::Update { selector, patch } => ProjectAskOptions {
            update: Some(ProjectAskUpdate {
                project_id: resolved(service, &selector).await?,
                patch,
            }),
            ..Default::default()
        },
        Intent::Delete { selector } => ProjectAskOptions {
            exact_delete: Some(ProjectAskDelete {
                project_id: resolved(service, &selector).await?,
                confirmed: true,
            }),
            ..Default::default()
        },
    };
    let mut value = service.ask(&instruction, options).await?;
    if value["project"].is_object() {
        value["project"] = project_json(&value["project"])
    }
    if let Some(rows) = value["projects"].as_array() {
        value["projects"] = json!(rows.iter().map(project_json).collect::<Vec<_>>());
    }
    Ok((instruction, value))
}
#[cfg(test)]
mod tests {
    use super::*;
    fn command(text: &str, flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["projects".into(), "ask".into()],
            positionals: vec![text.into()],
            flags: flags
                .iter()
                .map(|(key, value)| (key.to_string(), value.clone()))
                .collect(),
        }
    }
    async fn deletion_fixture(found: bool) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        const ID: &str = "11111111-1111-4111-8111-111111111111";
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let mut project = json!({"project_id":ID,"version":2,"archived":false,"pinned":false,"encrypted_project_key":crate::crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap()});
        for (field, text) in [
            ("name", "Engineering"),
            ("description", "Private synthetic description"),
            ("icon", "folder"),
            ("color", "default"),
            ("slug", "engineering"),
        ] {
            project[format!("encrypted_{field}")] =
                json!(crate::crypto::encrypt_combined(text, &[9; 32]).unwrap());
        }
        let server = tokio::spawn(async move {
            for phase in 0..if found { 3 } else { 1 } {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                let mut part = [0; 4096];
                let (end, length) = loop {
                    let count = socket.read(&mut part).await.unwrap();
                    assert!(count > 0);
                    bytes.extend_from_slice(&part[..count]);
                    if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                        let header = std::str::from_utf8(&bytes[..end]).unwrap();
                        let length = header
                            .lines()
                            .filter_map(|line| line.split_once(':'))
                            .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                            .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                            .unwrap_or(0);
                        break (end + 4, length);
                    }
                };
                while bytes.len() < end + length {
                    let count = socket.read(&mut part).await.unwrap();
                    assert!(count > 0);
                    bytes.extend_from_slice(&part[..count]);
                }
                let header = std::str::from_utf8(&bytes[..end]).unwrap();
                let request = header.lines().next().unwrap();
                let response=match phase{
                    0=>{assert!(request.starts_with("GET /v1/projects?include_archived=true "));json!({"projects":if found{vec![project.clone()]}else{vec![]}})},
                    1=>{assert_eq!(request,format!("GET /v1/projects/{ID} HTTP/1.1"));project["version"]=json!(3);json!({"project":project})},
                    _=>{assert_eq!(request,"POST /v1/projects/ask HTTP/1.1");let body:Value=serde_json::from_slice(&bytes[end..end+length]).unwrap();assert_eq!(body["exact_delete"],json!({"project_id":ID,"version":3}));assert!(body.get("confirmation_project_id").is_none());assert!(body.get("encrypted_create").is_none());json!({"outcome":"applied","summary":"Deleted synthetic Project","deleted":true})},
                }.to_string();
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",
                    response.len()
                );
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        let session = openmates_sdk::Session {
            api_url: base.clone(),
            session_id: "synthetic".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let mut client = Client::new(&base, Some(session)).unwrap();
        let i = command(
            "delete @project:Engineering",
            &[("json", json!(true)), ("personal", json!(true))],
        );
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            super::super::super::execute(&i, &mut client, CancellationToken::new()),
        )
        .await
        .unwrap();
        if found {
            let output = result.ok().expect(
                "exact resolved natural deletion succeeds without an extra confirmation flag",
            );
            assert_eq!(
                serde_json::from_str::<Value>(&output.stdout).unwrap()["deleted"],
                true
            );
        } else {
            assert!(matches!(result, Err(CliError::Client(Error::Invalid(_)))));
        }
        tokio::time::timeout(std::time::Duration::from_secs(3), server)
            .await
            .unwrap()
            .unwrap();
    }
    #[tokio::test]
    async fn exact_delete_resolves_selector_and_uses_fresh_sdk_version_without_extra_confirmation()
    {
        deletion_fixture(true).await;
    }
    #[tokio::test]
    async fn unresolved_delete_stops_after_read_without_any_mutation() {
        deletion_fixture(false).await;
    }
    #[test]
    fn exact_delete_syntax_requires_one_project_target_and_never_guesses_file_deletion() {
        for text in [
            "delete @project:Engineering",
            "Please remove the project @project:'Launch workspace'",
        ] {
            assert!(matches!(syntax(text), Ok(Intent::Delete { .. })));
        }
        for text in [
            "delete old Projects",
            "delete files in @project:Engineering",
            "delete @project:Engineering or @project:Personal",
        ] {
            assert!(syntax(text).is_err());
        }
        let parsed = super::super::super::parse_from([
            "openmates",
            "projects",
            "ask",
            "delete @project:Engineering",
            "--personal",
            "--json",
        ])
        .ok()
        .unwrap();
        assert!(input(parsed.invocation.as_ref().unwrap()).is_ok());
    }
    #[test]
    fn exact_rename_unarchive_and_create_defaults_remain_typed() {
        let (_, intent) = input(&command(
            "Rename @project:'Launch workspace' to 'Native workspace'",
            &[],
        ))
        .ok()
        .unwrap();
        let Intent::Update { selector, patch } = intent else {
            panic!("expected rename")
        };
        assert_eq!(selector, "Launch workspace");
        assert_eq!(patch.name.as_deref(), Some("Native workspace"));
        let Intent::Update { patch, .. } = syntax("unarchive @project:launch").ok().unwrap() else {
            panic!("expected unarchive")
        };
        assert_eq!(patch.archived, Some(false));
        assert!(matches!(
            syntax("Launch workspace"),
            Ok(Intent::Create { short: true })
        ));
        assert!(defaults(&command("Launch workspace", &[]), "Launch workspace").is_err());
        let value = defaults(
            &command("Launch workspace", &[("write-policy", json!("always_ask"))]),
            "Launch workspace",
        )
        .ok()
        .unwrap();
        assert_eq!(
            serde_json::to_value(value.write_mode).unwrap(),
            "always_ask"
        );
        assert!(
            input(&command(
                "rename @project:launch to Native",
                &[("description", json!("unused private description"))]
            ))
            .is_err()
        );
    }
}
