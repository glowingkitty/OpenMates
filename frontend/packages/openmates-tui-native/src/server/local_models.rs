//! Explicit self-host model setup. This never changes account routing defaults.
use super::*;
use zeroize::Zeroize;
struct Overlay(Value);
impl Drop for Overlay {
    fn drop(&mut self) {
        erase(&mut self.0);
    }
}
pub(super) fn erase(value: &mut Value) {
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(a) => a.iter_mut().for_each(erase),
        Value::Object(o) => o.values_mut().for_each(erase),
        _ => {}
    }
}
fn path(c: &Configuration) -> PathBuf {
    c.install_path.join(if c.install_mode == "source" {
        "backend/providers/local-ai-models.yml"
    } else {
        "config/providers/local-ai-models.yml"
    })
}
fn read(path: &Path) -> Result<Overlay> {
    let value = if path.try_exists()? {
        serde_json::from_slice(&Zeroizing::new(fs::private_read(path, 4 * 1024 * 1024)?))?
    } else {
        json!({"providers":[]})
    };
    let overlay = Overlay(value);
    let providers = overlay.0["providers"].as_array().ok_or(Error::Protocol)?;
    for provider in providers {
        if provider["provider_id"].as_str().is_none() || !provider["models"].is_array() {
            return Err(Error::Protocol);
        }
    }
    Ok(overlay)
}
fn write(path: &Path, value: &Overlay) -> Result<()> {
    let bytes = Zeroizing::new(serde_json::to_vec_pretty(&value.0)?);
    fs::write(path, &bytes, 0o600)
}
fn normalize(raw: &str, creator: bool) -> String {
    let separator = if creator { '_' } else { '-' };
    let mut out = String::new();
    let mut replacing = false;
    for ch in raw.trim().to_ascii_lowercase().chars() {
        if ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' || (!creator && ch == '.') {
            out.push(ch);
            replacing = false
        } else if !replacing {
            out.push(separator);
            replacing = true
        }
    }
    let out = out.trim_matches(separator);
    if out.is_empty() {
        if creator {
            "custom_local".into()
        } else {
            "local-model".into()
        }
    } else {
        out.into()
    }
}
fn creator(model: &str) -> (&'static str, &'static str) {
    for token in model.to_ascii_lowercase().split(['-', '_', ':', '/']) {
        if token.starts_with("qwen") {
            return ("alibaba", "Alibaba / Qwen");
        }
        if token.starts_with("gemma") {
            return ("google", "Google / Gemma");
        }
        if ["mistral", "mixtral", "ministral"]
            .iter()
            .any(|s| token.starts_with(s))
        {
            return ("mistral", "Mistral");
        }
        if token.starts_with("deepseek") {
            return ("deepseek", "DeepSeek");
        }
    }
    if model.to_ascii_lowercase().contains("gpt-oss") {
        ("openai", "OpenAI")
    } else {
        ("custom_local", "Custom")
    }
}
fn ask(flags: &Flags, key: &str, label: &str, default: Option<&str>) -> Result<Zeroizing<String>> {
    use std::io::IsTerminal;
    if let Some(value) = text(flags, key) {
        return Ok(Zeroizing::new(value.into()));
    }
    if !std::io::stdin().is_terminal() {
        return default.map(|s|Zeroizing::new(s.into())).ok_or(Error::Invalid("Noninteractive local-model setup requires --model and a custom runtime requires --base-url."));
    }
    eprint!(
        "{label}{}: ",
        default.map(|s| format!(" [{s}]")).unwrap_or_default()
    );
    std::io::stderr().flush()?;
    let mut value = Zeroizing::new(String::new());
    std::io::stdin().read_line(&mut value)?;
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return default
            .map(|s| Zeroizing::new(s.into()))
            .ok_or(Error::Invalid(
                "A local-model configuration value is required.",
            ));
    }
    if trimmed.len() > 4096 || trimmed.contains(['\r', '\n', '\0']) {
        return Err(Error::Invalid(
            "Local-model configuration value is invalid.",
        ));
    }
    Ok(Zeroizing::new(trimmed.into()))
}
fn endpoint(raw: &str) -> Result<url::Url> {
    let url =
        url::Url::parse(raw).map_err(|_| Error::Invalid("Local model base URL is invalid."))?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(Error::Invalid(
            "Local model URL requires HTTP(S) without embedded credentials, query or fragment.",
        ));
    }
    Ok(url)
}
async fn request(base: &str, key: &str, model: Option<&str>) -> Result<Value> {
    let mut url = endpoint(base)?;
    // Docker's container-only alias is mapped to host loopback solely for the
    // explicit host-side setup probe; the stored container URL is preserved.
    if url.host_str() == Some("host.docker.internal") {
        url.set_host(Some("127.0.0.1"))
            .map_err(|_| Error::Protocol)?;
    }
    url.set_path(&format!(
        "{}/{}",
        url.path().trim_end_matches('/'),
        if model.is_some() {
            "chat/completions"
        } else {
            "models"
        }
    ));
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(30))
        .build()?;
    let auth = if key.is_empty() { "local" } else { key };
    let mut response = if let Some(model) = model {
        client.post(url).bearer_auth(auth).json(&json!({"model":model,"messages":[{"role":"system","content":"Answer with only the number."},{"role":"user","content":"1+2?"}],"stream":false,"temperature":0})).send().await?
    } else {
        client.get(url).bearer_auth(auth).send().await?
    };
    if !response.status().is_success() {
        return Err(Error::Offline);
    }
    let mut bytes = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await? {
        if bytes.len() + chunk.len() > 1024 * 1024 {
            return Err(Error::Protocol);
        }
        bytes.extend_from_slice(&chunk)
    }
    Ok(serde_json::from_slice(&bytes)?)
}
fn probe(base: &str, key: &str, model: &str) -> Result<String> {
    let mut value = tokio::runtime::Handle::current().block_on(request(base, key, Some(model)))?;
    let result = value["choices"][0]["message"]["content"]
        .as_str()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .ok_or(Error::Protocol);
    erase(&mut value);
    result
}
fn full_id(raw: &str) -> Result<(&str, &str)> {
    let (provider, model) = raw
        .split_once('/')
        .ok_or(Error::Invalid("Use provider/model-id format."))?;
    if provider.is_empty() || model.is_empty() || model.contains('/') {
        return Err(Error::Invalid("Use provider/model-id format."));
    }
    Ok((provider, model))
}
pub(super) fn execute(
    action: &str,
    c: &Configuration,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    if c.server_role != "core" {
        return Err(Error::Invalid(
            "Local AI model configuration requires a core installation.",
        ));
    }
    let path = path(c);
    let mut overlay = read(&path)?;
    match action {
        "ai models" | "ai models list" => {
            let models=overlay.0["providers"].as_array().unwrap().iter().flat_map(|p|p["models"].as_array().unwrap().iter().map(|m|json!({"id":format!("{}/{}",p["provider_id"].as_str().unwrap(),m["id"].as_str().unwrap_or("")),"name":m.get("name").or(m.get("id")),"server":m["servers"][0]["id"],"serverModelId":m["servers"][0]["model_id"]}))).collect::<Vec<_>>();
            Ok(json!({"overlayPath":path,"models":models}))
        }
        "ai models add" => {
            use std::io::IsTerminal;
            let runtime = ask(
                flags,
                "runtime",
                "Runtime (ollama/lm-studio/custom)",
                Some("ollama"),
            )?;
            let (runtime_id, label, default_url, default_key) =
                match runtime.to_lowercase().replace('_', "-").as_str() {
                    "ollama" => (
                        "ollama",
                        "Ollama",
                        Some("http://host.docker.internal:11434/v1"),
                        "ollama",
                    ),
                    "lmstudio" | "lm-studio" => (
                        "lm_studio",
                        "LM Studio",
                        Some("http://host.docker.internal:1234/v1"),
                        "lm-studio",
                    ),
                    _ => (
                        "custom_openai_compatible",
                        "Custom OpenAI-compatible API",
                        None,
                        "local",
                    ),
                };
            let base = ask(flags, "base-url", "OpenAI-compatible base URL", default_url)?;
            endpoint(&base)?;
            let key: Zeroizing<String> = if let Some(key) = text(flags, "api-key") {
                Zeroizing::new(key.into())
            } else if runtime_id == "custom_openai_compatible" && std::io::stdin().is_terminal() {
                eprintln!("Local runtime API key (leave empty for local):");
                let value = configuration::prompt()?;
                if value.is_empty() {
                    Zeroizing::new(default_key.into())
                } else {
                    value
                }
            } else {
                Zeroizing::new(default_key.into())
            };
            let discovered = if text(flags, "model").is_none() && std::io::stdin().is_terminal() {
                tokio::runtime::Handle::current()
                    .block_on(request(&base, &key, None))
                    .ok()
                    .map(Overlay)
            } else {
                None
            };
            let available = discovered
                .as_ref()
                .and_then(|o| o.0["data"].as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|m| m["id"].as_str())
                        .filter(|s| {
                            !s.is_empty() && s.len() <= 4096 && !s.contains(['\n', '\r', '\0'])
                        })
                        .take(100)
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            if !available.is_empty() {
                eprintln!("Installed local model IDs:");
                for model in &available {
                    eprintln!("  {model}")
                }
            }
            let model = ask(flags, "model", "Local model ID", available.first().copied())?;
            if model.is_empty() || model.len() > 4096 || model.contains(['\n', '\r', '\0']) {
                return Err(Error::Invalid("Local model ID is invalid."));
            }
            let (inferred, name) = creator(&model);
            let provider = normalize(text(flags, "creator").unwrap_or(inferred), true);
            let provider_name = if provider == inferred {
                name
            } else {
                &provider
            };
            let id = text(flags, "id")
                .map(|s| normalize(s, false))
                .unwrap_or_else(|| format!("{}-local", normalize(&model, false)));
            let display = text(flags, "name").unwrap_or(&model);
            let context = text(flags, "context-window")
                .map(|s| {
                    s.parse::<u64>().map_err(|_| {
                        Error::Invalid("Context window must be a positive token count.")
                    })
                })
                .transpose()?
                .unwrap_or(32768);
            if context == 0 || context > i32::MAX as u64 {
                return Err(Error::Invalid(
                    "Context window must be a positive token count.",
                ));
            }
            if !boolean(flags, "skip-test") {
                let mut output = probe(&base, &key, &model)?;
                output.zeroize();
            }
            let tools = boolean(flags, "tools") || boolean(flags, "tool-use");
            let images =
                boolean(flags, "images") || boolean(flags, "image") || boolean(flags, "vision");
            let model = json!({"id":id,"name":display,"description":format!("{display} served locally through {label}."),"country_origin":"local","for_app_skill":"ai.ask","allow_auto_select":false,"local":true,"self_hosted":true,"input_types":if images{vec!["text","image"]}else{vec!["text"]},"output_types":["text"],"default_server":runtime_id,"servers":[{"id":runtime_id,"name":label,"model_id":model.as_str(),"region":"local","base_url":base.trim_end_matches('/'),"api_key":key.as_str(),"supports_tools":tools}],"pricing":{"fixed":{"credits":0}},"costs":{"input_per_million_token":{"price":0,"currency":"USD","max_context":context},"output_per_million_token":{"price":0,"currency":"USD","max_context":context}},"features":{"streaming":true,"tool_use":tools,"max_context":context}});
            let providers = overlay.0["providers"].as_array_mut().unwrap();
            let index=providers.iter().position(|p|p["provider_id"]==provider).unwrap_or_else(||{providers.push(json!({"provider_id":provider,"name":provider_name,"description":format!("Local self-hosted models for {provider_name}."),"models":[]}));providers.len()-1});
            let models = providers[index]["models"].as_array_mut().unwrap();
            models.retain_mut(|m| {
                if m["id"] == id {
                    erase(m);
                    false
                } else {
                    true
                }
            });
            models.push(model);
            write(&path, &overlay)?;
            Ok(
                json!({"command":"server ai models add","status":"success","model":format!("{provider}/{id}"),"overlayPath":path,"restartRequired":true}),
            )
        }
        "ai models test" | "ai models remove" => {
            let raw = args
                .first()
                .ok_or(Error::Invalid("Provide a provider/model-id."))?;
            let (provider, model) = full_id(raw)?;
            let found = overlay.0["providers"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|p| p["provider_id"] == provider)
                .and_then(|p| p["models"].as_array_mut());
            if action.ends_with("remove") {
                let mut removed = false;
                if let Some(models) = found {
                    models.retain_mut(|m| {
                        if m["id"] == model {
                            removed = true;
                            erase(m);
                            false
                        } else {
                            true
                        }
                    })
                }
                if removed {
                    write(&path, &overlay)?;
                }
                return Ok(
                    json!({"command":"server ai models remove","status":if removed{"success"}else{"not_found"},"model":raw,"restartRequired":removed}),
                );
            }
            let server = found
                .and_then(|m| m.iter().find(|m| m["id"] == model))
                .map(|m| &m["servers"][0])
                .ok_or(Error::Invalid("Local model was not found."))?;
            let output = probe(
                server["base_url"].as_str().ok_or(Error::Protocol)?,
                server["api_key"].as_str().unwrap_or("local"),
                server["model_id"].as_str().ok_or(Error::Protocol)?,
            )?;
            Ok(json!({"model":raw,"status":"success","output":output}))
        }
        _ => Err(Error::Invalid("Unknown local-model command.")),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn private_overlay_roundtrip_preserves_other_models_and_never_lists_keys() {
        use std::os::unix::fs::PermissionsExt;
        let temp = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = temp.path().into();
        let mut flags = Flags::from([
            ("model".into(), json!("qwen:small")),
            ("api-key".into(), json!("synthetic-secret")),
            ("skip-test".into(), json!(true)),
            ("images".into(), json!(true)),
        ]);
        fake::with(vec![], || {
            execute("ai models add", &c, &[], &flags).unwrap();
            flags.insert("model".into(), json!("qwen:other"));
            execute("ai models add", &c, &[], &flags).unwrap();
        });
        let listed = execute("ai models list", &c, &[], &Flags::new()).unwrap();
        assert_eq!(listed["models"].as_array().unwrap().len(), 2);
        assert!(!listed.to_string().contains("synthetic-secret"));
        assert_eq!(
            std::fs::metadata(path(&c)).unwrap().permissions().mode() & 0o777,
            0o600
        );
        let overlay = read(&path(&c)).unwrap();
        assert_eq!(
            overlay.0["providers"][0]["models"][0]["allow_auto_select"],
            false
        );
        assert_eq!(
            overlay.0["providers"][0]["models"][0]["pricing"]["fixed"]["credits"],
            0
        );
        drop(overlay);
        assert_eq!(
            execute(
                "ai models remove",
                &c,
                &["alibaba/qwen-small-local".into()],
                &Flags::new()
            )
            .unwrap()["status"],
            "success"
        );
        assert_eq!(
            execute("ai models list", &c, &[], &Flags::new()).unwrap()["models"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            execute(
                "ai models remove",
                &c,
                &["alibaba/missing".into()],
                &Flags::new()
            )
            .unwrap()["status"],
            "not_found"
        );
    }
    #[test]
    fn model_normalization_and_url_validation_are_bounded() {
        assert_eq!(
            normalize(" Qwen:Small / latest ", false),
            "qwen-small-latest"
        );
        assert_eq!(normalize("Creator!Name", true), "creator_name");
        assert_eq!(creator("a/qwen:small").0, "alibaba");
        assert_eq!(creator("qwen3:4b").0, "alibaba");
        assert!(endpoint("file:///tmp/model").is_err());
        assert!(endpoint("https://user:key@example.org/v1").is_err());
        assert!(endpoint("http://127.0.0.1:11434/v1").is_ok());
        assert!(full_id("creator/model/extra").is_err());
    }
    #[tokio::test]
    async fn synthetic_http_probe_has_exact_explicit_model_and_no_redirects() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![0; 8192];
            let n = socket.read(&mut bytes).await.unwrap();
            let request = String::from_utf8_lossy(&bytes[..n]);
            assert!(request.starts_with("POST /v1/chat/completions HTTP/1.1"));
            assert!(
                request
                    .to_lowercase()
                    .contains("authorization: bearer fixture-key")
            );
            let body = request.split("\r\n\r\n").nth(1).unwrap();
            let body: Value = serde_json::from_str(body).unwrap();
            assert_eq!(body["model"], "fixture-only");
            assert_eq!(body["stream"], false);
            let body = r#"{"choices":[{"message":{"content":"3"}}]}"#;
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
        });
        let value = request(
            &format!("http://{addr}/v1"),
            "fixture-key",
            Some("fixture-only"),
        )
        .await
        .unwrap();
        assert_eq!(value["choices"][0]["message"]["content"], "3");
        server.await.unwrap();
    }
}
