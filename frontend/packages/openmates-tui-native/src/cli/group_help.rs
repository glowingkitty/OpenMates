//! Command-group roots whose npm usage is `<group> [--help]`: running the bare
//! group prints its help and exits 0, before any credential access.
use super::{CliError, CliOutput, Invocation, catalog, command};

/// Catalog handler name recorded for help-only group roots.
pub(super) const HANDLER: &str = "cli::group_help";

/// A one-segment group declared `<name> [--help]` with child commands and no
/// handler of its own.
pub(super) fn is_root(i: &Invocation) -> bool {
    let [name] = i.path.as_slice() else { return false };
    if !i.positionals.is_empty() {
        return false;
    }
    let help_usage = format!("{name} [--help]");
    catalog().commands.iter().any(|r| {
        r.path.len() == 1
            && r.path[0] == *name
            && r.implementation.handler.as_ref().is_none_or(|h| h.as_str() == HANDLER)
            && r.usages.contains(&help_usage)
    })
        && catalog().commands.iter().any(|r| r.path.len() > 1 && r.path[0] == *name)
}

pub(super) fn public(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if !is_root(i) {
        return None;
    }
    let mut help = command();
    let group = help.find_subcommand_mut(&i.path[0])?;
    Some(Ok(CliOutput::text(group.render_long_help().to_string())))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parsed(args: &[&str]) -> Invocation {
        Invocation {
            path: args[1..].iter().map(|s| (*s).to_owned()).collect(),
            positionals: vec![],
            flags: Default::default(),
        }
    }

    #[test]
    fn help_only_roots_print_help_and_real_commands_do_not() {
        for group in ["mentions", "settings", "tasks", "teams", "plans", "projects", "workflows"] {
            let invocation = parsed(&["openmates", group]);
            assert!(is_root(&invocation), "{group}");
            assert!(super::super::handlers::requirements(&invocation).supported, "{group}");
            let out = public(&invocation).unwrap().ok().unwrap();
            assert!(out.stdout.contains("Usage:"), "{group}");
            assert_eq!(out.exit_code, 0);
        }
        for command in ["privacy", "update", "recovery", "chats list"] {
            let args: Vec<&str> = ["openmates"].into_iter().chain(command.split(' ')).collect();
            assert!(!is_root(&parsed(&args)), "{command}");
        }
    }
}
