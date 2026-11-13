//! Pure-function vectors: public utilities (`sdk-api-key-domains-b.json`),
//! key-management primitives (`sdk-key-management.json`) and presentation models
//! (`sdk-models.json`), each through the public Rust SDK API only.
use base64::{Engine, engine::general_purpose::STANDARD};
use openmates_sdk::crypto;
use openmates_sdk::model::{Chat, Item, Message, Workspace};
use openmates_sdk::sdk_feedback::build_assistant_feedback_decision;
use openmates_sdk::sdk_public_utilities as utilities;
use serde_json::{Value, json};

fn check(ok: bool, id: &Value) -> Result<(), String> {
    ok.then_some(())
        .ok_or_else(|| format!("assertion failed: {id}"))
}
fn str_arg(vector: &Value, index: usize) -> Result<&str, String> {
    vector["args"][index]
        .as_str()
        .ok_or_else(|| format!("string argument {index}"))
}

/// One `sdk.public-utilities-helpers.v1` vector.
pub fn helper_case(vector: &Value) -> Result<(), String> {
    let id = &vector["id"];
    let expected = &vector["expect"];
    let actual = match vector["function"].as_str().unwrap_or_default() {
        "render_support_info" => json!(utilities::render_support_info()),
        "default_clone_branch_for_version" => {
            json!(utilities::default_clone_branch_for_version(str_arg(
                vector, 0
            )?))
        }
        "get_ext_for_lang" => json!(utilities::get_ext_for_lang(str_arg(vector, 0)?)),
        "derive_app_url" => json!(utilities::derive_app_url(str_arg(vector, 0)?)),
        "classify_images_ai_detection" => {
            json!(utilities::classify_images_ai_detection(vector["args"][0].as_f64()).as_str())
        }
        "build_images_ai_detection_summary" => {
            utilities::build_images_ai_detection_summary(&vector["args"][0], str_arg(vector, 1)?)
        }
        "build_assistant_feedback_decision" => {
            let rating = vector["args"][0].as_i64().ok_or("integer rating")?;
            match build_assistant_feedback_decision(rating) {
                Ok(d) => {
                    json!({"rating": d.rating, "action": d.action, "message": d.message, "report_title": d.report_title})
                }
                Err(_) => json!({"error": "invalid"}),
            }
        }
        other => return Err(format!("unsupported helper {other}")),
    };
    check(&actual == expected, id)
}

fn key(vector: &Value) -> Result<[u8; 32], String> {
    let hex = vector["key_hex"].as_str().ok_or("key_hex")?;
    let bytes: Vec<u8> = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(hex.get(i..i + 2).unwrap_or("zz"), 16).map_err(|_| "hex"))
        .collect::<Result<_, _>>()?;
    bytes.try_into().map_err(|_| "32-byte key".into())
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// One `sdk.key-management.primitives.v1` vector.
pub fn key_case(vector: &Value) -> Result<(), String> {
    let id = &vector["id"];
    let refused = vector["expect_error"] == true;
    match vector["op"].as_str().unwrap_or_default() {
        "encode_key" => check(crypto::encode_key(&key(vector)?) == vector["expect"], id),
        "decode_key" => match crypto::decode_key(vector["value"].as_str().ok_or("value")?) {
            Ok(decoded) => check(!refused && hex(&decoded[..]) == vector["expect_hex"], id),
            Err(error) => check(refused && matches!(error, openmates_sdk::Error::Crypto), id),
        },
        "key_fingerprint" => check(
            hex(&crypto::key_fingerprint(&key(vector)?)) == vector["expect_hex"],
            id,
        ),
        "hash_email" => check(
            crypto::hash_email(vector["email"].as_str().ok_or("email")?) == vector["expect"],
            id,
        ),
        "hash_key" => {
            let salt = STANDARD
                .decode(vector["salt_b64"].as_str().ok_or("salt")?)
                .map_err(|_| "salt")?;
            let hash = crypto::hash_key(vector["password"].as_str().ok_or("password")?, &salt)
                .map_err(|_| "hash_key")?;
            check(hash == vector["expect"], id)
        }
        "decrypt_combined" => match crypto::decrypt_combined(
            vector["ciphertext"].as_str().ok_or("ciphertext")?,
            &key(vector)?,
        ) {
            Ok(text) => check(!refused && text == vector["expect"], id),
            Err(error) => check(refused && matches!(error, openmates_sdk::Error::Crypto), id),
        },
        "encrypt_combined" => {
            let (plain, key) = (
                vector["plaintext"].as_str().ok_or("plaintext")?,
                key(vector)?,
            );
            let sealed = crypto::encrypt_combined(plain, &key).map_err(|_| "encrypt")?;
            let raw = STANDARD.decode(&sealed).map_err(|_| "base64")?;
            check(
                raw.starts_with(b"OM") && raw.get(2..6) == Some(&crypto::key_fingerprint(&key)[..]),
                id,
            )?;
            check(
                crypto::decrypt_combined(&sealed, &key).map_err(|_| "decrypt")? == plain,
                id,
            )
        }
        "random_key" => {
            let (first, second) = (crypto::random_key(), crypto::random_key());
            check(first.len() == 32 && *first != *second, id)
        }
        other => Err(format!("unsupported key op {other}")),
    }
}

fn layout<T: serde::de::DeserializeOwned + serde::Serialize>(input: &Value) -> Option<Value> {
    serde_json::from_value::<T>(input.clone())
        .ok()
        .and_then(|value| serde_json::to_value(value).ok())
}

/// One `sdk.models.layout.v1` vector.
pub fn model_case(vector: &Value) -> Result<(), String> {
    let id = &vector["id"];
    let input = &vector["input"];
    let parsed = match vector["kind"].as_str().unwrap_or_default() {
        "workspaces" => {
            let listed = Workspace::ALL
                .iter()
                .map(|w| serde_json::to_value(w).map(|id| json!({"id": id, "label": w.label()})))
                .collect::<Result<Vec<_>, _>>()
                .map_err(|_| "workspace")?;
            return check(Value::Array(listed) == vector["expect"], id);
        }
        "chat" => layout::<Chat>(input),
        "message" => layout::<Message>(input),
        "item" => layout::<Item>(input),
        other => return Err(format!("unsupported model kind {other}")),
    };
    match parsed {
        Some(value) => check(
            vector["expect_error"] != true && value == vector["expect"],
            id,
        ),
        None => check(vector["expect_error"] == true, id),
    }
}
