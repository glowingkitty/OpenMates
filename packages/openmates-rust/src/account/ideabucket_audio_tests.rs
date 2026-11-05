// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::*;
use crate::client::upload::parse_upload_response;

fn file_error(raw: &str, path: &Path) -> String {
    match classify_audio_file(raw, path) {
        Err(AudioCaptureError::File(message)) => message,
        Err(other) => panic!("unexpected error {other}"),
        Ok(_) => panic!("{raw} unexpectedly classified as audio"),
    }
}

#[test]
fn local_files_are_classified_like_npm_process_files() {
    let dir = tempfile::tempdir().unwrap();
    let touch = |name: &str| {
        let path = dir.path().join(name);
        std::fs::write(&path, b"x").unwrap();
        path
    };
    assert_eq!(
        file_error("nope.m4a", &dir.path().join("nope.m4a")),
        "nope.m4a: File not found"
    );
    assert_eq!(file_error("d", dir.path()), "d: Is a directory, not a file");
    assert_eq!(
        file_error("k.pem", &touch("k.pem")),
        "k.pem: Blocked: .pem files may contain private keys. Use --allow-sensitive to override."
    );
    assert_eq!(
        file_error("id_rsa", &touch("id_rsa")),
        "id_rsa: Blocked: 'id_rsa' typically contains credentials. Use --allow-sensitive to override."
    );
    assert_eq!(
        file_error("a.docx", &touch("a.docx")),
        "a.docx: Office file .docx requires async processing; use processFilesAsync()."
    );
    assert_eq!(file_error("n.txt", &touch("n.txt")), NOT_AUDIO);
    assert_eq!(file_error(".env", &touch(".env")), NOT_AUDIO);
    assert_eq!(
        file_error("a.xyz", &touch("a.xyz")),
        "a.xyz: Unsupported file type: .xyz. Supported: code/text, images, PDFs, audio."
    );
    let audio = classify_audio_file("Memo.M4A", &touch("Memo.M4A"))
        .ok()
        .unwrap();
    assert_eq!(audio.filename, "Memo.M4A");
}

#[test]
fn embed_refs_and_markdown_match_npm_vectors() {
    assert_eq!(
        create_embed_ref("audio-recording", "Voice Memo 1.m4a"),
        "voice-memo-1-m4a-a846ba"
    );
    assert_eq!(create_embed_ref("audio-recording", "ÜÜ.mp3"), "mp3-d087f7");
    assert_eq!(
        create_embed_ref(
            "audio-recording",
            "A very long recording name that exceeds forty characters.wav"
        ),
        "a-very-long-recording-name-that-exceeds--f047b7"
    );
    assert_eq!(
        audio_idea_markdown("memo.m4a", "e1", "Buy milk"),
        "Audio: memo.m4a\n```json\n{\"type\":\"audio-recording\",\"embed_id\":\"e1\"}\n```\nTranscript: Buy milk"
    );
    assert_eq!(
        audio_idea_markdown("memo.m4a", "e1", ""),
        "Audio: memo.m4a\n```json\n{\"type\":\"audio-recording\",\"embed_id\":\"e1\"}\n```"
    );
}

fn transcription() -> AudioTranscription {
    AudioTranscription {
        transcript: json!("Buy milk"),
        transcript_original: json!("buy milk"),
        transcript_corrected: Value::Null,
        use_corrected: json!(false),
        correction_model: Value::Null,
        model: json!("whisper"),
        waveform: json!({"duration_seconds":2.5,"kind":"rms-envelope","samples":[0,0.5,1],"version":1}),
    }
}

#[test]
fn transcript_selection_prefers_corrected_then_transcript() {
    let mut t = transcription();
    assert_eq!(selected_transcript(&t), "Buy milk");
    t.transcript_corrected = json!("Buy oat milk.");
    assert_eq!(selected_transcript(&t), "Buy oat milk.");
    t.transcript_corrected = Value::Null;
    t.transcript = Value::Null;
    assert_eq!(selected_transcript(&t), "buy milk");
    t.transcript_original = Value::Null;
    assert_eq!(selected_transcript(&t), "");
}

const UPLOAD: &str = r#"{"embed_id":"e1","filename":"memo.m4a","content_type":"audio/mp4","content_hash":"h","files":{"original":{"format":"m4a","height":0,"s3_key":"u/o.m4a","size_bytes":42,"width":0}},"s3_base_url":"https://s3.example","aes_key":"QUVTS0VZ","aes_nonce":"Tk9OQ0U=","vault_wrapped_aes_key":"vault:v1:wrapped"}"#;

#[test]
fn embed_content_is_byte_identical_to_the_npm_toon() {
    let upload = parse_upload_response(UPLOAD.as_bytes()).ok().unwrap();
    let content =
        audio_embed_content("memo.m4a", "memo-m4a-abc123-e1", &upload, &transcription()).unwrap();
    let expected = "app_id: audio\nskill_id: transcribe\ntype: audio-recording\nstatus: finished\nfilename: memo.m4a\nembed_ref: memo-m4a-abc123-e1\nmime_type: audio/mp4\ntranscript: Buy milk\ntranscript_original: buy milk\ntranscript_corrected: null\nuse_corrected: false\ncorrection_model: null\nmodel: whisper\nwaveform:\n  duration_seconds: 2.5\n  kind: rms-envelope\n  samples[3]: 0,0.5,1\n  version: 1\ns3_base_url: \"https://s3.example\"\nfiles:\n  original:\n    format: m4a\n    height: 0\n    s3_key: u/o.m4a\n    size_bytes: 42\n    width: 0\naes_key: QUVTS0VZ\naes_nonce: Tk9OQ0U=\nvault_wrapped_aes_key: \"vault:v1:wrapped\"";
    assert_eq!(content.as_str(), expected);
}

#[test]
fn audio_idea_enters_the_shared_encrypted_draft_builder() {
    let t = transcription();
    let idea = PreparedIdea {
        content: audio_idea_markdown("memo.m4a", "e1", "Buy milk"),
        preview: "Buy milk".into(),
        payload: audio_idea_payload("memo.m4a", "memo-m4a-abc123-e1", "Buy milk", &t),
    };
    assert_eq!(idea.payload["type"], "audio");
    assert_eq!(idea.payload["waveform"]["version"], 1);
    let chat = "11111111-1111-4111-8111-111111111111";
    let (draft, result) = super::super::ideabucket::ideas_draft(
        chat,
        "2026-11-03",
        1_800_000_000,
        "Process these.",
        &[idea],
        7,
        &[1; 32],
        &[2; 32],
    )
    .unwrap();
    assert_eq!(result["preview"], "IdeaBucket 2026-11-03: Buy milk");
    assert_eq!(
        result["markdown"],
        "Process these.\n\n----- Idea 1 -----\nAudio: memo.m4a\n```json\n{\"type\":\"audio-recording\",\"embed_id\":\"e1\"}\n```\nTranscript: Buy milk\n-----------------"
    );
    assert_eq!(draft["ideabucket_processing_version"], 7);
    let serialized = draft.to_string();
    for secret in ["QUVTS0VZ", "Buy milk", "vault:v1"] {
        assert!(
            !serialized.contains(secret),
            "{secret} leaked into the draft envelope"
        );
    }
}
