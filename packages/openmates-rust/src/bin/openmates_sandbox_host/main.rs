//! `openmates-sandbox-host serve`: the daemon that holds one Project's
//! plaintext working tree inside an E2B sandbox (hosted Project sandbox plan).
//! Thin shell: reads `OMSH_*` env, hardens the process, then runs the server
//! from the shared core. Started as root; model commands run as `user`.
use openmates_sdk::work::sandbox_host::server::{
    Host, HostConfig, RunUser, make_non_dumpable, serve,
};
use std::sync::Arc;
use zeroize::Zeroizing;

fn required(name: &str) -> Result<String, String> {
    std::env::var(name)
        .ok()
        .filter(|v| !v.is_empty())
        .ok_or_else(|| format!("missing env {name}"))
}

fn config() -> Result<(HostConfig, u16), String> {
    let token = Zeroizing::new(required("OMSH_TOKEN")?);
    // SAFETY: still single-threaded here (the runtime starts afterwards), so no
    // other thread can read the environment concurrently. The token must not
    // stay in the environment of child processes the daemon spawns (git).
    unsafe { std::env::remove_var("OMSH_TOKEN") };
    let run_user = std::env::var("OMSH_RUN_USER").unwrap_or_else(|_| "user".to_owned());
    let port = std::env::var("OMSH_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(7787);
    Ok((
        HostConfig {
            token,
            sandbox_id: required("OMSH_SANDBOX_ID")?,
            job_id: required("OMSH_JOB_ID")?,
            project_id: required("OMSH_PROJECT_ID")?,
            chat_id: required("OMSH_CHAT_ID")?,
            team_id: std::env::var("OMSH_TEAM_ID").ok().filter(|v| !v.is_empty()),
            project_dir: std::env::var("OMSH_PROJECT_DIR")
                .unwrap_or_else(|_| "/home/user/project".to_owned())
                .into(),
            run_user: RunUser::lookup(&run_user),
        },
        port,
    ))
}

fn main() {
    if std::env::args().nth(1).as_deref() != Some("serve") {
        eprintln!("usage: openmates-sandbox-host serve");
        std::process::exit(2);
    }
    // Keep going when the kernel refuses: process isolation is a second line of defence.
    if make_non_dumpable().is_err() {
        eprintln!("warning: could not make the process non-dumpable");
    }
    let (cfg, port) = match config() {
        Ok(parts) => parts,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    let Ok(runtime) = tokio::runtime::Runtime::new() else {
        std::process::exit(1);
    };
    runtime.block_on(async move {
        let Ok(listener) = tokio::net::TcpListener::bind(("0.0.0.0", port)).await else {
            eprintln!("cannot bind port {port}");
            std::process::exit(1);
        };
        serve(listener, Arc::new(Host::new(cfg))).await;
    });
}
