//! New empty documents, sheets, slide decks and code files in a Project
//! folder (shared core). Port of the web `createProjectDocument`
//! (`projectService.ts`): one client-encrypted embed with a master-key and a
//! Project-key wrapper plus its Project item link, sent in a single
//! `upload-embed` request without a chat. Spec: `projects.items.create-documents`,
//! `storage.privacy.ciphertext-boundary`. Shells only supply the name and folder.
use super::*;
use crate::embed_read::link::generate_direct_embed_ref;
use serde_json::Map;

/// Kind of a new Project file (web `ProjectDocumentKind`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectDocumentKind {
    /// A rich-text document (`docs-doc`).
    Document,
    /// A spreadsheet (`sheets-sheet`).
    Sheet,
    /// A slide deck (`slides-deck`).
    Slides,
    /// A code file (`code-code`).
    Code,
}

impl ProjectDocumentKind {
    /// Parse the wire name (`document`, `sheet`, `slides`, `code`).
    pub fn from_wire(value: &str) -> Option<Self> {
        Some(match value {
            "document" => Self::Document,
            "sheet" => Self::Sheet,
            "slides" => Self::Slides,
            "code" => Self::Code,
            _ => return None,
        })
    }

    /// `(embed type, app id, skill id, embed ref kind)` of the catalog entry.
    fn spec(self) -> (&'static str, &'static str, &'static str, &'static str) {
        match self {
            Self::Document => ("docs-doc", "docs", "document", "doc"),
            Self::Sheet => ("sheets-sheet", "sheets", "sheet", "sheet"),
            Self::Slides => ("slides-deck", "slides", "deck", "deck"),
            Self::Code => ("code-code", "code", "code", "code"),
        }
    }
}

/// A created Project file: what a shell needs to open it right away.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CreatedProjectDocument {
    /// The new embed id.
    pub embed_id: String,
    /// Embed type (`docs-doc`, `sheets-sheet`, `slides-deck`, `code-code`).
    pub embed_type: String,
    /// The Project item link id.
    pub project_item_id: String,
    /// Embed content as the JSON string the viewers decode.
    pub content: String,
}

struct Blank {
    fields: Map<String, Value>,
    hash_source: String,
    language: Option<&'static str>,
}

fn object(pairs: Vec<(&str, Value)>) -> Map<String, Value> {
    pairs.into_iter().map(|(k, v)| (k.to_owned(), v)).collect()
}

fn escape_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn escape_attr(value: &str) -> String {
    escape_text(value)
        .replace('"', "&quot;")
        .replace('\'', "&#x27;")
}

/// Blank content in the fields each viewer/editor reads. Slides markup is the
/// byte-exact normalised form (one element per line, trailing newline).
fn blank_content(kind: ProjectDocumentKind, name: &str) -> Blank {
    match kind {
        ProjectDocumentKind::Document => Blank {
            fields: object(vec![
                ("title", json!(name)),
                ("filename", json!(format!("{name}.docx"))),
                ("html", json!("<p></p>")),
                ("word_count", json!(0)),
            ]),
            hash_source: "<p></p>".into(),
            language: None,
        },
        ProjectDocumentKind::Sheet => {
            let rows = 8;
            let mut lines = vec![
                "| Column 1 | Column 2 | Column 3 |".to_owned(),
                "| --- | --- | --- |".to_owned(),
            ];
            lines.extend((0..rows).map(|_| "|  |  |  |".to_owned()));
            let table = lines.join("\n");
            Blank {
                fields: object(vec![
                    ("title", json!(name)),
                    ("table", json!(table)),
                    ("row_count", json!(rows)),
                    ("col_count", json!(3)),
                ]),
                hash_source: table,
                language: None,
            }
        }
        ProjectDocumentKind::Slides => {
            let markup = format!(
                "<deck title=\"{}\" aspect=\"16:9\" template=\"builtin:plain\">\n  <slide id=\"s1\" layout=\"title\">\n    <text id=\"e1\" role=\"title\">{}</text>\n  </slide>\n</deck>\n",
                escape_attr(name),
                escape_text(name)
            );
            Blank {
                fields: object(vec![
                    ("title", json!(name)),
                    ("slides_markup", json!(markup)),
                    ("slide_count", json!(1)),
                ]),
                hash_source: markup,
                language: None,
            }
        }
        ProjectDocumentKind::Code => Blank {
            fields: object(vec![
                ("code", json!("")),
                ("filename", json!(name)),
                ("line_count", json!(1)),
            ]),
            hash_source: String::new(),
            language: Some("text"),
        },
    }
}

/// The code language of a new code file: the shared upload route's language
/// when it routes the name as code, else `text` (as the web does).
fn code_language(name: &str) -> String {
    let input = json!({"fileName": name, "fileType": "", "importedFromRemote": false});
    crate::web_projects::run_json("projectUploadRoute", &input.to_string())
        .ok()
        .and_then(|out| serde_json::from_str::<Value>(&out).ok())
        .filter(|route| route["route"] == "code")
        .and_then(|route| route["language"].as_str().map(str::to_owned))
        .unwrap_or_else(|| "text".to_owned())
}

