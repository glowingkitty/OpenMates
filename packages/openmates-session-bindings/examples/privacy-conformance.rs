//! Direct public Rust SDK privacy facade, independent of foreign binding dispatch.
// contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
use openmates_sdk::privacy::{PrivacyOptions, prepare_local, restore_local};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
const CAPABILITY: &str = "local.privacy.v1";
fn strings(value: &Value) -> Result<&str, &'static str> {
    value.as_str().ok_or("fixture string")
}
fn values(value: &Value) -> Result<&[Value], &'static str> {
    value.as_array().map(Vec::as_slice).ok_or("fixture array")
}
fn run() -> Result<Value, &'static str> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|a| a == name)
            .and_then(|i| args.get(i + 1))
            .ok_or("missing option")
    };
    if option("--capability")? != CAPABILITY {
        return Err("unsupported capability");
    }
    let raw = std::fs::read(option("--fixture")?).map_err(|_| "fixture read")?;
    let fixture: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let vectors = values(&fixture["capabilities"][CAPABILITY]["vectors"])?;
    if vectors.is_empty() {
        return Err("empty vectors");
    }
    let mut results = vec![];
    for vector in vectors {
        let mut input = vector["input"].clone();
        let expand = &vector["expand"];
        if let Some(n) = expand["text_bytes"].as_u64() {
            input["text"] = json!("x".repeat(n as usize));
        }
        if let Some(n) = expand["mapping_count"].as_u64() {
            input["mappings"] = json!(vec![Value::Null; n as usize]);
        }
        if let Some(n) = expand["encoded_bytes"].as_u64() {
            input["mappings"] = json!([""]);
            let overhead = serde_json::to_vec(&input)
                .map_err(|_| "fixture expansion")?
                .len();
            input["mappings"] = json!(["x".repeat(n as usize - overhead)]);
        }

        if let Some(n) = expand["existing_count"].as_u64() {
            input["existing_mappings"]=json!((0..n).map(|i|json!({"original":format!("unrelated-{i}"),"placeholder":format!("[KEEP_{i}]")})).collect::<Vec<_>>());
        }
        if let Some(n) = expand["email_repeats"].as_u64() {
            input["text"] = json!("a@b.co ".repeat(n as usize));
        }
        if let Some(n) = expand["prepare_json_bytes"].as_u64() {
            input["existing_mappings"] =
                json!([{"original":"unrelated","placeholder":"[KEEP]","padding":""}]);
            let overhead = serde_json::to_vec(&input)
                .map_err(|_| "fixture expansion")?
                .len();
            input["existing_mappings"][0]["padding"] = json!("x".repeat(n as usize - overhead));
        }
        if let Some(n) = expand["canonical_json_bytes"].as_u64() {
            let overhead = expand["canonical_overhead"]
                .as_u64()
                .ok_or("canonical overhead")?;
            input["mappings"][1] = json!("x".repeat((n - overhead) as usize));
        }

        if let Some(n) = expand["placeholder_bytes"].as_u64() {
            input["text"] = json!(
                "x".repeat(
                    expand["plain_repeats"]
                        .as_u64()
                        .ok_or("plain repeat count")? as usize
                )
            );
            input["existing_mappings"] =
                json!([{"original":"x","placeholder":format!("[{}]","A".repeat(n as usize-2))}]);
        }
        if let Some(n) = expand["original_bytes"].as_u64() {
            input["text"] = json!(
                "[X]".repeat(
                    expand["token_repeats"]
                        .as_u64()
                        .ok_or("token repeat count")? as usize
                )
            );
            input["mappings"] = json!([{"original":"y".repeat(n as usize),"placeholder":"[X]"}]);
        }

        let text = strings(&input["text"])?;
        let output = match strings(&input["operation"])? {
            "prepare" => prepare_local(
                text,
                values(&input["memories"])?,
                values(&input["existing_mappings"])?,
                &PrivacyOptions {
                    enhanced: input["enhanced"].as_bool().ok_or("fixture bool")?,
                },
            )
            .map(|p| json!({"text":p.text,"mappings":p.mappings})),
            "restore" => {
                restore_local(text, values(&input["mappings"])?).map(|text| json!({"text":text}))
            }
            _ => return Err("fixture operation"),
        };
        if vector.get("error").is_some() {
            if !matches!(output, Err(openmates_sdk::Error::Invalid(_))) {
                return Err("expected static invalid argument");
            }
        } else {
            let output = output.map_err(|_| "privacy operation")?;
            if let Some(n) = vector["expected_text_length"].as_u64() {
                if output["text"]
                    != json!(
                        vector["expected_repeat_character"]
                            .as_str()
                            .unwrap_or("x")
                            .repeat(n as usize)
                    )
                {
                    return Err("text boundary mismatch");
                }
            }
            if let Some(expected) = vector.get("expected") {
                if &output != expected {
                    return Err("golden output mismatch");
                }
            }
            if let Some(expected) = vector.get("mapping_values") {
                let mappings = values(&output["mappings"])?;
                let projection: Vec<Value> = mappings
                    .iter()
                    .map(|m| json!({"original":m["original"],"type":m["type"]}))
                    .collect();
                if &json!(projection) != expected {
                    return Err("mapping projection mismatch");
                }
                let text = strings(&output["text"])?;
                let mut tokens = std::collections::HashSet::new();
                for mapping in mappings {
                    let token = strings(&mapping["placeholder"])?;
                    if token.len() != 41
                        || !token.starts_with("[OM_PII_")
                        || !token.ends_with(']')
                        || !token.as_bytes()[8..40]
                            .iter()
                            .all(|c| c.is_ascii_digit() || (b'A'..=b'F').contains(c))
                        || !tokens.insert(token)
                        || !text.contains(token)
                        || text.contains(strings(&mapping["original"])?)
                    {
                        return Err("token privacy invariant");
                    }
                }
            }
            if let Some(n) = vector["prepared_text_length"].as_u64() {
                if strings(&output["text"])?.len() != n as usize {
                    return Err("prepared text length");
                }
            }
            if vector["prepared_token_output"] == true
                && output["text"] != output["mappings"][0]["placeholder"]
            {
                return Err("known output token mismatch");
            }
            if vector["roundtrip_input"] == true {
                if restore_local(strings(&output["text"])?, values(&output["mappings"])?)
                    .map_err(|_| "prepared output restore budgets")?
                    != text
                {
                    return Err("prepared output roundtrip");
                }
            }
            if let Some(expected) = vector.get("restored") {
                let restored =
                    restore_local(strings(&output["text"])?, values(&output["mappings"])?)
                        .map_err(|_| "restoration")?;
                if json!(restored) != *expected {
                    return Err("roundtrip mismatch");
                }
            }
        }
        results.push(json!({"id":vector["id"],"status":"passed"}));
    }
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(raw)),"results":results}),
    )
}
fn main() {
    match run() {
        Ok(result) => println!("{result}"),
        Err(reason) => {
            eprintln!("Local privacy conformance failed: {reason}");
            std::process::exit(1);
        }
    }
}
