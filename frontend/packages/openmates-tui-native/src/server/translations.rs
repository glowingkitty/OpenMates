//! Native source-install locale generation, matching the canonical YAML data
//! shape without requiring Node or executing the legacy translation script.
use super::*;
type Namespaces = BTreeMap<String, BTreeMap<String, Value>>;
fn load(root: &Path, prefix: &str, namespaces: &mut Namespaces) -> Result<()> {
    let mut entries = std::fs::read_dir(root)?.collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        let kind = entry.file_type()?;
        let name = entry.file_name();
        let name = name.to_str().ok_or(Error::Io)?;
        if kind.is_symlink() {
            return Err(Error::Invalid(
                "Translation sources must not be symbolic links.",
            ));
        }
        if kind.is_dir() {
            let child = if prefix.is_empty() {
                name.to_owned()
            } else {
                format!("{prefix}.{name}")
            };
            load(&entry.path(), &child, namespaces)?;
        } else if kind.is_file() && name.ends_with(".yml") {
            let bytes = fs::read(&entry.path(), 16 * 1024 * 1024)?;
            let data: Value = serde_yaml::from_slice(&bytes)
                .map_err(|_| Error::Invalid("Translation YAML could not be parsed."))?;
            let Some(data) = data.as_object() else {
                continue;
            };
            if data.is_empty() {
                continue;
            }
            let stem = name.trim_end_matches(".yml");
            let namespace = if prefix.is_empty() { stem } else { prefix };
            let key_prefix = if prefix.is_empty() || stem == "main" {
                ""
            } else {
                stem
            };
            let target = namespaces.entry(namespace.into()).or_default();
            for (key, value) in data {
                let key = if key_prefix.is_empty() || key == key_prefix {
                    key.clone()
                } else {
                    format!("{key_prefix}.{key}")
                };
                target.insert(key, value.clone());
            }
        }
    }
    Ok(())
}
fn nested(target: &mut Value, path: &str, value: Value) -> Result<()> {
    let mut current = target;
    let parts = path.split('.').collect::<Vec<_>>();
    if parts
        .iter()
        .any(|p| p.is_empty() || matches!(*p, "__proto__" | "constructor" | "prototype"))
    {
        return Err(Error::Invalid("Translation key is invalid."));
    }
    for key in parts.iter().take(parts.len() - 1) {
        if !current.is_object() {
            *current = json!({})
        }
        current = current
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .entry((*key).to_owned())
            .or_insert_with(|| json!({}));
    }
    let key = *parts.last().ok_or(Error::Protocol)?;
    let entry = current
        .as_object_mut()
        .ok_or(Error::Protocol)?
        .entry(key.to_owned())
        .or_insert_with(|| json!({}));
    if let (Some(a), Some(b)) = (entry.as_object_mut(), value.as_object()) {
        a.extend(b.clone())
    } else {
        *entry = value;
    }
    Ok(())
}
fn render(namespaces: &Namespaces, language: &str) -> Result<Value> {
    let mut out = json!({});
    for (namespace, items) in namespaces {
        let mut target = json!({});
        for (key, value) in items {
            if !value.is_object() {
                continue;
            }
            let text = value
                .get(language)
                .filter(|v| !v.is_null())
                .cloned()
                .unwrap_or_else(|| json!(""));
            if text == "" && namespace != "metadata" {
                continue;
            }
            let text = if let Some(text) = text.as_str() {
                json!(text.trim_end_matches('\n'))
            } else {
                text
            };
            nested(&mut target, key, json!({"text":text}))?;
        }
        out[namespace] = target;
    }
    Ok(out)
}
pub(super) fn generate(root: &Path) -> Result<()> {
    let relative = root.join("frontend/packages/ui/src/i18n");
    let mut data = Namespaces::new();
    load(&relative.join("sources"), "", &mut data)?;
    if data.is_empty() {
        return Err(Error::Invalid("Source checkout has no translation YAML."));
    }
    let languages: Value =
        serde_json::from_slice(&fs::read(&relative.join("languages.json"), 128 * 1024)?)?;
    for language in languages["languages"].as_array().ok_or(Error::Protocol)? {
        let code = language["code"]
            .as_str()
            .filter(|s| s.len() <= 16 && s.bytes().all(|b| b.is_ascii_alphabetic() || b == b'-'))
            .ok_or(Error::Protocol)?;
        let output = render(&data, code)?;
        fs::write(
            &relative.join("locales").join(format!("{code}.json")),
            &serde_json::to_vec_pretty(&output)?,
            0o600,
        )?;
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dotted_keys_preserve_parent_text_and_yaml_newlines() {
        let data = BTreeMap::from([
            (
                "settings".into(),
                BTreeMap::from([
                    ("privacy.description".into(), json!({"en":"Child\n\n"})),
                    ("privacy".into(), json!({"en":"Privacy"})),
                ]),
            ),
            (
                "metadata".into(),
                BTreeMap::from([("default.title".into(), json!({"en":""}))]),
            ),
        ]);
        let result = render(&data, "en").unwrap();
        assert_eq!(result["settings"]["privacy"]["text"], "Privacy");
        assert_eq!(
            result["settings"]["privacy"]["description"]["text"],
            "Child"
        );
        assert_eq!(result["metadata"]["default"]["title"]["text"], "");
    }
}
