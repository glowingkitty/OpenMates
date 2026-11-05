#[path = "support/essential_session.rs"]
mod essential;
#[tokio::main]
async fn main() {
    if essential::main("session.initial-startup-sync.v1").await.is_err() {
        eprintln!("Rust initial startup conformance failed");
        std::process::exit(1);
    }
}
