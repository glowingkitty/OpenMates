//! Actual stateless Rust binding adapter. No network, credentials or processes.
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
const CAPABILITY: &str = "local.task-order.v1";
fn run() -> Result<Value, &'static str> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|index| args.get(index + 1))
            .ok_or("missing argument")
    };
    if option("--capability")? != CAPABILITY {
        return Err("unsupported capability");
    }
    let raw = std::fs::read(option("--fixture")?).map_err(|_| "fixture read")?;
    let fixture: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let vectors = fixture["capabilities"][CAPABILITY]["vectors"]
        .as_array()
        .filter(|v| !v.is_empty())
        .ok_or("empty vectors")?;
    let mut results = vec![];
    for vector in vectors {
        let original = vector["tasks"].clone();
        let input = json!({"locale":vector["locale"],"tasks":original}).to_string();
        let result = _native::sort_tasks_json(input);
        if let Some(code) = vector["error"].as_str() {
            if result.err().map(|error| error.code) != Some(code) {
                return Err("typed error mismatch");
            }
        } else {
            let output: Value = serde_json::from_str(&result.map_err(|_| "native sort")?)
                .map_err(|_| "native sort JSON")?;
            if output["indices"] != vector["expected_indices"] {
                return Err("golden order mismatch");
            }
        }
        if vector["tasks"] != original {
            return Err("input mutated");
        }
        results.push(json!({"id":vector["id"],"status":"passed"}));
    }
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results}),
    )
}
fn main() {
    match run() {
        Ok(result) => println!("{result}"),
        Err(reason) => {
            eprintln!("Task ordering conformance failed: {reason}");
            std::process::exit(1)
        }
    }
}
