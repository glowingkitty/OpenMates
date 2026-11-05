#[path = "support/essential_session.rs"]
mod essential;
#[tokio::main]
async fn main() {
    if essential::main("session.chat-change-monitor.v1")
        .await
        .is_err()
    {
        eprintln!("Rust essential monitor conformance failed");
        std::process::exit(1);
    }
}
