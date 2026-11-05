//! Shared codec/lifetime vectors using an explicit synthetic primitive port.
//! This native port is not real CryptoKey proof; DedicatedWorker tests own that.
// contract-test-file: tooling
use super::*;
use serde_json::Value;
struct AesPort {
    key: Key,
}
impl MasterCrypto for AesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], data: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(
            async move { super::super::encrypt_aead(data, &self.key, iv, &[]).map(Zeroizing::new) },
        )
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], data: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { super::super::decrypt_aead(data, &self.key, iv, &[]) })
    }
}
fn vectors() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/master-capability-codecs.json"
    ))
    .unwrap()
}
fn plain(v: &Value) -> Vec<u8> {
    match v.get("plaintext") {
        Some(text) => text.as_str().unwrap().as_bytes().to_vec(),
        None => vec![b'X'; v["plaintext_repeat"]["count"].as_u64().unwrap() as usize],
    }
}
fn envelope(v: &Value, key: &[u8; 32], data: &[u8]) -> String {
    let iv = STANDARD.decode(v["iv_b64"].as_str().unwrap()).unwrap();
    let mut encoded = vec![];
    match v["wire"].as_str().unwrap() {
        "om-fnv" => {
            encoded.extend_from_slice(b"OM");
            encoded.extend_from_slice(&super::super::key_fingerprint(key));
        }
        "om-python" => {
            encoded.extend_from_slice(b"OM");
            encoded.extend_from_slice(&[1, 0, 0, 0]);
        }
        "legacy" => {}
        _ => panic!("codec fixture"),
    }
    encoded.extend_from_slice(&iv);
    encoded.extend(super::super::encrypt_aead(data, key, &iv, &[]).unwrap());
    assert_eq!(
        super::super::hex(&Sha256::digest(&encoded)),
        v["ciphertext_sha256"].as_str().unwrap()
    );
    STANDARD.encode(encoded)
}
#[tokio::test]
async fn exact_eleven_shared_native_and_existing_browser_codec_outcomes() {
    let fixtures = vectors();
    let vectors = fixtures["vectors"].as_array().unwrap();
    assert_eq!(vectors.len(), 11);
    for vector in vectors {
        let key = decode_key(vector["key_b64"].as_str().unwrap()).unwrap();
        let data = plain(vector);
        let wire = envelope(vector, &key, &data);
        let native = MasterCapability::from_native(key.clone());
        assert_eq!(&*native.decrypt_bytes(&wire).await.unwrap(), &data);
        let browser_raw=MasterCapability::from_browser_raw(key.clone());
        assert_eq!(&*browser_raw.decrypt_bytes(&wire).await.unwrap(),&data);
        let opaque = MasterCapability::opaque_for_test(Shared::new(AesPort { key }));
        let decoded = opaque.decrypt_bytes(&wire).await;
        if vector["opaque_browser"] == "plaintext" {
            assert_eq!(&*decoded.unwrap(), &data);
        } else {
            assert!(matches!(decoded, Err(Error::Crypto)));
        }
    }
}
#[tokio::test]
async fn malformed_wrong_key_tamper_and_forged_headers_fail_closed_without_fallback() {
    let fixtures = vectors();
    let vector = &fixtures["vectors"][0];
    let key = decode_key(vector["key_b64"].as_str().unwrap()).unwrap();
    let data = plain(vector);
    let wire = envelope(vector, &key, &data);
    let opaque = MasterCapability::opaque_for_test(Shared::new(AesPort { key }));
    for malformed in ["", "!notbase64!", "AA==", "AA=A", "===="] {
        assert!(matches!(
            opaque.decrypt_bytes(malformed).await,
            Err(Error::Crypto)
        ));
    }
    for length in 0..28 {
        assert!(matches!(
            opaque
                .decrypt_bytes(&STANDARD.encode(vec![0; length]))
                .await,
            Err(Error::Crypto)
        ));
    }
    let wrong = MasterCapability::opaque_for_test(Shared::new(AesPort {
        key: Zeroizing::new([99; 32]),
    }));
    assert!(matches!(
        wrong.decrypt_bytes(&wire).await,
        Err(Error::Crypto)
    ));
    let mut raw = STANDARD.decode(&wire).unwrap();
    *raw.last_mut().unwrap() ^= 1;
    assert!(matches!(
        opaque.decrypt_bytes(&STANDARD.encode(raw)).await,
        Err(Error::Crypto)
    ));
    let mut forged = b"OM".to_vec();
    forged.extend_from_slice(&[1, 0, 0, 0]);
    forged.extend_from_slice(&[0; 28]);
    assert!(matches!(
        opaque.decrypt_bytes(&STANDARD.encode(forged)).await,
        Err(Error::Crypto)
    ));
}
#[tokio::test]
async fn native_write_fingerprint_and_opaque_browser_legacy_write_remain_distinct() {
    let key = Zeroizing::new([7; 32]);
    let native = MasterCapability::from_native(key.clone());
    let opaque = MasterCapability::opaque_for_test(Shared::new(AesPort { key: key.clone() }));
    for data in [
        vec![],
        b"Synthetic Unicode \xe2\x9c\x93".to_vec(),
        (0..=255).collect::<Vec<u8>>(),
    ] {
        let n = STANDARD
            .decode(native.encrypt_bytes(&data).await.unwrap())
            .unwrap();
        assert_eq!(&n[..2], b"OM");
        assert_eq!(&n[2..6], &key_fingerprint(&key));
        assert_eq!(n.len(), data.len() + 34);
        let b = opaque.encrypt_bytes(&data).await.unwrap();
        assert_eq!(STANDARD.decode(&b).unwrap().len(), data.len() + 28);
        assert_eq!(&*opaque.decrypt_bytes(&b).await.unwrap(), &data);
        assert_eq!(&*native.decrypt_bytes(&b).await.unwrap(), &data);
    }
    assert!(!native.same_instance(&MasterCapability::from_native(key)));
    assert!(opaque.same_instance(&opaque.clone()));
    assert!(matches!(
        opaque.native_key(),
        Err(Error::Unavailable {
            code: "master_key_extraction_unavailable",
            ..
        })
    ));
}
struct GatePort {
    entered: tokio::sync::Notify,
    resume: tokio::sync::Notify,
}
impl MasterCrypto for GatePort {
    fn encrypt<'a>(&'a self, _: &'a [u8; 12], data: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            self.entered.notify_one();
            self.resume.notified().await;
            Ok(Zeroizing::new(vec![0; data.len() + 16]))
        })
    }
    fn decrypt<'a>(&'a self, _: &'a [u8; 12], _: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            self.entered.notify_one();
            self.resume.notified().await;
            Ok(Zeroizing::new(b"synthetic private pending result".to_vec()))
        })
    }
}
#[tokio::test]
async fn invalidation_during_unabortable_encrypt_or_decrypt_never_publishes_results() {
    for operation in [0,1,2] {
        let port = Shared::new(GatePort {
            entered: Default::default(),
            resume: Default::default(),
        });
        let capability = MasterCapability::opaque_for_test(port.clone());
        let old = capability.clone();
        let call = tokio::spawn(async move {
            if operation==0 {
                old.decrypt_bytes(&STANDARD.encode([0; 28]))
                    .await
                    .map(|_| ())
            } else if operation==1 {
                old.encrypt_bytes(b"private synthetic").await.map(|_| ())
            } else {
                old.encrypt_server_bytes(b"private synthetic").await.map(|_| ())
            }
        });
        port.entered.notified().await;
        capability.invalidate();
        port.resume.notify_one();
        assert!(matches!(call.await.unwrap(), Err(Error::Cancelled)));
        assert!(matches!(
            capability.encrypt_bytes(b"private").await,
            Err(Error::Cancelled)
        ));
    }
}
#[test]
fn browser_base64_preprocessing_matches_existing_helper_and_atob_boundaries() {
    for value in ["Zg==", "Zg", "Zh==", "_w=="] {
        assert_eq!(decode_browser_base64(value).unwrap().len(), 1);
    }
    assert_eq!(decode_browser_base64(" Zg==   ").unwrap(), vec![b'f']);
    for value in ["Zg===", "Z===", "Zg= ", "Zg\u{000b}="] {
        assert!(decode_browser_base64(value).is_err());
    }
}

