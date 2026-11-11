//! Pure planning of embed adoption into a Project (shared core, P11): which
//! embeds of a finished turn become Project links, under which folder and
//! path, with which encrypted metadata plaintext. No IO; `adopt` executes the
//! plan. Contract:
//! `docs/plans/cloud-project-development/contracts/project-embed-adoption.md`.
use super::adopt::{AdoptEmbedKind, AdoptionTarget};
use super::*;

/// Default Project folder of a chat application.
pub(crate) const DEFAULT_APPLICATION_FOLDER: &str = "web-app";
/// `project_items` metadata `source` of an adopted application.
pub(crate) const APPLICATION_SOURCE: &str = "project_application";
/// `project_items` metadata `source` of an adopted test result.
pub(crate) const TEST_RESULT_SOURCE: &str = "project_test_result";

/// One child reference of an application embed (`file_refs[]`).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct FileRef {
    pub(crate) path: String,
    pub(crate) embed_id: String,
}

/// The adoption-relevant plaintext of one embed persisted in a turn. Code
/// content and other bodies never enter this record, so it stays small and
/// carries no file text through the saved-send phase boundary.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct TurnEmbed {
    pub(crate) embed_id: String,
    pub(crate) embed_type: String,
    #[serde(default)]
    pub(crate) parent_embed_id: Option<String>,
    #[serde(default)]
    pub(crate) status: String,
    #[serde(default)]
    pub(crate) filename: Option<String>,
    #[serde(default)]
    pub(crate) title: Option<String>,
    #[serde(default)]
    pub(crate) file_refs: Vec<FileRef>,
    #[serde(default)]
    pub(crate) run_id: Option<String>,
}

fn optional(content: &Value, keys: &[&str]) -> Option<String> {
    keys.iter()
        .find_map(|key| content[*key].as_str().filter(|value| !value.is_empty()))
        .map(str::to_owned)
}

impl TurnEmbed {
    /// The record of one persisted turn row (`send_embed_data` fields plus its
    /// decoded TOON content).
    pub(crate) fn from_row(embed_id: &str, row: &Value, content: &Value) -> Self {
        let text = |value: &Value| value.as_str().unwrap_or_default().to_owned();
        let status = optional(row, &["status"])
            .or_else(|| optional(content, &["status"]))
            .unwrap_or_default();
        let file_refs = content["file_refs"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|reference| {
                Some(FileRef {
                    path: reference["path"].as_str()?.to_owned(),
                    embed_id: reference["embed_id"].as_str()?.to_owned(),
                })
            })
            .collect();
        Self {
            embed_id: embed_id.to_owned(),
            embed_type: text(&row["type"]),
            parent_embed_id: optional(row, &["parent_embed_id"]),
            status,
            filename: optional(content, &["filename", "path"]),
            title: optional(content, &["name", "title"]),
            file_refs,
            run_id: optional(content, &["run_id", "execution_id"]),
        }
    }

    fn kind(&self) -> Option<AdoptEmbedKind> {
        AdoptEmbedKind::of_embed_type(&self.embed_type)
    }

    /// Whether this record can produce an adoption (an application or a test
    /// result; code files are adopted through their application).
    pub(crate) fn starts_adoption(&self) -> bool {
        matches!(
            self.kind(),
            Some(AdoptEmbedKind::Application | AdoptEmbedKind::TestResult)
        )
    }

    fn finished(&self) -> bool {
        self.status == "finished"
    }
}

/// A folder name from an application title: lowercase ASCII words joined by
/// `-` (the shared object-slug rule), `app-<embed prefix>` when nothing is left.
pub(crate) fn title_folder(title: &str, embed_id: &str) -> String {
    crypto::normalize_object_slug(title)
        .map(|slug| slug.chars().take(64).collect::<String>())
        .map(|slug| slug.trim_end_matches('-').to_owned())
        .ok()
        .filter(|slug| !slug.is_empty())
        .unwrap_or_else(|| format!("app-{}", embed_id.chars().take(8).collect::<String>()))
}

/// The folder of an application: `web-app` unless that folder already belongs
/// to a different application embed, then the title slug (suffixed `-2`, `-3`,
/// … while that is taken by yet another application). An application that is
/// already linked keeps its folder.
pub(crate) fn choose_folder(existing: &[(String, String)], embed_id: &str, title: &str) -> String {
    if let Some((folder, _)) = existing.iter().find(|(_, owner)| owner == embed_id) {
        return folder.clone();
    }
    let taken = |folder: &str| {
        existing
            .iter()
            .any(|(path, owner)| path == folder && owner != embed_id)
    };
    if !taken(DEFAULT_APPLICATION_FOLDER) {
        return DEFAULT_APPLICATION_FOLDER.to_owned();
    }
    let base = title_folder(title, embed_id);
    let mut candidate = base.clone();
    let mut suffix = 2;
    while taken(&candidate) || candidate == DEFAULT_APPLICATION_FOLDER {
        candidate = format!("{base}-{suffix}");
        suffix += 1;
    }
    candidate
}

/// `(folder, application embed id)` of every adopted application link of the
/// Project listing (`/v1/projects/{id}` items), decrypted with its key.
///
/// # Errors
/// A malformed listing or a link that does not authenticate.
pub(crate) fn application_folders(
    items: &Value,
    key: &[u8; 32],
) -> HostedResult<Vec<(String, String)>> {
    let mut folders = Vec::new();
    for item in items
        .as_array()
        .ok_or(HostedFileError::Core(Error::Protocol))?
    {
        let metadata = super::super::items::optional_text(item, "encrypted_metadata", key)?;
        if metadata.is_empty() {
            continue;
        }
        let metadata: Value =
            serde_json::from_str(&metadata).map_err(|_| HostedFileError::Core(Error::Crypto))?;
        if metadata["source"] != APPLICATION_SOURCE {
            continue;
        }
        let target = super::super::items::optional_text(item, "target_id_encrypted", key)?;
        if let Some(folder) = metadata["path"].as_str() {
            folders.push((folder.to_owned(), target));
        }
    }
    Ok(folders)
}

