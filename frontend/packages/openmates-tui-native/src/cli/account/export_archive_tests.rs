// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;

fn bundle() -> Value {
    json!({
        "export":{"export_id":"exp/1","status":"completed"},
        "manifest":{"schema_version":"account-export-v1","selected_domains":["chats","settings"],"report":{"failures":[]}},
        "chunks":[
            {"chunk_id":"c1","sequence":1,"status":"done","domain":"chats","payload":{"items":[{"id":"chat-1","title":"Trip: Rome","messages":[{"role":"user","content":"Hello"}]}]}},
            {"chunk_id":"c2","sequence":2,"status":"done","domain":"settings","payload":{"language":"en"}},
        ],
    })
}

#[test]
fn archive_layout_matches_the_npm_writer() {
    let files = entries(&bundle()).unwrap();
    let names = files.iter().map(|(n, _)| n.as_str()).collect::<Vec<_>>();
    assert_eq!(
        names,
        [
            "README.md",
            "manifest.yml",
            "manifest.json",
            "export-report.yml",
            "domains/chats.json",
            "domains/settings.json",
            "chats/chat-1.yml",
            "chats/chat-1.md"
        ]
    );
    let file = |name: &str| files.iter().find(|(n, _)| n == name).unwrap().1.clone();
    assert!(
        file("README.md")
            .contains("Export ID: exp/1\nStatus: completed\nSchema: account-export-v1\n")
    );
    assert!(file("README.md").contains("## Selected Domains\n\n- chats\n- settings\n"));
    assert_eq!(
        file("chats/chat-1.md"),
        "# Trip: Rome\n\n## Messages\n\n### user\n\nHello\n\n"
    );
    assert!(file("chats/chat-1.yml").contains("chat:\n  id: chat-1\n"));
    assert!(file("chats/chat-1.yml").contains("  title: \"Trip: Rome\"\n"));
    assert!(file("export-report.yml").contains("redacted_secret_categories:\n- api_credentials\n"));
}

#[test]
fn secrets_are_refused_before_anything_is_written() {
    assert!(
        assert_payload_safe(&json!({"nested":{"encrypted_title":"x"}}), "$export")
            .unwrap_err()
            .contains("'encrypted_title' at $export.nested")
    );
    assert!(
        assert_payload_safe(
            &json!({"items":[{"note":"key sk-api-abcdef123"}]}),
            "$export"
        )
        .is_err()
    );
    assert!(assert_payload_safe(&json!({"share":"https://x/#key=abcdefghij"}), "$export").is_err());
    let mut leaked = bundle();
    leaked["chunks"][1]["payload"]["master_key"] = json!("x");
    assert!(
        entries(&leaked)
            .unwrap_err()
            .contains("forbidden secret field 'master_key'")
    );
    let sanitized = sanitize_manifest(&json!({"report":{"redactions":["anything"]}})).unwrap();
    assert_eq!(
        sanitized["report"]["redactions"],
        json!(REDACTION_CATEGORIES)
    );
}

#[test]
fn zip_and_encrypted_zip_are_readable() {
    use std::io::Read;
    let files = vec![("a.txt".to_owned(), "hello hello hello".to_owned())];
    let archive = zip(&files).unwrap();
    assert_eq!(&archive[..4], &0x0403_4b50u32.to_le_bytes());
    let name_len = u16::from_le_bytes([archive[26], archive[27]]) as usize;
    let size = u32::from_le_bytes(archive[18..22].try_into().unwrap()) as usize;
    let data = &archive[30 + name_len..30 + name_len + size];
    let mut text = String::new();
    flate2::read::DeflateDecoder::new(data)
        .read_to_string(&mut text)
        .unwrap();
    assert_eq!(text, "hello hello hello");
    assert_eq!(
        &archive[archive.len() - 22..archive.len() - 18],
        &0x0605_4b50u32.to_le_bytes()
    );

    let sealed = encrypt_zip(&archive, "pw").unwrap();
    let text = String::from_utf8_lossy(&sealed[..64]).into_owned();
    let mut lines = text.splitn(3, '\n');
    assert_eq!(lines.next(), Some("OMZIP1"));
    let header_len: usize = lines.next().unwrap().parse().unwrap();
    let prefix = 7 + header_len.to_string().len() + 1;
    let header: Value = serde_json::from_slice(&sealed[prefix..prefix + header_len]).unwrap();
    use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
    use base64::{Engine, engine::general_purpose::STANDARD};
    let salt = STANDARD.decode(header["salt"].as_str().unwrap()).unwrap();
    let mut key = [0u8; 32];
    scrypt::scrypt(
        b"pw",
        &salt,
        &scrypt::Params::new(14, 8, 1, 32).unwrap(),
        &mut key,
    )
    .unwrap();
    let mut ciphertext = sealed[prefix + header_len..].to_vec();
    ciphertext.extend(STANDARD.decode(header["tag"].as_str().unwrap()).unwrap());
    let iv = STANDARD.decode(header["iv"].as_str().unwrap()).unwrap();
    let opened = Aes256Gcm::new_from_slice(&key)
        .unwrap()
        .decrypt(Nonce::from_slice(&iv), ciphertext.as_slice())
        .unwrap();
    assert_eq!(opened, archive);
}

#[test]
fn directory_output_writes_every_file() {
    let directory = tempfile::tempdir().unwrap();
    let target = directory.path().join("export");
    let result = write(&bundle(), true, None, Some(target.to_str().unwrap())).unwrap();
    assert_eq!(result["format"], "directory");
    assert_eq!(result["files"], 8);
    assert!(target.join("domains/settings.json").is_file());
    assert!(
        write(&bundle(), true, Some("pw"), None)
            .unwrap_err()
            .contains("only supported for zip format")
    );
}
