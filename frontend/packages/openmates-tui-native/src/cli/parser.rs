use super::*;
use clap::{Arg, ArgAction, ArgMatches, Command, error::ErrorKind};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
};
#[derive(Default)]
struct Node {
    name: String,
    children: BTreeMap<String, Node>,
    records: Vec<usize>,
    flags: BTreeSet<String>,
    context: usize,
}
const GLOBALS: &[&str] = &[
    "json",
    "profile",
    "api-url",
    "api-key",
    "state-dir",
    "encrypted-vault",
    "demo",
];
fn switch(name: &str, family: &str) -> bool {
    catalog()
        .flags
        .iter()
        .find(|flag| flag.long == name)
        .is_some_and(|flag| flag.arity_overrides.get(family).unwrap_or(&flag.arity) == "switch")
}
fn presence_value(name: &str, family: &str) -> bool {
    catalog().flags.iter().find(|flag| flag.long == name)
        .and_then(|flag| flag.arity_overrides.get(family))
        .is_some_and(|arity| arity == "optional_value_presence")
}
const PRESENT: &str = "\0openmates_presence";
fn presence_scalar(values: &[String]) -> Value {
    let mut current = Value::Null;
    for value in values {
        if value == PRESENT { current = Value::Bool(true); }
        else {
            let text = current.as_str().filter(|text| !text.is_empty())
                .map(|previous| format!("{previous}\n{value}")).unwrap_or_else(|| value.clone());
            current = Value::String(text);
        }
    }
    current
}
fn flag(name: &str, family: &str, global: bool) -> Arg {
    let boolean = switch(name, family);
    let mut arg = Arg::new(name.to_owned())
        .long(name.to_owned())
        .global(global)
        .action(ArgAction::Append)
        .value_parser(clap::builder::StringValueParser::new());
    arg = match name {
        "profile" => arg.help("Account profile; server commands use this as the Compose profile"),
        "server-profile" => arg.help("Explicit Compose profile for server commands"),
        "api-key" => arg.help("Explicit API setup credential (never mixed with a cookie session)"),
        "state-dir" => arg.help("Isolated native state directory"),
        _ => arg,
    };
    // Projects mixes exact-ID deletion confirmation and boolean item unlink.
    // Keep the original value syntax while allowing bare --confirm for items;
    // each typed handler still validates its own required confirmation.
    if name == "confirm" && family == "projects" {
        arg = arg.num_args(0..=1).default_missing_value("true");
    } else if presence_value(name, family) {
        // Bare presence is distinct from every explicit scalar, including
        // "true". The scoped adapter normalizes separated values to equals.
        arg = arg.num_args(0..=1).require_equals(true).default_missing_value(PRESENT);
    } else if boolean {
        arg = arg
            .num_args(0..=1)
            .require_equals(true)
            .default_missing_value("true")
            .value_parser(["true", "false"]);
    } else if catalog()
        .flags
        .iter()
        .find(|flag| flag.long == name)
        .and_then(|flag| flag.arity_overrides.get(family))
        .is_some_and(|arity| arity == "optional_value_clear")
    {
        arg = arg
            .num_args(0..=1)
            .default_missing_value("\0openmates_clear");
    } else {
        arg = arg.num_args(1).allow_negative_numbers(true);
    }
    arg
}
fn tree() -> Node {
    let mut root = Node::default();
    for (i, record) in catalog().commands.iter().enumerate() {
        let mut node = &mut root;
        for (depth, name) in record.path.iter().enumerate() {
            node = node.children.entry(name.clone()).or_insert_with(|| Node {
                name: name.clone(),
                ..Default::default()
            });
            if record
                .positionals
                .iter()
                .any(|p| p.at == depth + 1 && p.at < record.path.len())
            {
                node.context = 1;
            }
            if depth == 0 {
                node.flags.extend(
                    catalog()
                        .family_flags
                        .get(name)
                        .into_iter()
                        .flatten()
                        .filter(|n| {
                            !GLOBALS.contains(&n.as_str())
                                && n.as_str() != "help"
                                && n.as_str() != "version"
                        })
                        .cloned(),
                );
            }
        }
        node.records.push(i);
        node.flags.extend(
            record
                .flags
                .iter()
                .filter(|n| !GLOBALS.contains(&n.as_str()) && n.as_str() != "help")
                .cloned(),
        );
    }
    // The original Plans Task delegation has two selectors before its action:
    // plans tasks <task-id> <plan-id> add-to-project <project-id>.
    // Model them as positional arguments so Clap still owns option arity,
    // subcommand recognition and the `--` boundary.
    root.children
        .get_mut("plans")
        .and_then(|plans| plans.children.get_mut("tasks"))
        .expect("The catalog declares Plans Task commands")
        .context = 2;
    root
}
fn build(node: &Node, family: &str, inherited: &BTreeSet<String>) -> Command {
    let mut command = Command::new(node.name.clone())
        .disable_version_flag(true)
        .disable_help_subcommand(true)
        .subcommand_precedence_over_arg(true)
        .subcommand_negates_reqs(true)
        .allow_missing_positional(node.context != 2);
    let mut inherited = inherited.clone();
    if let Some(record) = node.records.first().map(|i| &catalog().commands[*i]) {
        command = command.about(record.summary.clone()).long_about(format!(
            "{}\n\nUsage from the existing CLI:\n  openmates {}\n\nNative implementation: {}",
            record.summary,
            record.usages.join("\n  openmates "),
            record.implementation.status
        ));
    }
    for name in &node.flags {
        if !inherited.contains(name) {
            command = command.arg(flag(name, family, true));
            inherited.insert(name.clone());
        }
    }
    if node.context > 0 {
        command = command.arg(
            Arg::new("_context")
                .value_name("CONTEXT_ID")
                .num_args(1)
                .required(false),
        );
    }
    if node.context == 2 {
        command = command.arg(
            Arg::new("_plan_context")
                .value_name("PLAN_ID")
                .num_args(1)
                .required(false),
        );
    }
    // This contextual group accepts exactly Task and Plan before its action.
    // A trailing optional vararg would let Clap's missing-positional support
    // skip the Plan selector into that catch-all instead of binding its role.
    if node.context != 2 {
        command = command.arg(
            Arg::new("_arguments")
                .value_name("ARGUMENTS")
                .num_args(0..)
                .action(ArgAction::Append),
        );
    }
    for child in node.children.values() {
        command = command.subcommand(build(child, family, &inherited));
    }
    command
}
pub fn command() -> Command {
    let root = tree();
    debug_assert!(
        catalog()
            .global_flags
            .iter()
            .all(|flag| flag == "help" || GLOBALS.contains(&flag.as_str()))
    );
    let mut command=Command::new("openmates").about("OpenMates native Rust CLI and terminal UI").disable_version_flag(true).disable_help_subcommand(true).subcommand_precedence_over_arg(true).after_help("No command starts the native TUI on an interactive terminal. Unported operations fail explicitly; the existing CLI is preserved.");
    let mut inherited = BTreeSet::new();
    for name in GLOBALS {
        command = command.arg(flag(name, "", true));
        inherited.insert((*name).into());
    }
    command = command.arg(
        Arg::new("version")
            .long("version")
            .short('v')
            .num_args(0..=1)
            .require_equals(true)
            .default_missing_value("true")
            .action(ArgAction::Append),
    );
    for child in root.children.values() {
        command = command.subcommand(build(child, &child.name, &inherited));
    }
    command
}
fn collect(
    matches: &ArgMatches,
    path: &mut Vec<String>,
    positionals: &mut Vec<String>,
    flags: &mut BTreeMap<String, Value>,
    plan_task_selectors: &mut Option<[String; 2]>,
) {
    if path == &["plans", "tasks"] {
        let task = matches.get_one::<String>("_context");
        let plan = matches.get_one::<String>("_plan_context");
        if task.is_some() || plan.is_some() {
            *plan_task_selectors = Some([
                task.cloned().unwrap_or_default(),
                plan.cloned().unwrap_or_default(),
            ]);
        }
    }
    for id in matches.ids() {
        let key = id.as_str();
        if key == "_plan_context" || key == "_context" && path == &["plans", "tasks"] {
            continue;
        }
        if key == "_arguments" || key == "_context" {
            if let Ok(Some(values)) = matches.try_get_many::<String>(key) {
                positionals.extend(values.cloned());
            }
        } else if key != "help"
            && let Ok(Some(values)) = matches.try_get_many::<String>(key)
        {
            let values = values.cloned().collect::<Vec<_>>();
            let family = path.first().map(String::as_str).unwrap_or("");
            let value = if presence_value(key, family) {
                presence_scalar(&values)
            } else if switch(key, family) {
                json_boolean(values.last().unwrap())
            } else if values.len() == 1 {
                if values[0] == "\0openmates_clear" {
                    Value::Null
                } else {
                    Value::String(values[0].clone())
                }
            } else {
                Value::Array(values.into_iter().map(Value::String).collect())
            };
            flags.insert(key.into(), value);
        }
    }
    if let Some((name, child)) = matches.subcommand() {
        path.push(name.into());
        collect(child, path, positionals, flags, plan_task_selectors);
    }
}
fn json_boolean(value: &str) -> Value {
    Value::Bool(value == "true")
}
fn parse_error(message: impl Into<String>) -> clap::Error {
    clap::Error::raw(ErrorKind::InvalidValue, message.into())
}
/// Validate the declared hierarchy without touching credentials or a network.
pub fn parse_from<I, T>(arguments: I) -> Result<ParsedCli, clap::Error>
where
    I: IntoIterator<Item = T>,
    T: Into<OsString> + Clone,
{
    let mut arguments = arguments
        .into_iter()
        .map(Into::into)
        .collect::<Vec<OsString>>();
    // Real exec argv cannot contain NUL. Enforce that same boundary for public
    // parse_from callers before private capture/default markers are introduced;
    // never echo a rejected argument, which may contain a credential.
    if arguments.iter().any(|argument| argument.as_encoded_bytes().contains(&0)) {
        return Err(parse_error("Command arguments must not contain NUL bytes."));
    }
    for argument in &mut arguments {
        if argument == "-version" {
            *argument = "--version".into();
        }
    }
    if arguments.get(1).is_some_and(|arg| arg == "help") {
        arguments.remove(1);
        arguments.push("--help".into());
    }
    let mut history_scalars = super::global_history::normalize_history_arguments(&mut arguments);
    super::drafts::normalize_refresh_arguments(&mut arguments);
    let contains_secret = arguments.iter().any(|argument| {
        let argument = argument.to_string_lossy();
        catalog().flags.iter().any(|flag| {
            flag.sensitive
                && (argument == format!("--{}", flag.long)
                    || argument.starts_with(&format!("--{}=", flag.long)))
        })
    });
    // Global values must be supplied once even across subcommand boundaries:
    // Clap propagates the deepest global match and can replace an earlier one.
    // This checks only registered option spellings, never rewrites argv, and
    // leaves everything after `--` as literal positional data.
    let duplicate_global_value = GLOBALS.iter().filter(|name| !switch(name, "")).any(|name| {
        let spelling = format!("--{name}");
        let assigned = format!("{spelling}=");
        arguments
            .iter()
            .skip(1)
            .take_while(|argument| argument.as_os_str() != "--")
            .filter(|argument| {
                let argument = argument.to_string_lossy();
                argument == spelling || argument.starts_with(&assigned)
            })
            .take(2)
            .count()
            == 2
    });
    let matches = command().try_get_matches_from(arguments).map_err(|error| {
        if contains_secret && !matches!(error.kind(), ErrorKind::DisplayHelp | ErrorKind::DisplayVersion) {
            clap::Error::raw(error.kind(), "Invalid command arguments. Sensitive option values were omitted; use --help for this command.")
        } else { error }
    })?;
    if duplicate_global_value {
        return Err(parse_error("Global value options must be supplied once."));
    }
    let mut path = vec![];
    let mut positionals = vec![];
    let mut flags = BTreeMap::new();
    let mut plan_task_selectors = None;
    collect(
        &matches,
        &mut path,
        &mut positionals,
        &mut flags,
        &mut plan_task_selectors,
    );
    // Draft reads accept presence-style refresh, but the existing clear mutation
    // deliberately rejects that option before credentials or transport are used.
    if path == ["drafts", "clear"] && flags.contains_key("refresh") {
        return Err(parse_error("Draft clearing does not accept --refresh."));
    }
    if path.first().is_some_and(|family| family == "history")
        && let Some(capture) = history_scalars.as_mut()
    {
        capture.apply(&mut flags);
    }
    if let Some([task_id, plan_id]) = plan_task_selectors {
        if task_id.is_empty()
            || plan_id.is_empty()
            || path.len() != 3
            || path[..2] != ["plans", "tasks"]
            || !matches!(path[2].as_str(), "add-to-project" | "remove-from-project")
            || positionals.len() != 1
        {
            return Err(parse_error(
                "Expected 'plans tasks <task-id> <plan-id> add-to-project|remove-from-project <project-id>'.",
            ));
        }
        // The delegated handler's stable order is Plan, Task, Project.
        positionals.splice(0..0, [plan_id, task_id]);
    }
    if GLOBALS
        .iter()
        .any(|name| flags.get(*name).is_some_and(Value::is_array))
    {
        return Err(parse_error("Global value options must be supplied once."));
    }
    let take = |name: &str| flags.get(name).and_then(Value::as_str).map(str::to_owned);
    let boolean = |name: &str| {
        flags
            .get(name)
            .is_some_and(|v| v == true || v.as_str() == Some("true"))
    };
    let globals = GlobalArgs {
        demo: boolean("demo"),
        api_url: take("api-url"),
        state_dir: take("state-dir").map(PathBuf::from),
        encrypted_vault: boolean("encrypted-vault"),
        profile: take("profile"),
        json: boolean("json"),
        api_key: take("api-key").map(Zeroizing::new),
    };
    let version_requested = path.is_empty() && flags.contains_key("version");
    if !path.is_empty()
        && let Some(record) = record(&path)
    {
        let mut required = BTreeSet::new();
        for p in &record.positionals {
            if p.required {
                required.insert((p.at, p.name.as_str()));
            }
        } // Alternate synopsis variants can make positional prompts optional (for example --followup).
        let minimum = if record
            .usages
            .iter()
            .any(|u| !u.contains('<') && !u.contains('['))
        {
            0
        } else {
            required.len()
        };
        // The preserved TypeScript sources-list handler owns its first selector:
        // absent/blank values produce command_failed + exit1; later positional
        // values are ignored. Keep other commands' parser arity unchanged.
        let project_source_selector = path.as_slice() == ["projects", "sources", "list"]
            // npm `projects ask` reports its own "Missing ask instruction" (exit 1).
            || path.as_slice() == ["projects", "ask"];
        if positionals.len() < minimum
            && !flags.contains_key("followup")
            && !project_source_selector
        {
            // Distinct kind so main.rs can exit 1 like the npm CLI (clap would use 2).
            // npm spells out the usage line for these two commands only.
            let message = match path.as_slice() {
                [a, b] if a == "chats" && b == "search" => {
                    "Missing search query. Usage: openmates chats search <query>".to_string()
                }
                [a, b] if a == "chats" && b == "delete" => {
                    "Missing chat IDs. Usage: openmates chats delete <id1> [id2] [id3] ...".to_string()
                }
                _ => format!(
                    "Missing positional argument for '{}'. Run 'openmates {} --help'.",
                    path.join(" "),
                    path.join(" ")
                ),
            };
            return Err(clap::Error::raw(ErrorKind::MissingRequiredArgument, message));
        }
        // A bare `...` usage token repeats the preceding positional, as in
        // `chats delete <id1> [id2] [id3] ... [--yes]` (TS accepts any count).
        let open_text = record.skill_schema.is_some()
            || record.usages.iter().any(|usage| usage.split_whitespace().any(|token| token == "..."))
            || record.positionals.iter().any(|p| {
                p.variadic || ["message", "text", "query", "prompt"].contains(&p.name.as_str())
            });
        let maximum = record
            .positionals
            .iter()
            .map(|p| p.at)
            .collect::<BTreeSet<_>>()
            .len();
        let is_group = catalog().commands.iter().any(|candidate| {
            candidate.path.len() > path.len() && candidate.path.starts_with(&path)
        });
        if is_group
            && maximum == 0
            && !positionals.is_empty()
            && path.first().is_none_or(|p| p != "apps")
        {
            return Err(parse_error(format!(
                "Unknown subcommand for '{}'. Use --help to see declared commands.",
                path.join(" ")
            )));
        }
        if !open_text && maximum > 0 && positionals.len() > maximum && !project_source_selector {
            return Err(parse_error(format!(
                "Too many positional arguments for '{}'. Use --help to see its usage.",
                path.join(" ")
            )));
        }
    }
    let invocation = if path.is_empty() {
        None
    } else {
        Some(Invocation {
            path,
            positionals,
            flags,
        })
    };
    Ok(ParsedCli {
        globals,
        invocation,
        version_requested,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn complete_inventory_help_tree_builds() {
        command().debug_assert();
        assert!(catalog().commands.len() > 500);
    }
    #[test]
    fn bounded_installer_log_diagnostics_reach_native_log_options() {
        let parsed = parse_from([
            "openmates",
            "server",
            "logs",
            "--path",
            "/tmp/isolated-install",
            "--tail",
            "80",
            "--since",
            "10m",
            "--timestamps",
        ])
        .unwrap();
        let invocation = parsed.invocation.unwrap();
        assert_eq!(invocation.command_path(), "server logs");
        assert_eq!(invocation.text("tail"), Some("80"));
        assert_eq!(invocation.text("since"), Some("10m"));
        assert!(invocation.boolean("timestamps"));
    }
    #[test]
    fn nested_paths_repeated_flags_and_contextual_ids_parse() {
        let parsed = parse_from([
            "openmates",
            "tasks",
            "activity",
            "list",
            "OM-6",
            "--max-entries",
            "20",
            "--json",
        ])
        .unwrap();
        let invocation = parsed.invocation.unwrap();
        assert_eq!(invocation.path, ["tasks", "activity", "list"]);
        assert_eq!(invocation.positionals, ["OM-6"]);
        assert_eq!(invocation.text("max-entries"), Some("20"));
        assert!(invocation.boolean("json"));
        let parsed = parse_from(["openmates", "chats", "chat-id", "tasks", "list"]).unwrap();
        assert_eq!(parsed.invocation.as_ref().unwrap().positionals, ["chat-id"]);
    }
    #[test]
    fn server_full_hierarchy_and_generated_skills_are_declared() {
        for args in [
            vec!["openmates", "server", "ai", "models", "list"],
            vec![
                "openmates",
                "server",
                "env",
                "set",
                "KEY",
                "--value",
                "text",
            ],
            vec![
                "openmates",
                "apps",
                "web",
                "search",
                "query",
                "--count",
                "3",
            ],
        ] {
            assert!(parse_from(args).is_ok());
        }
    }
    #[test]
    fn help_is_local_and_unknown_commands_and_flags_fail() {
        let error = parse_from(["openmates", "server", "env", "--help"])
            .err()
            .unwrap();
        assert_eq!(error.kind(), ErrorKind::DisplayHelp);
        assert!(parse_from(["openmates", "definitely-unknown"]).is_err());
        assert!(parse_from(["openmates", "tasks", "list", "--definitely-unknown"]).is_err());
    }
    #[test]
    fn chats_delete_accepts_any_number_of_ids_like_typescript() {
        let ids = ["a1", "b2", "c3", "d4", "e5"];
        let parsed = parse_from(["openmates", "chats", "delete"].into_iter().chain(ids).chain(["--yes"])).unwrap();
        assert_eq!(parsed.invocation.unwrap().positionals, ids);
        // Fixed-arity commands still refuse extra positionals.
        assert!(parse_from(["openmates", "chats", "show", "a1", "b2"]).is_err());
    }
    #[test]
    fn version_alias_and_profile_are_native() {
        let parsed = parse_from(["openmates", "-version"]).unwrap();
        assert!(parsed.version_requested);
        let parsed =
            parse_from(["openmates", "--profile", "isolated", "whoami", "--json"]).unwrap();
        assert_eq!(parsed.globals.profile.as_deref(), Some("isolated"));
        assert!(parsed.globals.json);
    }
    #[test]
    fn repeated_values_remain_ordered_and_repeated_switches_use_last_value() {
        let parsed = parse_from([
            "openmates",
            "tasks",
            "list",
            "--json",
            "--json=false",
            "--project",
            "first",
            "--project",
            "second",
        ])
        .unwrap();
        let invocation = parsed.invocation.unwrap();
        assert!(!invocation.boolean("json"));
        assert_eq!(invocation.values("project"), ["first", "second"]);
        assert!(
            parse_from([
                "openmates",
                "--api-url",
                "https://one.example",
                "--api-url",
                "https://two.example",
                "whoami"
            ])
            .is_err()
        );
    }
    #[test]
    fn sensitive_argument_errors_never_echo_values() {
        let error = parse_from([
            "openmates",
            "chats",
            "share",
            "chat-id",
            "--password",
            "private-password",
            "--unknown",
        ])
        .err()
        .unwrap();
        assert!(!error.to_string().contains("private-password"));
    }
    #[test]
    fn group_typoes_and_excess_identifiers_fail_before_credentials() {
        assert!(parse_from(["openmates", "tasks", "definitely-misspelled"]).is_err());
        assert!(parse_from(["openmates", "tasks", "show", "one", "two"]).is_err());
        assert!(
            parse_from([
                "openmates",
                "plans",
                "tasks",
                "activity",
                "plan-id",
                "list",
                "task-id"
            ])
            .is_ok()
        );
    }
    #[test]
    fn every_catalog_command_has_native_help() {
        let command = command();
        for record in &catalog().commands {
            let mut arguments = vec!["openmates".to_owned()];
            arguments.extend(record.path.clone());
            arguments.push("--help".into());
            assert_eq!(
                command
                    .clone()
                    .try_get_matches_from(arguments)
                    .err()
                    .unwrap()
                    .kind(),
                ErrorKind::DisplayHelp,
                "{}",
                record.path.join(" ")
            );
        }
    }
    #[test]
    fn server_profile_preserves_legacy_family_meaning_and_flag_placement() {
        for arguments in [
            vec!["openmates", "--profile", "minimal", "server", "status"],
            vec!["openmates", "server", "status", "--profile", "minimal"],
        ] {
            let parsed = parse_from(arguments).unwrap();
            assert_eq!(
                parsed.invocation.as_ref().unwrap().text("profile"),
                Some("minimal")
            );
        }
        let parsed = parse_from([
            "openmates",
            "server",
            "start",
            "--server-profile",
            "production",
        ])
        .unwrap();
        assert_eq!(
            parsed.invocation.as_ref().unwrap().text("server-profile"),
            Some("production")
        );
    }
    #[test]
    fn task_edit_supports_explicit_clear_and_preserves_literal_identifiers() {
        let parsed = parse_from([
            "openmates",
            "tasks",
            "edit",
            "TASK-4",
            "--chat",
            "--plan",
            "--description",
            "",
        ])
        .unwrap();
        let invocation = parsed.invocation.unwrap();
        assert_eq!(invocation.flags["chat"], Value::Null);
        assert_eq!(invocation.flags["plan"], Value::Null);
        assert_eq!(invocation.text("description"), Some(""));
        let parsed =
            parse_from(["openmates", "tasks", "edit", "TASK-4", "--chat", "chat-id"]).unwrap();
        assert_eq!(parsed.invocation.unwrap().text("chat"), Some("chat-id"));
    }
    #[test]
    fn task_positional_title_comment_and_legacy_restore_target_fallbacks_parse() {
        for arguments in [
            vec!["openmates", "tasks", "create", "An", "unquoted", "title"],
            vec![
                "openmates",
                "tasks",
                "activity",
                "add",
                "TASK-4",
                "Milestone",
                "saved",
            ],
            vec!["openmates", "tasks", "restore", "TASK-4", "history-entry"],
            vec![
                "openmates",
                "tasks",
                "dependencies",
                "add",
                "TASK-4",
                "plan:plan-id",
            ],
        ] {
            assert!(parse_from(arguments).is_ok());
        }
    }
    #[test]
    fn task_ask_accepts_flag_and_positional_instructions() {
        assert!(parse_from(["openmates", "tasks", "ask", "--text", "Prepare launch copy"]).is_ok());
        assert!(parse_from(["openmates", "tasks", "ask", "Prepare", "launch", "copy"]).is_ok());
    }
    #[test]
    fn project_ask_without_instruction_reaches_the_npm_style_handler_error() {
        // The handler, not the arity check, owns npm's exit-1 "Missing ask instruction".
        assert!(parse_from(["openmates", "projects", "ask"]).is_ok());
    }
    #[test]
    fn plan_confirm_and_nullable_link_flags_keep_command_specific_arity() {
        let parsed = parse_from(["openmates", "plans", "delete", "PLAN-4", "--confirm"]).unwrap();
        assert!(parsed.invocation.unwrap().boolean("confirm"));
        let parsed =
            parse_from(["openmates", "plans", "edit", "PLAN-4", "--chat", "--focus"]).unwrap();
        let invocation = parsed.invocation.unwrap();
        assert_eq!(invocation.flags["chat"], Value::Null);
        assert_eq!(invocation.flags["focus"], Value::Null);
        let parsed =
            parse_from(["openmates", "projects", "delete", "id", "--confirm", "id"]).unwrap();
        assert_eq!(parsed.invocation.unwrap().text("confirm"), Some("id"));
    }

    #[test]
    fn plan_task_project_links_preserve_original_and_normalized_selector_roles() {
        for operation in ["add-to-project", "remove-from-project"] {
            for arguments in [
                vec![
                    "openmates",
                    "plans",
                    "tasks",
                    "TASK-7",
                    "PLAN-9",
                    operation,
                    "project-id",
                ],
                vec![
                    "openmates",
                    "plans",
                    "tasks",
                    operation,
                    "PLAN-9",
                    "TASK-7",
                    "project-id",
                ],
            ] {
                let invocation = parse_from(arguments).unwrap().invocation.unwrap();
                assert_eq!(invocation.path, ["plans", "tasks", operation]);
                assert_eq!(invocation.positionals, ["PLAN-9", "TASK-7", "project-id"]);
            }
        }
    }

    #[test]
    fn plan_task_context_does_not_consume_flag_values_or_sentinel_literals() {
        for operation in ["add-to-project", "remove-from-project"] {
            let parsed = parse_from([
                "openmates",
                "--profile",
                operation,
                "plans",
                "tasks",
                "--team",
                "team-id",
                "TASK-7",
                "--api-url",
                "https://example.invalid",
                "PLAN-9",
                "--json",
                operation,
                "--state-dir",
                "/tmp/isolated",
                "project-id",
                "--json=false",
            ])
            .unwrap();
            assert_eq!(parsed.globals.profile.as_deref(), Some(operation));
            assert_eq!(
                parsed.globals.api_url.as_deref(),
                Some("https://example.invalid")
            );
            assert_eq!(
                parsed.globals.state_dir,
                Some(PathBuf::from("/tmp/isolated"))
            );
            let invocation = parsed.invocation.unwrap();
            assert_eq!(invocation.positionals, ["PLAN-9", "TASK-7", "project-id"]);
            assert_eq!(invocation.text("team"), Some("team-id"));
            assert!(!invocation.boolean("json"));

            let parsed = parse_from([
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                operation,
                "--",
                "--json",
            ])
            .unwrap();
            let invocation = parsed.invocation.unwrap();
            assert_eq!(invocation.positionals, ["PLAN-9", "TASK-7", "--json"]);
            assert!(!invocation.has("json"));
            let parsed = parse_from([
                "openmates",
                "--profile",
                "isolated",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                operation,
                "--",
                "--profile=literal-project-id",
            ])
            .unwrap();
            assert_eq!(parsed.globals.profile.as_deref(), Some("isolated"));
            assert_eq!(
                parsed.invocation.unwrap().positionals,
                ["PLAN-9", "TASK-7", "--profile=literal-project-id"]
            );
        }
    }

    #[test]
    fn plan_task_context_rejects_missing_excess_unknown_and_nonlink_actions() {
        for arguments in [
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "add-to-project",
                "project-id",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "add-to-project",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "add-to-project",
                "project-id",
                "extra",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "unknown",
                "project-id",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "create",
                "title",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "--",
                "add-to-project",
                "project-id",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "add-to-project",
                "project-id",
                "--unknown",
            ],
            vec![
                "openmates",
                "plans",
                "tasks",
                "add-to-project",
                "PLAN-9",
                "TASK-7",
            ],
        ] {
            assert!(parse_from(arguments.clone()).is_err(), "{arguments:?}");
        }
    }

    #[test]
    fn plan_task_context_preserves_duplicate_and_sensitive_option_validation() {
        assert!(
            parse_from([
                "openmates",
                "plans",
                "tasks",
                "TASK-7",
                "--profile",
                "first",
                "PLAN-9",
                "add-to-project",
                "project-id",
                "--profile",
                "second",
            ])
            .is_err()
        );
        assert!(
            parse_from([
                "openmates",
                "--profile=first",
                "plans",
                "tasks",
                "TASK-7",
                "PLAN-9",
                "remove-from-project",
                "project-id",
                "--profile=second",
            ])
            .is_err()
        );
        let error = parse_from([
            "openmates",
            "plans",
            "tasks",
            "TASK-7",
            "--api-key",
            "private-setup-secret",
            "PLAN-9",
            "add-to-project",
            "project-id",
            "--unknown",
        ])
        .err()
        .unwrap();
        assert!(!error.to_string().contains("private-setup-secret"));
    }
}