/// Everything one new Project file sends, built without IO.
pub(crate) struct DocumentRequest<'a> {
    pub(crate) project_id: &'a str,
    pub(crate) project_key: &'a [u8; 32],
    pub(crate) master_key: &'a [u8; 32],
    pub(crate) embed_key: &'a [u8; 32],
    pub(crate) embed_id: &'a str,
    pub(crate) project_item_id: &'a str,
    pub(crate) kind: ProjectDocumentKind,
    pub(crate) name: &'a str,
    pub(crate) folder_id: Option<&'a str>,
    pub(crate) timestamp: u64,
}

/// The `upload-embed` body and the plaintext content JSON string.
///
/// # Errors
/// `Invalid` for an empty name; encryption failures.
pub(crate) fn document_body(request: &DocumentRequest<'_>) -> Result<(Value, String)> {
    let name = request.name.trim();
    if name.is_empty() {
        return Err(Error::Invalid("A name is required."));
    }
    let (embed_type, app_id, skill_id, ref_kind) = request.kind.spec();
    let blank = blank_content(request.kind, name);
    let embed_ref = generate_direct_embed_ref(ref_kind, request.embed_id, Some(name), None, None);
    let mut content = object(vec![
        ("type", json!(embed_type)),
        ("app_id", json!(app_id)),
        ("skill_id", json!(skill_id)),
    ]);
    content.extend(blank.fields);
    if blank.language.is_some() {
        content.insert("language".into(), json!(code_language(name)));
    }
    content.insert("embed_ref".into(), json!(embed_ref));
    content.insert("status".into(), json!("finished"));
    content.insert("version_number".into(), json!(1));
    let content = serde_json::to_string(&content).map_err(Error::from)?;
    let metadata = json!({ "embed_type": embed_type }).to_string();
    let seal = |text: &str, key: &[u8; 32]| crypto::server_fields::encrypt_text(text, key, &[]);
    let hashed_embed_id = hash(request.embed_id);
    let body = json!({
        "embed": {
            "embed_id": request.embed_id,
            "encrypted_type": seal(embed_type, request.embed_key)?,
            "status": "finished",
            "encrypted_content": seal(&content, request.embed_key)?,
            "encrypted_text_preview": seal(name, request.embed_key)?,
            "content_hash": hash(&blank.hash_source),
            "created_at": request.timestamp,
            "updated_at": request.timestamp,
            "encryption_mode": "client",
            "is_private": true,
            "is_shared": false,
            "app_id": app_id,
            "skill_id": skill_id,
        },
        "embed_keys": [
            {
                "hashed_embed_id": hashed_embed_id,
                "key_type": "master",
                "encrypted_embed_key": crypto::server_fields::encrypt_bytes(request.embed_key, request.master_key, &[])?,
                "created_at": request.timestamp,
            },
            {
                "hashed_embed_id": hashed_embed_id,
                "key_type": "project",
                "hashed_project_id": hash(request.project_id),
                "encrypted_embed_key": crypto::server_fields::encrypt_bytes(request.embed_key, request.project_key, &[])?,
                "created_at": request.timestamp,
            },
        ],
        "item": {
            "project_item_id": request.project_item_id,
            "folder_id": request.folder_id,
            "item_type": "embed",
            "target_id": request.embed_id,
            "target_id_encrypted": seal(request.embed_id, request.project_key)?,
            "encrypted_display_name": seal(name, request.project_key)?,
            "encrypted_note": seal("", request.project_key)?,
            "encrypted_metadata": seal(&metadata, request.project_key)?,
            "created_at": request.timestamp,
            "updated_at": request.timestamp,
            "position": request.timestamp,
        },
    });
    Ok((body, content))
}

impl Projects<'_> {
    /// Create a new empty document, sheet, slide deck or code file named
    /// `name` in `folder_id` (Project root when `None`) of `project_id`.
    ///
    /// # Errors
    /// `Invalid` for an empty name or malformed ids; `Forbidden`; transport
    /// and crypto errors.
    pub async fn create_document(
        &mut self,
        project_id: &str,
        kind: ProjectDocumentKind,
        name: &str,
        folder_id: Option<&str>,
    ) -> Result<CreatedProjectDocument> {
        uuid(project_id)?;
        let project = self.resolve(project_id).await?;
        let master = self.backend.master().await?;
        let embed_key = crypto::random_key();
        let embed_id = uuid::Uuid::new_v4().to_string();
        let project_item_id = uuid::Uuid::new_v4().to_string();
        let (body, content) = document_body(&DocumentRequest {
            project_id,
            project_key: &project.key,
            master_key: &master,
            embed_key: &embed_key,
            embed_id: &embed_id,
            project_item_id: &project_item_id,
            kind,
            name,
            folder_id,
            timestamp: now(),
        })?;
        let route = self.path(&format!("/v1/projects/{project_id}/upload-embed"), &[]);
        self.backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        Ok(CreatedProjectDocument {
            embed_id,
            embed_type: kind.spec().0.to_owned(),
            project_item_id,
            content,
        })
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "documents_tests.rs"]
mod tests;
