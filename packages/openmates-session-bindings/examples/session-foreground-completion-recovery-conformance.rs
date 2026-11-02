#[path = "support/essential_session.rs"]
mod essential;
#[tokio::main]
async fn main() {
    if essential::main("session.foreground-completion-recovery.v1")
        .await
        .is_err()
    {
        eprintln!("Rust essential completion recovery conformance failed");
        std::process::exit(1);
    }
}
