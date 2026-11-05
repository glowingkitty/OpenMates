//! Offline conformance harness; argument/file handling is outside the SDK library.
use base64::{
    Engine,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use openmates_sdk::crypto::*;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value[key]
        .as_str()
        .ok_or_else(|| format!("Missing synthetic fixture field: {key}"))
}
fn check(ok: bool) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err("SDK conformance assertion failed".into())
    }
}
fn url_key(value: &str) -> Result<zeroize::Zeroizing<[u8; 32]>, String> {
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| "Invalid synthetic key")?;
    let bytes: [u8; 32] = bytes
        .try_into()
        .map_err(|_| "Invalid synthetic key length")?;
    Ok(zeroize::Zeroizing::new(bytes))
}
fn run(capability: &str, source: &[u8]) -> Result<Value, String> {
    let fixture: Value = serde_json::from_slice(source).map_err(|_| "Invalid fixture JSON")?;
    check(fixture["schema_version"] == 1)?;
    let fixture = &fixture["capabilities"][capability];
    let checks: &[&str] = match capability {
        "crypto.aes-gcm-combined.v1" => &[
            "known ciphertext plaintext",
            "fresh encryption roundtrip",
            "wrong key rejection",
            "ciphertext tag tamper rejection",
            "OM fingerprint tamper rejection",
        ],
        "crypto.slug-lookup.v1" => &[
            "exact normalized slug",
            "exact HKDF/HMAC lookup hash",
            "empty normalized slug rejection",
        ],
        "crypto.recovery-envelope.v1" => &[
            "exact derived keypair",
            "exact associated data",
            "known sealed payload plaintext",
            "wrong identity rejection",
            "ephemeral key/nonce/ciphertext tamper rejection",
            "low-order ephemeral public key rejection",
        ],
        _ => {
            return Ok(
                json!({"capability":capability,"language":"rust","status":"unsupported","fixtureSha256":format!("{:x}",Sha256::digest(source)),"results":[]}),
            );
        }
    };
    check(fixture["required_checks"] == json!(checks))?;
    let vectors = fixture["vectors"].as_array().ok_or("Missing vectors")?;
    check(!vectors.is_empty())?;
    let mut results = vec![];
    for vector in vectors {
        let id = vector
            .get("id")
            .or_else(|| vector.get("name"))
            .and_then(Value::as_str)
            .ok_or("Missing vector identity")?;
        match capability {
            "crypto.aes-gcm-combined.v1" => {
                let key =
                    decode_key(field(vector, "key_b64")?).map_err(|_| "Synthetic key rejected")?;
                let ciphertext = field(vector, "ciphertext_b64")?;
                let plain = field(vector, "plaintext")?;
                check(decrypt_combined(ciphertext, &key).ok().as_deref() == Some(plain))?;
                let fresh = encrypt_combined(plain, &key).map_err(|_| "Encryption failed")?;
                check(decrypt_combined(&fresh, &key).ok().as_deref() == Some(plain))?;
                let mut wrong = *key;
                wrong[0] ^= 1;
                check(decrypt_combined(ciphertext, &wrong).is_err())?;
                let mut tamper = STANDARD
                    .decode(ciphertext)
                    .map_err(|_| "Invalid ciphertext fixture")?;
                let last = tamper.len() - 1;
                tamper[last] ^= 1;
                check(decrypt_combined(&STANDARD.encode(&tamper), &key).is_err())?;
                let mut header = STANDARD
                    .decode(ciphertext)
                    .map_err(|_| "Invalid ciphertext fixture")?;
                if header.starts_with(b"OM") {
                    header[2] ^= 128;
                    check(decrypt_combined(&STANDARD.encode(header), &key).is_err())?;
                }
            }
            "crypto.slug-lookup.v1" => {
                let key =
                    decode_key(field(vector, "key_b64")?).map_err(|_| "Synthetic key rejected")?;
                let normalized = normalize_object_slug(field(vector, "input")?)
                    .map_err(|_| "Normalization failed")?;
                check(normalized == field(vector, "normalized")?)?;
                check(
                    object_slug_lookup_hash(&normalized, &key).ok().as_deref()
                        == Some(field(vector, "lookup_hash")?),
                )?;
                check(normalize_object_slug(" ✨ ").is_err())?;
            }
            "crypto.recovery-envelope.v1" => {
                let key = url_key(field(vector, "chat_key")?)?;
                let version = vector["key_version"]
                    .as_u64()
                    .ok_or("Invalid key version")? as u32;
                let keys = recovery_keypair(&key, field(vector, "chat_id")?, version)
                    .map_err(|_| "Recovery derivation failed")?;
                check(
                    URL_SAFE_NO_PAD.encode(keys.private_key.as_ref())
                        == field(vector, "recovery_private_key")?,
                )?;
                check(keys.public_key == field(vector, "recovery_public_key")?)?;
                let mut identity = RecoveryIdentity {
                    owner_id: field(vector, "owner_id")?.into(),
                    chat_id: field(vector, "chat_id")?.into(),
                    turn_id: field(vector, "turn_id")?.into(),
                    job_id: field(vector, "job_id")?.into(),
                    assistant_message_id: field(vector, "assistant_message_id")?.into(),
                    key_version: version,
                };
                check(
                    URL_SAFE_NO_PAD
                        .encode(recovery_associated_data(&identity).map_err(|_| "AAD failed")?)
                        == field(vector, "associated_data")?,
                )?;
                let envelope = &vector["envelope"];
                let plain = open_recovery_envelope(envelope, &keys.private_key, &identity)
                    .map_err(|_| "Recovery open failed")?;
                check(plain.as_slice() == field(vector, "plaintext")?.as_bytes())?;
                identity.owner_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".into();
                check(open_recovery_envelope(envelope, &keys.private_key, &identity).is_err())?;
                identity.owner_id = field(vector, "owner_id")?.into();
                for component in ["epk", "nonce", "ciphertext"] {
                    let mut changed = envelope.clone();
                    let mut bytes = URL_SAFE_NO_PAD
                        .decode(field(envelope, component)?)
                        .map_err(|_| "Invalid envelope fixture")?;
                    bytes[0] ^= 1;
                    changed[component] = json!(URL_SAFE_NO_PAD.encode(bytes));
                    check(open_recovery_envelope(&changed, &keys.private_key, &identity).is_err())?;
                }
                let mut low_order = envelope.clone();
                low_order["epk"] = json!(URL_SAFE_NO_PAD.encode([0; 32]));
                check(open_recovery_envelope(&low_order, &keys.private_key, &identity).is_err())?;
            }
            _ => unreachable!(),
        }
        results.push(json!({"id":id,"status":"passed"}));
    }
    Ok(
        json!({"capability":capability,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(source)),"results":results}),
    )
}
async fn generated(source: &[u8]) -> Result<Value, String> {
    use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let fixture: Value = serde_json::from_slice(source).map_err(|_| "Invalid fixture JSON")?;
    let capability = "protocol.generated-skills.v1";
    let fixture = &fixture["capabilities"][capability];
    let vectors = fixture["vectors"]
        .as_array()
        .ok_or("Missing generated fixtures")?;
    check(!vectors.is_empty())?;
    let mut results = vec![];
    check(
        fixture["required_checks"]
            == json!([
                "actual generated binding method invocation",
                "direct fake-transport request path/method/body",
                "API key bearer boundary",
                "actual structured response",
                "no model/provider override added"
            ]),
    )?;
    for vector in vectors {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|_| "Fake transport bind failed")?;
        let address = listener
            .local_addr()
            .map_err(|_| "Fake transport address failed")?;
        let response =
            serde_json::to_vec(&vector["response"]).map_err(|_| "Invalid synthetic response")?;
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener
                .accept()
                .await
                .map_err(|_| "Fake transport accept failed")?;
            let mut bytes = vec![];
            let mut buffer = [0u8; 4096];
            let (header_end, body_len) = loop {
                let n = stream
                    .read(&mut buffer)
                    .await
                    .map_err(|_| "Fake request failed")?;
                if n == 0 {
                    return Err("Truncated fake request");
                }
                bytes.extend_from_slice(&buffer[..n]);
                if bytes.len() > 65536 {
                    return Err("Oversized fake request");
                }
                if let Some(end) = bytes.windows(4).position(|s| s == b"\r\n\r\n") {
                    let header = String::from_utf8_lossy(&bytes[..end]);
                    let len = header
                        .lines()
                        .find_map(|line| {
                            line.split_once(':')
                                .filter(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                                .and_then(|(_, n)| n.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    break (end + 4, len);
                }
            };
            while bytes.len() < header_end + body_len {
                let n = stream
                    .read(&mut buffer)
                    .await
                    .map_err(|_| "Fake request body failed")?;
                if n == 0 {
                    return Err("Truncated fake request body");
                }
                bytes.extend_from_slice(&buffer[..n]);
                if bytes.len() > 65536 {
                    return Err("Oversized fake request body");
                }
            }
            let header = String::from_utf8_lossy(&bytes[..header_end]).into_owned();
            let body: Value = serde_json::from_slice(&bytes[header_end..header_end + body_len])
                .map_err(|_| "Invalid fake request body")?;
            let prefix = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                response.len()
            );
            stream
                .write_all(prefix.as_bytes())
                .await
                .map_err(|_| "Fake response failed")?;
            stream
                .write_all(&response)
                .await
                .map_err(|_| "Fake response body failed")?;
            Ok::<_, &str>((header, body))
        });
        let bearer = format!("sk-api-{}", "b".repeat(32));
        let secret = "s".repeat(32);
        let client = OpenMates::new(SdkOptions {
            api_url: format!("http://{address}"),
            credentials: SdkCredentials::ApiKey(
                ApiKey::new(&format!("{bearer}.{secret}")).map_err(|_| "Credential rejected")?,
            ),
            device_id: "rust-conformance-fixture".into(),
            client_options: ClientOptions::default(),
        })
        .map_err(|_| "Client configuration failed")?;
        check(vector["app"] == "web" && vector["skill"] == "search")?;
        let actual = client
            .apps()
            .web()
            .search(vector["input"].clone())
            .await
            .map_err(|_| "Actual generated method failed")?;
        let (header, body) = server
            .await
            .map_err(|_| "Fake transport task failed")?
            .map_err(String::from)?;
        check(header.starts_with(&format!(
            "{} {} HTTP/1.1",
            field(vector, "method")?,
            field(vector, "path")?
        )))?;
        check(
            header
                .to_ascii_lowercase()
                .contains(&format!("authorization: bearer {bearer}")),
        )?;
        check(!header.contains(&secret))?;
        check(
            header
                .to_ascii_lowercase()
                .contains("x-openmates-sdk: rust"),
        )?;
        check(body == vector["input"])?;
        check(actual == vector["response"])?;
        results.push(json!({"id":vector["id"],"status":"passed"}));
    }
    Ok(
        json!({"capability":capability,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(source)),"results":results}),
    )
}
fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let argument = |name: &str| {
        args.windows(2)
            .find(|pair| pair[0] == name)
            .map(|pair| pair[1].clone())
    };
    let result = (|| {
        let path = argument("--fixture").ok_or("--fixture is required")?;
        let capability = argument("--capability").ok_or("--capability is required")?;
        let bytes = std::fs::read(path).map_err(|_| "Fixture could not be read")?;
        if capability == "protocol.generated-skills.v1" {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|_| "Conformance runtime failed")?
                .block_on(generated(&bytes))
        } else {
            run(&capability, &bytes)
        }
    })();
    match result {
        Ok(value) => {
            println!("{value}");
            if value["status"] != "passed" {
                std::process::exit(2)
            }
        }
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1)
        }
    }
}