#[tokio::test]
async fn real_raw_browser_and_typed_server_writes_match_legacy_browser_decryptor() {
    let key=Zeroizing::new([7u8;32]);
    let native=MasterCapability::from_native(key.clone());
    let browser=MasterCapability::from_browser_raw(key.clone());
    let opaque=MasterCapability::opaque_for_test(Shared::new(AesPort{key:key.clone()}));
    for plain in [b"".as_slice(),b"master-wrapped child key".as_slice(),"real browser settings Δ".as_bytes()] {
        let generic=native.encrypt_bytes(plain).await.unwrap();
        assert!(STANDARD.decode(&generic).unwrap().starts_with(b"OM"));
        for wire in [browser.encrypt_bytes(plain).await.unwrap(),native.encrypt_server_bytes(plain).await.unwrap(),browser.encrypt_server_bytes(plain).await.unwrap(),opaque.encrypt_server_bytes(plain).await.unwrap()] {
            // Length proves no hidden native header; authentication below proves
            // actual deployed FormatC/D layout, not an unauthenticated prefix.
            assert_eq!(STANDARD.decode(&wire).unwrap().len(),12+plain.len()+16);
            assert_eq!(&*opaque.decrypt_bytes(&wire).await.unwrap(),plain);
            assert_eq!(&*native.decrypt_bytes(&wire).await.unwrap(),plain);
            let mut tampered=STANDARD.decode(&wire).unwrap();*tampered.last_mut().unwrap()^=1;
            assert!(matches!(opaque.decrypt_bytes(&STANDARD.encode(tampered)).await,Err(Error::Crypto)));
        }
    }
    assert_eq!(&**browser.native_key().unwrap(),&[7u8;32]);
    browser.invalidate();assert!(matches!(browser.encrypt_server_bytes(b"private").await,Err(Error::Cancelled)));
    native.invalidate();assert!(matches!(native.encrypt_server_bytes(b"private").await,Err(Error::Cancelled)));
}
