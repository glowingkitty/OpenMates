//! Project code-file text inside stored embed content: replayed history in
//! both forms and the restored head object.
use super::*;

const HEAD: &str = "type: code\nlanguage: javascript\nfilename: web-app/recipes.js\ncode: \"const recipes = [];\\n\"\nversion_number: 2\nstatus: finished\nline_count: 2";

#[test]
fn hosted_history_text_stays_text() {
    let text = version_text(Zeroizing::new("const recipes = [];\n".into()));
    assert_eq!(text.as_str(), "const recipes = [];\n");
}

#[test]
fn web_edit_snapshot_yields_its_code_text() {
    let text = version_text(Zeroizing::new(HEAD.into()));
    assert_eq!(text.as_str(), "const recipes = [];\n");
}

#[test]
fn project_code_snapshot_yields_only_the_source_text() {
    let project_head = HEAD.replacen("type: code", "type: code-code", 1);
    let text = version_text(Zeroizing::new(project_head));
    assert_eq!(text.as_str(), "const recipes = [];\n");
}

#[test]
fn json_source_file_is_not_mistaken_for_a_code_object() {
    let package = "{\"type\": \"module\", \"code\": \"x\"}";
    assert_eq!(
        version_text(Zeroizing::new(package.into())).as_str(),
        package
    );
}

#[test]
fn restored_head_keeps_fields_and_order_with_the_old_text() {
    let content = content_with_text(HEAD, "const recipes = [\"pancakes\"];\n", 3).expect("content");
    let fields = decode_content_fields(&content).expect("object");
    let keys: Vec<&str> = fields.iter().map(|(key, _)| key.as_str()).collect();
    assert_eq!(
        keys,
        [
            "type",
            "language",
            "filename",
            "code",
            "version_number",
            "status",
            "line_count"
        ]
    );
    let get = |name: &str| {
        fields
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, v)| v.clone())
    };
    assert_eq!(
        get("code"),
        Some(json!("const recipes = [\"pancakes\"];\n"))
    );
    assert_eq!(get("version_number"), Some(json!(3)));
    assert_eq!(get("line_count"), Some(json!(2)));
    assert_eq!(
        version_text(content).as_str(),
        "const recipes = [\"pancakes\"];\n"
    );
}

#[test]
fn legacy_content_field_is_replaced_in_place() {
    let legacy = "{\"type\":\"code\",\"content\":\"a\"}";
    let content = content_with_text(legacy, "b\nc", 2).expect("content");
    let fields = decode_content_fields(&content).expect("object");
    assert!(fields.iter().all(|(key, _)| key != "code"));
    assert_eq!(version_text(content).as_str(), "b\nc");
}

#[test]
fn refuses_a_head_that_is_not_an_object() {
    assert!(content_with_text("plain text", "x", 2).is_err());
}

#[test]
fn code_edit_content_replaces_code_fields_and_keeps_the_rest() {
    let text = code_edit_content(
        r#"{"type":"code","language":"rust","code":"old","line_count":1,"content_hash":"x","version_number":1}"#,
        "a\nb\n",
        2,
    )
    .expect("object head encodes");
    let value = crate::toon_decode::decode(&text).expect("valid TOON").to_json_value();
    assert_eq!(value["language"], "rust");
    assert_eq!(value["code"], "a\nb\n");
    assert_eq!(value["line_count"], 2);
    assert_eq!(value["version_number"], 2);
    assert_eq!(value["content_hash"], super::super::content_hash("a\nb\n"));
}

#[test]
fn code_edit_content_refuses_a_non_object_head() {
    assert!(code_edit_content("[1,2]", "x", 2).is_err());
}