/// Metadata plaintext of an adopted file (contract "Metadata plaintext").
pub(crate) fn file_metadata(path: &str, application: Option<(&str, &str)>) -> Value {
    json!({
        "path": path,
        "source": HOSTED_SOURCE,
        "application_embed_id": application.map(|(embed, _)| embed),
        "application_path": application.map(|(_, relative)| relative),
    })
}

/// Metadata plaintext of an adopted application.
pub(crate) fn application_metadata(folder: &str, entry_path: Option<&str>) -> Value {
    json!({"path": folder, "source": APPLICATION_SOURCE, "entry_path": entry_path})
}

/// Metadata plaintext of an adopted test result.
pub(crate) fn test_result_metadata(run_id: Option<&str>) -> Value {
    json!({"source": TEST_RESULT_SOURCE, "run_id": run_id})
}

/// The application's entry file: the first conventional web entry among its
/// files, else its first file.
pub(crate) fn entry_path(refs: &[FileRef]) -> Option<String> {
    const ENTRIES: [&str; 5] = [
        "index.html",
        "src/main.ts",
        "src/main.js",
        "src/App.svelte",
        "main.py",
    ];
    ENTRIES
        .iter()
        .find(|entry| refs.iter().any(|r| r.path == **entry))
        .map(|entry| (*entry).to_owned())
        .or_else(|| refs.first().map(|r| r.path.clone()))
}

/// The adoptions of one finished turn, in contract order: per application its
/// finished child files at `<folder>/<path>`, then the application itself;
/// then the turn's finished test results. A child path the hosted policy
/// refuses is reported as a failed row instead of being adopted.
pub(crate) fn plan_turn(
    chat_id: &str,
    embeds: &[TurnEmbed],
    existing: &[(String, String)],
) -> Vec<HostedResult<AdoptionTarget>> {
    let mut plan = Vec::new();
    let mut folders = existing.to_vec();
    for application in embeds
        .iter()
        .filter(|e| e.kind() == Some(AdoptEmbedKind::Application) && e.finished())
    {
        let title = application.title.as_deref().unwrap_or_default();
        let folder = choose_folder(&folders, &application.embed_id, title);
        folders.push((folder.clone(), application.embed_id.clone()));
        for reference in &application.file_refs {
            let Some(child) = embeds.iter().find(|e| {
                e.embed_id == reference.embed_id && e.kind() == Some(AdoptEmbedKind::File)
            }) else {
                continue;
            };
            if !child.finished() {
                continue;
            }
            let joined = format!("{folder}/{}", reference.path);
            plan.push(normalize_path(&json!(joined)).map(|path| AdoptionTarget {
                chat_id: chat_id.to_owned(),
                embed_id: child.embed_id.clone(),
                kind: AdoptEmbedKind::File,
                metadata: file_metadata(&path, Some((&application.embed_id, &reference.path))),
                display_name: path.clone(),
                path: Some(path),
            }));
        }
        let entry = entry_path(&application.file_refs);
        plan.push(Ok(AdoptionTarget {
            chat_id: chat_id.to_owned(),
            embed_id: application.embed_id.clone(),
            kind: AdoptEmbedKind::Application,
            metadata: application_metadata(&folder, entry.as_deref()),
            display_name: if title.is_empty() {
                folder.clone()
            } else {
                title.to_owned()
            },
            path: Some(folder),
        }));
    }
    for result in embeds
        .iter()
        .filter(|e| e.kind() == Some(AdoptEmbedKind::TestResult) && e.finished())
    {
        plan.push(Ok(test_result_target(chat_id, result)));
    }
    plan
}

fn test_result_target(chat_id: &str, embed: &TurnEmbed) -> AdoptionTarget {
    AdoptionTarget {
        chat_id: chat_id.to_owned(),
        embed_id: embed.embed_id.clone(),
        kind: AdoptEmbedKind::TestResult,
        metadata: test_result_metadata(embed.run_id.as_deref()),
        display_name: embed
            .title
            .clone()
            .unwrap_or_else(|| "Test result".to_owned()),
        path: None,
    }
}

/// The explicit-repair adoption of one existing embed. A file or application
/// needs `path` (the full Project file path, or the application folder); a
/// test result ignores it.
///
/// # Errors
/// `path_required` without a path, and the hosted path refusals.
pub(crate) fn repair_target(
    chat_id: &str,
    embed: &TurnEmbed,
    kind: AdoptEmbedKind,
    path: Option<&str>,
) -> HostedResult<AdoptionTarget> {
    if kind == AdoptEmbedKind::TestResult {
        return Ok(test_result_target(chat_id, embed));
    }
    let path = normalize_path(&json!(
        path.ok_or(HostedFileError::Refused("path_required"))?
    ))?;
    let (metadata, display_name) = match kind {
        AdoptEmbedKind::File => (file_metadata(&path, None), path.clone()),
        _ => (
            application_metadata(&path, entry_path(&embed.file_refs).as_deref()),
            embed.title.clone().unwrap_or_else(|| path.clone()),
        ),
    };
    Ok(AdoptionTarget {
        chat_id: chat_id.to_owned(),
        embed_id: embed.embed_id.clone(),
        kind,
        metadata,
        display_name,
        path: Some(path),
    })
}
