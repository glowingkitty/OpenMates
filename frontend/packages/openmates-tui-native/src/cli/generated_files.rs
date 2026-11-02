//! Native adapter for generated files; direct execution remains shared Rust.
//! JSON is URL-only unless an explicit destination was supplied. Private partial
//! files publish atomically; failure never retries a skill or replaces a target.
use super::*;
use std::{
    io::Write,
    path::{Path, PathBuf},
};
const FLAGS: &[&str] = &["output", "output-dir", "filename", "no-download"];
pub(super) fn flags() -> &'static [&'static str] {
    FLAGS
}
struct Options {
    enabled: bool,
    directory: PathBuf,
    output: Option<PathBuf>,
    filename: Option<String>,
}
fn options(i: &Invocation, input: &Value) -> Result<Options, CliError> {
    let option = |key: &str| -> Result<Option<String>, CliError> {
        match i.flags.get(key) {
            None => Ok(None),
            Some(Value::String(v)) if !v.trim().is_empty() => Ok(Some(v.clone())),
            _ => Err(CliError::Invalid(format!(
                "--{key} requires a path or name"
            ))),
        }
    };
    let output = option("output")?;
    let directory = option("output-dir")?;
    let filename = option("filename")?;
    if output.is_some() && (directory.is_some() || filename.is_some()) {
        return Err(CliError::Invalid(
            "--output cannot be combined with --output-dir or --filename".into(),
        ));
    }
    if filename
        .as_ref()
        .is_some_and(|v| v == "." || v == ".." || v.contains(['/', '\\', '\0']))
    {
        return Err(CliError::Invalid(
            "--filename must be a filename without directories".into(),
        ));
    }
    if i.boolean("no-download") && (output.is_some() || directory.is_some() || filename.is_some()) {
        return Err(CliError::Invalid(
            "--no-download cannot be combined with download destinations".into(),
        ));
    }
    if (output.is_some() || filename.is_some())
        && input["requests"].as_array().is_some_and(|r| r.len() > 1)
    {
        return Err(CliError::Invalid(
            "One filename cannot name multiple generated files; use --output-dir".into(),
        ));
    }
    let enabled = !i.boolean("no-download")
        && (!i.boolean("json") || output.is_some() || directory.is_some() || filename.is_some());
    let current = std::env::current_dir().map_err(|_| Error::Io)?;
    let absolute = |path: PathBuf| {
        if path.is_absolute() {
            path
        } else {
            current.join(path)
        }
    };
    Ok(Options {
        enabled,
        directory: absolute(
            directory
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(".")),
        ),
        output: output.map(|v| absolute(PathBuf::from(v))),
        filename,
    })
}
struct File {
    url: String,
    filename: String,
    asset: Option<String>,
}
fn text(v: &Value, key: &str) -> Option<String> {
    v[key].as_str().filter(|s| !s.is_empty()).map(str::to_owned)
}
fn safe_name(value: &str) -> String {
    let name = value
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or("")
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || "._-".contains(c) {
                c
            } else {
                '_'
            }
        })
        .collect::<String>();
    let name = name.trim_start_matches('.');
    if name.is_empty() {
        "generated-file".into()
    } else {
        name.into()
    }
}
fn collect(value: &Value) -> Vec<File> {
    fn add(meta: &Value, parent: &Value, variant: &str, files: &mut Vec<File>) {
        let asset = text(meta, "asset_id")
            .or_else(|| text(parent, "embed_id"))
            .or_else(|| text(parent, "asset_id"));
        let url = text(meta, "download_url").or_else(|| {
            asset.as_ref().map(|id| {
                format!(
                    "/v1/embeds/{}/file?format={}",
                    url::form_urlencoded::byte_serialize(id.as_bytes()).collect::<String>(),
                    url::form_urlencoded::byte_serialize(variant.as_bytes()).collect::<String>()
                )
            })
        });
        let Some(url) = url else { return };
        if files.iter().any(|f| f.url == url) {
            return;
        }
        let extension = text(meta, "format")
            .or_else(|| match meta["mime_type"].as_str() {
                Some("audio/mpeg") => Some("mp3".into()),
                Some("audio/wav") => Some("wav".into()),
                Some("image/png") => Some("png".into()),
                Some("image/jpeg") => Some("jpg".into()),
                Some("image/webp") => Some("webp".into()),
                Some("video/mp4") => Some("mp4".into()),
                Some("application/pdf") => Some("pdf".into()),
                Some("model/gltf-binary") => Some("glb".into()),
                _ => None,
            })
            .unwrap_or_else(|| variant.into());
        let filename = text(meta, "filename")
            .or_else(|| text(meta, "path"))
            .or_else(|| text(parent, "filename"))
            .map(|n| safe_name(&n))
            .unwrap_or_else(|| {
                format!(
                    "openmates-{}.{}",
                    safe_name(asset.as_deref().unwrap_or("generated")),
                    safe_name(&extension)
                )
            });
        files.push(File {
            url,
            filename,
            asset,
        });
    }
    fn visit(v: &Value, files: &mut Vec<File>) {
        if let Some(rows) = v.as_array() {
            for row in rows {
                visit(row, files)
            }
            return;
        }
        if !v.is_object() {
            return;
        }
        if let Some(variants) = v["files"].as_object() {
            let preferred = [
                "original",
                "master",
                "full",
                v["output_filetype"].as_str().unwrap_or(""),
            ];
            let chosen = preferred
                .iter()
                .find_map(|key| {
                    variants
                        .get(*key)
                        .filter(|v| v.is_object())
                        .map(|v| (*key, v))
                })
                .or_else(|| {
                    variants
                        .iter()
                        .find(|(name, v)| {
                            v.is_object()
                                && !name.to_ascii_lowercase().contains("preview")
                                && !name.to_ascii_lowercase().contains("thumbnail")
                                && !name.to_ascii_lowercase().contains("poster")
                        })
                        .map(|(k, v)| (k.as_str(), v))
                });
            if let Some((name, meta)) = chosen {
                add(meta, v, name, files);
            }
        }
        for field in ["artifacts", "files"] {
            if let Some(rows) = v[field].as_array() {
                for meta in rows {
                    if meta["download_url"].as_str().is_some() {
                        add(
                            meta,
                            v,
                            meta["variant"].as_str().unwrap_or("original"),
                            files,
                        );
                    }
                }
            }
        }
        for field in ["data", "result", "results", "items", "final"] {
            if let Some(nested) = v.get(field) {
                visit(nested, files);
            }
        }
    }
    let mut files = vec![];
    visit(value, &mut files);
    files
}
struct Partial(PathBuf);
impl Drop for Partial {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn publish(partial: &Path, target: &Path, explicit: bool) -> Result<PathBuf, CliError> {
    if explicit {
        std::fs::rename(partial, target).map_err(|_| Error::Io)?;
        return Ok(target.into());
    }
    for suffix in 0u64.. {
        let candidate = if suffix == 0 {
            target.to_path_buf()
        } else {
            let stem = target
                .file_stem()
                .and_then(|v| v.to_str())
                .unwrap_or("generated");
            let name = match target.extension().and_then(|v| v.to_str()) {
                Some(ext) => format!("{stem}-{suffix}.{ext}"),
                None => format!("{stem}-{suffix}"),
            };
            target.with_file_name(name)
        };
        match std::fs::hard_link(partial, &candidate) {
            Ok(()) => return Ok(candidate),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => return Err(Error::Io.into()),
        }
    }
    unreachable!()
}
pub(super) fn validate(i: &Invocation, input: &Value) -> Result<(), CliError> {
    options(i, input).map(|_| ())
}
pub(super) async fn finish(
    i: &Invocation,
    client: &mut crate::client::Client,
    publication: &openmates_sdk::client::DirectAppSkillAdmission,
    store: Option<(&crate::runtime_store::RuntimeStore,u64)>,
    input: &Value,
    result: &mut Value,
) -> Result<Vec<String>, CliError> {
    let options = options(i, input)?;
    if !options.enabled {
        return Ok(vec![]);
    }
    let files = collect(result);
    let explicit = options.output.is_some() || options.filename.is_some();
    if explicit && files.len() != 1 {
        return Err(CliError::Invalid(format!(
            "Expected one generated file for the explicit filename; received {}. Use --output-dir for multiple files.",
            files.len()
        )));
    }
    let mut saved = vec![];
    let mut notices = vec![];
    for asset in files {
        let target = options.output.clone().unwrap_or_else(|| {
            options
                .directory
                .join(options.filename.as_ref().unwrap_or(&asset.filename))
        });
        let directory = target.parent().ok_or(Error::Io)?;
        std::fs::create_dir_all(directory).map_err(|_| Error::Io)?;
        let partial = Partial(directory.join(format!(".{}.partial", uuid::Uuid::new_v4())));
        let mut open = std::fs::OpenOptions::new();
        open.create_new(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            open.mode(0o600);
        }
        let mut file = open.open(&partial.0).map_err(|_| Error::Io)?;
        publication.check(client)?;
        // Core validates fixed authenticated routes vs uncredentialed provider URLs,
        // cancellation and original owner/resource scope around every body chunk.
        client
            .stream_generated_app_file(&asset.url, |chunk| {
                file.write_all(chunk).map_err(|_| Error::Io)
            })
            .await?;
        file.sync_all().map_err(|_| Error::Io)?;
        drop(file);
        publication.check(client)?;
        if store.is_some_and(|(store,generation)|store.generation()!=generation){return Err(Error::Cancelled.into());}
        let path = publish(&partial.0, &target, explicit)?
            .to_string_lossy()
            .into_owned();
        notices.push(path.clone());
        saved.push(match asset.asset {
            Some(id) => serde_json::json!({"path":path,"asset_id":id}),
            None => serde_json::json!({"path":path}),
        });
    }
    if !saved.is_empty() {
        result
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .insert("local_files".into(), Value::Array(saved));
    }
    Ok(notices)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn json_is_url_only_and_destinations_are_explicit() {
        let mut i = Invocation {
            path: vec![],
            positionals: vec![],
            flags: BTreeMap::from([("json".into(), Value::Bool(true))]),
        };
        assert!(!options(&i, &Value::Null).unwrap_or_else(|_| panic!("synthetic generated-file operation failed")).enabled);
        i.flags
            .insert("output".into(), Value::String("file.wav".into()));
        assert!(options(&i, &Value::Null).unwrap_or_else(|_| panic!("synthetic generated-file operation failed")).enabled);
        i.flags.insert("no-download".into(), Value::Bool(true));
        assert!(options(&i, &Value::Null).is_err());
    }
    #[test]
    fn malformed_destination_refuses_before_skill_dispatch() {
        let i = Invocation {
            path: vec![],
            positionals: vec![],
            flags: BTreeMap::from([
                ("output".into(), Value::String("one".into())),
                ("output-dir".into(), Value::String("two".into())),
            ]),
        };
        assert!(validate(&i, &Value::Null).is_err());
    }
    #[test]
    fn collection_uses_existing_original_asset_and_deduplicates() {
        let value = serde_json::json!({"data":{"items":[{"embed_id":"owned","files":{"preview":{"download_url":"https://example.invalid/p"},"original":{"download_url":"https://example.invalid/o","mime_type":"audio/mpeg"}}},{"artifacts":[{"download_url":"https://example.invalid/o"}]}]}});
        let files = collect(&value);
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].filename, "openmates-owned.mp3");
    }
    #[test]
    fn mixed_case_preview_is_never_preferred_to_the_actual_file() {
        let files=collect(&serde_json::json!({"files":{"Preview":{"download_url":"https://example.invalid/p"},"download":{"download_url":"https://example.invalid/d"}}}));
        assert_eq!(files.len(),1);assert_eq!(files[0].url,"https://example.invalid/d");
    }
    #[test]
    fn atomic_automatic_names_preserve_existing_and_explicit_replaces_after_complete() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("output.wav");
        let partial = dir.path().join("partial");
        std::fs::write(&target, b"old").unwrap();
        std::fs::write(&partial, b"new").unwrap();
        assert_eq!(
            publish(&partial, &target, false).unwrap_or_else(|_| panic!("synthetic generated-file operation failed")),
            dir.path().join("output-1.wav")
        );
        assert_eq!(std::fs::read(&target).unwrap(), b"old");
        publish(&partial, &target, true).unwrap_or_else(|_| panic!("synthetic generated-file operation failed"));
        assert_eq!(std::fs::read(target).unwrap(), b"new");
    }
}
