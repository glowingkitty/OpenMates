#![forbid(unsafe_code)]
mod command_runtime;
mod runtime;
use openmates::cli::{self, CliError, CliOutput};
use std::{
    io::{self, IsTerminal, Write},
    path::PathBuf,
};

/// OpenMates, implemented entirely in Rust.
struct Args {
    /// Synthetic presentation demo. Does not access credentials or the network.
    demo: bool,
    /// API origin. HTTPS is required except for a literal loopback address.
    api_url: Option<String>,
    /// Independent native client state directory.
    state_dir: Option<PathBuf>,
    /// Explicitly select a passphrase-encrypted local credential vault.
    encrypted_vault: bool,
    /// Select an isolated named native authentication profile.
    profile: Option<String>,
    trusted_account: bool,
}

fn main() {
    // Before any thread exists: the OS refuses the offset afterwards.
    openmates::local_zone::capture();
    let parsed = cli::parse_from(std::env::args_os()).unwrap_or_else(|error| {
        // The npm CLI reports a missing positional ("Missing chat ID. Usage: ...")
        // as a runtime error with exit code 1; clap would exit 2.
        if error.kind() == clap::error::ErrorKind::MissingRequiredArgument {
            let _ = error.print();
            std::process::exit(1);
        }
        error.exit()
    });
    if parsed.version_requested {
        // The global flag is the package identity probe; the public `version`
        // command retains update availability details and its JSON contract.
        if !parsed.globals.json {
            write_result(
                Ok(CliOutput::text(format!(
                    "OpenMates CLI {} (Rust)",
                    env!("CARGO_PKG_VERSION")
                ))),
                false,
            );
        }
        let invocation = cli::Invocation {
            path: vec!["version".into()],
            positionals: Vec::new(),
            flags: std::collections::BTreeMap::from([(
                "json".into(),
                serde_json::json!(parsed.globals.json),
            )]),
        };
        write_result(
            cli::execute_public(&invocation).expect("native version handler"),
            parsed.globals.json,
        );
    }
    let json = parsed.globals.json;
    let terminal = parsed
        .invocation
        .as_ref()
        .is_none_or(|call| call.command_path() == "tui");
    if terminal && !io::stdin().is_terminal() && parsed.invocation.is_none() {
        println!(
            "OpenMates native Rust CLI\n\nUse openmates --help for commands, openmates login to pair,\nand openmates tui in an interactive terminal."
        );
        return;
    }
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(_) => {
            eprintln!("OpenMates: The async runtime could not be started.");
            std::process::exit(1);
        }
    };
    let result = if terminal {
        let globals = parsed.globals;
        let guard = cli::trusted_account::check_environment(
            &globals,
            parsed.invocation.as_ref(),
            &cli::trusted_account::Environment::capture(),
        );
        let trusted_account = guard.as_ref().is_ok_and(|policy| policy.enabled);
        if let Err(error) = guard {
            Err(error)
        } else if globals.api_key.is_some()
            || std::env::var("OPENMATES_API_KEY").is_ok_and(|value| !value.trim().is_empty())
        {
            Err(CliError::Invalid("The interactive terminal requires an explicit native session; API-key terminal auth is not implemented yet.".into()))
        } else {
            runtime
                .block_on(runtime::run(Args {
                    demo: globals.demo,
                    api_url: globals.api_url,
                    state_dir: globals.state_dir,
                    encrypted_vault: globals.encrypted_vault,
                    profile: globals.profile,
                    trusted_account,
                }))
                .map(|()| CliOutput {
                    stdout: String::new(),
                    stderr: String::new(),
                    exit_code: 0,
                })
                .map_err(CliError::from)
        }
    } else {
        let invocation = parsed.invocation.expect("command mode");
        let path = invocation.command_path();
        let chat_id = invocation.positionals.first().cloned();
        let second_positional = invocation.positionals.get(1).cloned();
        let chat_flag = invocation.text("chat").map(str::to_owned);
        let result = runtime.block_on(command_runtime::run(parsed.globals, invocation));
        // npm names the missing object ("Chat '<id>' not found"); the SDK's error is generic.
        result.map_err(|error| {
            cli::npm_wording::unknown_id(
                &path,
                chat_id.as_deref(),
                second_positional.as_deref(),
                chat_flag.as_deref(),
                json,
                error,
            )
        })
    };
    // A stuck OS keyring call must not prevent returning the restored terminal.
    // In-flight filesystem publication remains atomic even if shutdown times out.
    runtime.shutdown_timeout(std::time::Duration::from_secs(5));
    write_result(result, json);
}

fn write_result(result: Result<CliOutput, CliError>, json: bool) -> ! {
    match result {
        Ok(output) => {
            let written = io::stdout()
                .write_all(output.stdout.as_bytes())
                .and_then(|()| io::stderr().write_all(output.stderr.as_bytes()));
            if let Err(error) = written {
                if error.kind() != io::ErrorKind::BrokenPipe {
                    eprintln!("Error: Output could not be written.");
                }
                std::process::exit(1);
            }
            std::process::exit(i32::from(output.exit_code));
        }
        Err(error) => {
            if json {
                eprintln!("{}", error.structured_error());
            } else {
                eprintln!("Error: {error}");
            }
            std::process::exit(
                if matches!(
                    error,
                    CliError::Client(openmates::error::Error::Cancelled)
                ) {
                    130
                } else {
                    i32::from(error.exit_code())
                },
            );
        }
    }
}
