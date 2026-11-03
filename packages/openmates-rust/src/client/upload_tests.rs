// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::*;

const UPLOAD: &str = r#"{"embed_id":"e1","filename":"memo.m4a","content_type":"audio/mp4","content_hash":"h","files":{"original":{"s3_key":"u/o.m4a","width":0,"height":0,"size_bytes":42,"format":"m4a"}},"s3_base_url":"https://s3.example","aes_key":"QUVTS0VZ","aes_nonce":"Tk9OQ0U=","vault_wrapped_aes_key":"vault:v1:wrapped","malware_scan":"clean","ai_detection":null,"deduplicated":false}"#;

#[test]
fn upload_response_parsing_requires_the_key_material() {
    let parsed = parse_upload_response(UPLOAD.as_bytes()).ok().unwrap();
    assert_eq!(
        (
            parsed.embed_id.as_str(),
            parsed.content_type.as_str(),
            parsed.aes_key.as_str()
        ),
        ("e1", "audio/mp4", "QUVTS0VZ")
    );
    assert_eq!(audio_s3_key(&parsed.files), Some("u/o.m4a"));
    let missing = UPLOAD.replace(r#""aes_key":"QUVTS0VZ","#, "");
    assert_eq!(
        parse_upload_response(missing.as_bytes()).err(),
        Some(Error::Protocol)
    );
    let other: serde_json::Map<String, Value> =
        serde_json::from_str(r#"{"preview":{"s3_key":"p"}}"#).unwrap();
    assert_eq!(audio_s3_key(&other), Some("p"));
}

#[test]
fn upload_failures_use_the_npm_messages_and_endpoints() {
    assert_eq!(
        upload_status_message(401, ""),
        "Authentication failed. Run `openmates login` to re-authenticate."
    );
    assert_eq!(
        upload_status_message(413, ""),
        "File too large (maximum 100 MB)."
    );
    assert_eq!(upload_status_message(415, ""), "Unsupported file type.");
    assert_eq!(
        upload_status_message(422, "malware found"),
        "File rejected: malware detected."
    );
    assert_eq!(
        upload_status_message(422, "content_safety"),
        "File rejected: content safety violation."
    );
    assert_eq!(
        upload_status_message(422, "bad"),
        "Upload validation failed: bad"
    );
    assert_eq!(
        upload_status_message(429, ""),
        "Upload rate limit exceeded. Try again in a minute."
    );
    assert_eq!(upload_status_message(500, ""), "Upload failed (HTTP 500).");
    let url = |s: &str| url::Url::parse(s).unwrap();
    assert_eq!(
        upload_base_url(&url("http://localhost:8000")),
        "http://localhost:8001"
    );
    assert_eq!(
        upload_base_url(&url("https://api.dev.openmates.org")),
        "https://upload.openmates.org"
    );
    assert_eq!(
        upload_origin(&url("https://api.dev.openmates.org")),
        "https://app.dev.openmates.org"
    );
    assert_eq!(
        upload_origin(&url("http://localhost:8000")),
        "http://localhost:5173"
    );
    assert_eq!(
        upload_origin(&url("https://self.example")),
        "https://app.openmates.org"
    );
    let body = multipart_body("B", "a\"b.m4a", "audio/mp4", b"xy");
    assert_eq!(
        String::from_utf8(body).unwrap(),
        "--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a%22b.m4a\"\r\nContent-Type: audio/mp4\r\n\r\nxy\r\n--B--\r\n"
    );
}

#[test]
fn transcription_results_and_errors_follow_npm_selection() {
    let data = json!({"success":true,"data":{"results":[
        {"id":"other","results":[{"transcript":"wrong"}]},
        {"id":"e1","results":[{"transcript":"hi","transcript_corrected":"Hi.","use_corrected":true,"model":"m","waveform":{"version":1,"kind":"rms-envelope","samples":[0.5]}}]}
    ]}});
    let parsed = parse_transcription(&data, "e1").unwrap();
    assert_eq!(parsed.transcript_corrected, json!("Hi."));
    assert_eq!(parsed.transcript_original, Value::Null);
    assert_eq!(parsed.waveform["samples"], json!([0.5]));
    assert_eq!(
        parse_transcription(&data, "missing").unwrap().transcript,
        json!("wrong")
    );
    for (value, message) in [
        (json!({"success":false}), "Transcription failed."),
        (json!({"success":false,"error":"quota"}), "quota"),
        (
            json!({"data":{"results":[]}}),
            "Transcription response did not include a result.",
        ),
        (
            json!({"data":{"results":[{"id":"e1","error":"too long","results":[]}]}}),
            "too long",
        ),
        (
            json!({"data":{"results":[{"id":"e1","results":[{"error":"decode"}]}]}}),
            "decode",
        ),
    ] {
        assert_eq!(parse_transcription(&value, "e1").unwrap_err(), message);
    }
    assert_eq!(
        transcription_error(402, br#"{"detail":"Insufficient credits"}"#),
        "Insufficient credits"
    );
    assert_eq!(transcription_error(500, br#"{"error":"boom"}"#), "boom");
    assert_eq!(
        transcription_error(502, b"<html>"),
        "Transcription failed (HTTP 502)."
    );
}

#[test]
fn toon_encoding_matches_the_npm_library_and_native_decoder() {
    let fields = [
        ("app_id", json!("audio")),
        ("filename", json!("voice memo, 1.m4a")),
        ("transcript", json!("Hello: \"world\"\nnext")),
        ("original", Value::Null),
        ("empty", json!("")),
        ("flag", json!(false)),
        ("dash", json!("-x")),
        ("numeric", json!("123")),
        (
            "waveform",
            json!({"kind":"rms-envelope","samples":[0.1,0.25,1,0,-0.5,1e-7,1e21],"version":1}),
        ),
        (
            "files",
            json!({"original":{"s3_key":"a/b.m4a","size_bytes":1234}}),
        ),
        ("url", json!("https://s3.example/x")),
        ("aes_key", json!("k+/=")),
        ("arr", json!([])),
        ("strs", json!(["a", "b c", "d,e"])),
        ("bad key", json!(1)),
    ];
    let encoded = toon_encode::encode_fields(&fields).unwrap();
    assert_eq!(
        encoded,
        "app_id: audio\nfilename: \"voice memo, 1.m4a\"\ntranscript: \"Hello: \\\"world\\\"\\nnext\"\noriginal: null\nempty: \"\"\nflag: false\ndash: \"-x\"\nnumeric: \"123\"\nwaveform:\n  kind: rms-envelope\n  samples[7]: 0.1,0.25,1,0,-0.5,1e-7,1e+21\n  version: 1\nfiles:\n  original:\n    s3_key: a/b.m4a\n    size_bytes: 1234\nurl: \"https://s3.example/x\"\naes_key: k+/=\narr: []\nstrs[3]: a,b c,\"d,e\"\n\"bad key\": 1"
    );
    for (value, text) in [
        (1e20, "100000000000000000000"),
        (0.000001, "0.000001"),
        (-1.5e-10, "-1.5e-10"),
        (2.5, "2.5"),
    ] {
        assert_eq!(toon_encode::js_float(value), text);
    }
    assert!(toon_encode::encode_fields(&[("nested", json!([[1]]))]).is_err());
    let audio = toon_encode::encode_fields(&[
        ("transcript", json!("Buy milk")),
        (
            "waveform",
            json!({"kind":"rms-envelope","samples":[0,0.5,1],"version":1}),
        ),
        (
            "files",
            json!({"original":{"s3_key":"u/o.m4a","size_bytes":42}}),
        ),
        ("vault_wrapped_aes_key", json!("vault:v1:wrapped")),
    ])
    .unwrap();
    let decoded = crate::client::toon::decode(&audio).unwrap();
    assert_eq!(decoded["transcript"], "Buy milk");
    assert_eq!(decoded["waveform"]["samples"], json!([0, 0.5, 1]));
    assert_eq!(decoded["files"]["original"]["s3_key"], "u/o.m4a");
    assert_eq!(decoded["vault_wrapped_aes_key"], "vault:v1:wrapped");
}
