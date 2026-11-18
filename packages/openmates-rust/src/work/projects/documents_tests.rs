//! New Project files: blank content per kind and the ciphertext boundary of the upload body.
use super::*;

const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const EMBED: &str = "abcdef12-1111-4111-8111-111111111111";
const ITEM: &str = "33333333-3333-4333-8333-333333333333";

fn body(kind: ProjectDocumentKind, name: &str, folder: Option<&str>) -> (Value, String) {
    document_body(&DocumentRequest {
        project_id: PROJECT,
        project_key: &[1; 32],
        master_key: &[2; 32],
        embed_key: &[3; 32],
        embed_id: EMBED,
        project_item_id: ITEM,
        kind,
        name,
        folder_id: folder,
        timestamp: 1_700_000_000,
    })
    .expect("body")
}

fn open(ciphertext: &Value, key: &[u8; 32]) -> String {
    crypto::server_fields::decrypt_text(ciphertext.as_str().expect("text"), key, &[])
        .expect("decrypt")
}

#[test]
fn deck_markup_is_normalised_and_escaped() {
    let (_, content) = body(ProjectDocumentKind::Slides, "Q&A <\"1\">", None);
    let content: Value = serde_json::from_str(&content).expect("json");
    assert_eq!(
        content["slides_markup"],
        "<deck title=\"Q&amp;A &lt;&quot;1&quot;&gt;\" aspect=\"16:9\" template=\"builtin:plain\">\n  <slide id=\"s1\" layout=\"title\">\n    <text id=\"e1\" role=\"title\">Q&amp;A &lt;\"1\"&gt;</text>\n  </slide>\n</deck>\n"
    );
    assert_eq!(content["slide_count"], 1);
}

#[test]
fn blank_content_matches_the_web_fields() {
    let (_, doc) = body(ProjectDocumentKind::Document, "Notes", None);
    let doc: Value = serde_json::from_str(&doc).expect("json");
    assert_eq!(doc["type"], "docs-doc");
    assert_eq!(doc["html"], "<p></p>");
    assert_eq!(doc["filename"], "Notes.docx");
    let (_, sheet) = body(ProjectDocumentKind::Sheet, "Budget", None);
    let sheet: Value = serde_json::from_str(&sheet).expect("json");
    assert_eq!(sheet["row_count"], 8);
    assert_eq!(sheet["table"].as_str().expect("table").lines().count(), 10);
    let (_, code) = body(ProjectDocumentKind::Code, "main.py", None);
    let code: Value = serde_json::from_str(&code).expect("json");
    assert_eq!(code["code"], "");
    assert_eq!(code["line_count"], 1);
    assert!(code["language"].is_string());
    assert_eq!(code["status"], "finished");
    assert!(
        code["embed_ref"]
            .as_str()
            .expect("ref")
            .ends_with("-abcdef")
    );
}

#[test]
fn upload_body_is_ciphertext_with_both_key_wrappers() {
    let (body, content) = body(ProjectDocumentKind::Document, "Notes", Some("folder-1"));
    let embed = &body["embed"];
    assert_eq!(open(&embed["encrypted_content"], &[3; 32]), content);
    assert_eq!(open(&embed["encrypted_type"], &[3; 32]), "docs-doc");
    assert_eq!(embed["app_id"], "docs");
    assert_eq!(embed["encryption_mode"], "client");
    let keys = body["embed_keys"].as_array().expect("keys");
    let unwrap = |row: &Value, key: &[u8; 32]| {
        crypto::server_fields::decrypt_bytes(
            row["encrypted_embed_key"].as_str().expect("wrapper"),
            key,
            &[],
        )
        .expect("unwrap")
    };
    assert_eq!(keys[0]["key_type"], "master");
    assert_eq!(unwrap(&keys[0], &[2; 32]).as_slice(), &[3u8; 32]);
    assert_eq!(keys[1]["key_type"], "project");
    assert_eq!(keys[1]["hashed_project_id"], hash(PROJECT));
    assert_eq!(unwrap(&keys[1], &[1; 32]).as_slice(), &[3u8; 32]);
    let item = &body["item"];
    assert_eq!(item["folder_id"], "folder-1");
    assert_eq!(open(&item["encrypted_display_name"], &[1; 32]), "Notes");
    assert_eq!(open(&item["target_id_encrypted"], &[1; 32]), EMBED);
    assert!(!body.to_string().contains("Notes"));
}

#[test]
fn an_empty_name_is_refused() {
    let result = document_body(&DocumentRequest {
        project_id: PROJECT,
        project_key: &[1; 32],
        master_key: &[2; 32],
        embed_key: &[3; 32],
        embed_id: EMBED,
        project_item_id: ITEM,
        kind: ProjectDocumentKind::Code,
        name: "  ",
        folder_id: None,
        timestamp: 1,
    });
    assert!(matches!(result, Err(Error::Invalid(_))));
}
