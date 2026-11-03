use super::*;

#[test]
fn message_embed_ids_keep_order_inline_then_closed_fences() {
    let first =
        "See embed:aaaa-1 and\n```json_embed\n{\"type\":\"pdf\",\"embed_id\":\"bbbb-2\"}\n```\n";
    let second = "Again embed:aaaa-1\n```json\n{\"embed_id\":\"cccc-3\"}\n```\n```python\n{\"embed_id\":\"code\"}\n```";
    let unclosed = "```json_embed\n{\"embed_id\":\"never\"}\n";
    assert_eq!(
        message_embed_ids([first, second, unclosed]),
        vec!["aaaa-1", "bbbb-2", "cccc-3"]
    );
    // Examples nested inside another fence are never scanned as references.
    let nested = "````markdown\n```json_embed\n{\"embed_id\":\"inner\"}\n```\n````\n";
    assert!(message_embed_ids([nested]).is_empty());
}

#[test]
fn file_rows_match_the_shared_projection() {
    let pdf = json!({"type":"pdf","filename":"reports/Q3.pdf","page_count":12,"byte_length":20480,
        "app_id":"docs","skill_id":"read","url":"https://cdn.test/q3.pdf?x=1"});
    let rows = embed_file_references("embed:11111111-2222", "", &pdf);
    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row.embed_id, "11111111-2222");
    assert_eq!(row.content_ref, "embed:11111111-2222");
    assert_eq!(row.title, "reports_Q3.pdf");
    assert_eq!(row.node_type, "pdf");
    assert_eq!(row.metadata, "PDF | 12 pages | 20 KB");
    assert_eq!(row.url.as_deref(), Some("https://cdn.test/q3.pdf?x=1"));
    assert_eq!(
        row.to_json(),
        json!({"embed_id":"11111111-2222","content_ref":"embed:11111111-2222","title":"reports_Q3.pdf",
            "type":"pdf","node_type":"pdf","metadata":"PDF | 12 pages | 20 KB","app_id":"docs",
            "skill_id":"read","url":"https://cdn.test/q3.pdf?x=1","mime_type":null})
    );
    // Non-file embeds produce no rows.
    assert!(embed_file_references("x", "website", &json!({"url":"https://a.test"})).is_empty());
}

#[test]
fn titles_and_extensions_fall_back_like_the_web_resolver() {
    let code = json!({"type":"code","language":"Python","line_count":1});
    let row = &embed_file_references("abcdef0123456789", "", &code)[0];
    assert_eq!(row.title, "code-abcdef01.py");
    assert_eq!(row.metadata, "Code file | 1 line");
    let titled = json!({"title":"My Sheet/2024","mime_type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
    let row = &embed_file_references("e1", "sheet", &titled)[0];
    assert_eq!(row.title, "My Sheet_2024.xlsx");
    assert_eq!(row.node_type, "sheets-sheet");
    let audio = json!({"duration_seconds":"4.25","file_url":"/files/clip.MP3"});
    let row = &embed_file_references("e2", "generated_audio", &audio)[0];
    assert_eq!(
        (row.kind.as_str(), row.title.as_str(), row.metadata.as_str()),
        ("audio", "clip.MP3", "Audio | 4.3s")
    );
    let data_url = json!({"type":"image","src":"data:image/png;base64,AAAA","title":"\"Logo\""});
    let row = &embed_file_references("e3", "", &data_url)[0];
    assert_eq!(row.title, "Logo.png");
    assert_eq!(row.url.as_deref(), Some("data:image/png;base64,AAAA"));
    let unsafe_url = json!({"type":"video","url":"javascript:alert(1)/x.mp4"});
    assert_eq!(embed_file_references("e4", "", &unsafe_url)[0].url, None);
}

#[test]
fn string_contents_and_child_ids_decode_json_and_flat_toon() {
    let toon = Value::String(
        "type: pdf\nfilename: \"a b.pdf\"\nembed_ids: x|embed:y,\n  nested: ignored".into(),
    );
    assert_eq!(embed_file_references("e", "", &toon)[0].title, "a b.pdf");
    assert_eq!(child_embed_ids(&toon), vec!["x", "y"]);
    assert_eq!(
        child_embed_ids(&json!({"embed_ids":["a", "null", " embed:b "]})),
        vec!["a", "b"]
    );
    assert!(child_embed_ids(&json!({"embed_ids": 3})).is_empty());
}
