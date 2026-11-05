//! Authored real DedicatedWorker tests. Execute through isolated WASM CI only.
use super::*;
use openmates_sdk::crypto::master::MasterCapability;
use std::{
    future::Future,
    rc::Rc,
    task::{Context, Poll, Waker},
};
use wasm_bindgen_test::*;
wasm_bindgen_test_configure!(run_in_dedicated_worker);

#[wasm_bindgen::prelude::wasm_bindgen(inline_js = "
export async function codecFixtureKey(raw, extractable) {
  return crypto.subtle.importKey('raw', raw, 'AES-GCM', extractable, ['encrypt','decrypt']);
}
export async function fixtureKey(algorithm, bits, extractable, usages, byte) {
  return crypto.subtle.importKey('raw', new Uint8Array(bits / 8).fill(byte), algorithm, extractable, usages);
}
export function cloneFixtureKey(key) { return structuredClone(key); }
export async function publicFixtureKey() {
  return (await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt'])).publicKey;
}
export function observeDecryptOutput() {
  const target=crypto.subtle, descriptor=Object.getOwnPropertyDescriptor(target,'decrypt'), original=target.decrypt;
  let observed, view, sawPlaintext=false;
  Object.defineProperty(target,'decrypt',{configurable:true,value:function(...args){
    observed=Reflect.apply(original,this,args).then(buffer=>{view=new Uint8Array(buffer);sawPlaintext=view.some(byte=>byte!==0);return buffer;});
    return observed;
  }});
  return async action=>{
    if(action==='wait'){await observed;await new Promise(resolve=>setTimeout(resolve,0));return {sawPlaintext,wiped:view.every(byte=>byte===0)};}
    if(descriptor)Object.defineProperty(target,'decrypt',descriptor);else delete target.decrypt;
    view=undefined;observed=undefined;
  };
}
export function forbidKeyExport() {
  const target=crypto.subtle, prior=Object.getOwnPropertyDescriptor(target,'exportKey');
  Object.defineProperty(target,'exportKey',{configurable:true,value:()=>{throw Error('forbidden');}});
  return ()=>{if(prior)Object.defineProperty(target,'exportKey',prior);else delete target.exportKey;};
}
")]
extern "C" {
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = codecFixtureKey)]
    fn codec_fixture_key(raw: &Uint8Array, extractable: bool) -> js_sys::Promise;
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = fixtureKey)]
    fn fixture_key(
        algorithm: &str,
        bits: u32,
        extractable: bool,
        usages: &js_sys::Array,
        byte: u8,
    ) -> js_sys::Promise;
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = cloneFixtureKey)]
    fn clone_key(key: &CryptoKey) -> CryptoKey;
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = publicFixtureKey)]
    fn public_key() -> js_sys::Promise;
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = forbidKeyExport)]
    fn forbid_export() -> js_sys::Function;
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = observeDecryptOutput)]
    fn observe_decrypt_output() -> js_sys::Function;
}
struct ExportGuard(js_sys::Function);
impl Drop for ExportGuard {
    fn drop(&mut self) {
        self.0
            .call0(&JsValue::UNDEFINED)
            .expect("restore fixture guard");
    }
}
async fn key(
    algorithm: &str,
    bits: u32,
    extractable: bool,
    usages: &[&str],
    byte: u8,
) -> CryptoKey {
    let values = usages
        .iter()
        .map(|value| JsValue::from_str(value))
        .collect::<js_sys::Array>();
    JsFuture::from(fixture_key(algorithm, bits, extractable, &values, byte))
        .await
        .unwrap()
        .dyn_into()
        .unwrap()
}
async fn port(byte: u8) -> BrowserMasterCrypto {
    BrowserMasterCrypto::new(key("AES-GCM", 256, false, &["encrypt", "decrypt"], byte).await)
        .unwrap()
}
fn cap(port: BrowserMasterCrypto) -> MasterCapability {
    MasterCapability::from_browser_port(Rc::new(port))
}
fn require_pending<T>(future: std::pin::Pin<&mut impl Future<Output = T>>) {
    assert!(matches!(
        future.poll(&mut Context::from_waker(Waker::noop())),
        Poll::Pending
    ));
}

#[wasm_bindgen_test(async)]
async fn cloned_nonextractable_key_preserves_nist_aes256_vector_and_never_exports() {
    let original = key("AES-GCM", 256, false, &["encrypt", "decrypt"], 0).await;
    let cloned = clone_key(&original);
    assert!(!original.extractable());
    assert!(!cloned.extractable());
    assert_eq!(
        cloned
            .usages()
            .iter()
            .map(|value| value.as_string())
            .collect::<Vec<_>>(),
        original
            .usages()
            .iter()
            .map(|value| value.as_string())
            .collect::<Vec<_>>()
    );
    let _guard = ExportGuard(forbid_export());
    let port = BrowserMasterCrypto::new(cloned).unwrap();
    let actual = port.encrypt(&[0; 12], &[0; 16]).await.unwrap();
    let expected = [
        0xce, 0xa7, 0x40, 0x3d, 0x4d, 0x60, 0x6b, 0x6e, 0x07, 0x4e, 0xc5, 0xd3, 0xba, 0xf3, 0x9d,
        0x18, 0xd0, 0xd1, 0xc8, 0xa7, 0x99, 0x99, 0x6b, 0xf0, 0x26, 0x5b, 0x98, 0xb5, 0xd4, 0x8a,
        0xb9, 0x19,
    ];
    assert_eq!(actual.as_slice(), expected);
    assert_eq!(
        port.decrypt(&[0; 12], &actual).await.unwrap().as_slice(),
        &[0; 16]
    );
}

#[wasm_bindgen_test(async)]
async fn extractable_key_uses_same_primitive_without_export_or_attribute_change() {
    let key = key("AES-GCM", 256, true, &["encrypt", "decrypt"], 7).await;
    let held = key.clone();
    let _guard = ExportGuard(forbid_export());
    let master = cap(BrowserMasterCrypto::new(key).unwrap());
    for bytes in [
        b"".as_slice(),
        "Unicode 日本語 🦀".as_bytes(),
        &[0, 255, 128, 1],
    ] {
        let encrypted = master.encrypt_bytes(bytes).await.unwrap();
        assert_eq!(
            master.decrypt_bytes(&encrypted).await.unwrap().as_slice(),
            bytes
        );
    }
    assert!(held.extractable());
}

#[wasm_bindgen_test(async)]
async fn wrong_key_tag_nonce_and_short_tag_fail_closed() {
    let first = port(0).await;
    let wrong = port(1).await;
    let ciphertext = first.encrypt(&[2; 12], b"synthetic fixture").await.unwrap();
    assert!(wrong.decrypt(&[2; 12], &ciphertext).await.is_err());
    assert!(first.decrypt(&[3; 12], &ciphertext).await.is_err());
    let mut tampered = ciphertext.to_vec();
    *tampered.last_mut().unwrap() ^= 1;
    assert!(first.decrypt(&[2; 12], &tampered).await.is_err());
    assert!(first.decrypt(&[2; 12], &[0; 15]).await.is_err());
}

#[wasm_bindgen_test(async)]
async fn wrong_algorithm_length_usage_and_key_type_are_rejected() {
    // A wasm-bindgen JS handle type alone does not authenticate a JS resource.
    assert!(BrowserMasterCrypto::new(Object::new().unchecked_into()).is_err());
    for candidate in [
        key("AES-CBC", 256, false, &["encrypt", "decrypt"], 0).await,
        key("AES-GCM", 128, false, &["encrypt", "decrypt"], 0).await,
        key("AES-GCM", 256, false, &["decrypt"], 0).await,
        key("AES-GCM", 256, false, &["encrypt"], 0).await,
        JsFuture::from(public_key())
            .await
            .unwrap()
            .dyn_into::<CryptoKey>()
            .unwrap(),
    ] {
        assert!(BrowserMasterCrypto::new(candidate).is_err());
    }
}

#[wasm_bindgen_test(async)]
async fn capability_cancellation_denies_late_encrypt_and_decrypt_results() {
    let source = cap(port(0).await);
    let encrypted = source
        .encrypt_bytes(b"synthetic private result")
        .await
        .unwrap();
    let encrypting = source.encrypt_bytes(b"cancelled write");
    let mut encrypting = std::pin::pin!(encrypting);
    require_pending(encrypting.as_mut());
    source.invalidate();
    assert!(encrypting.await.is_err());
    let source = cap(port(0).await);
    let decrypting = source.decrypt_bytes(&encrypted);
    let mut decrypting = std::pin::pin!(decrypting);
    require_pending(decrypting.as_mut());
    source.invalidate();
    assert!(decrypting.await.is_err());
    assert!(source.decrypt_bytes(&encrypted).await.is_err());
}

#[wasm_bindgen_test(async)]
async fn same_material_new_capability_is_distinct_and_invalidated_old_result_cannot_publish() {
    let key = key("AES-GCM", 256, false, &["encrypt", "decrypt"], 9).await;
    let old = cap(BrowserMasterCrypto::new(key.clone()).unwrap());
    let next = cap(BrowserMasterCrypto::new(clone_key(&key)).unwrap());
    assert!(!old.same_instance(&next));
    assert!(old.same_instance(&old));
    let encrypted = old
        .encrypt_bytes(b"same material is not owner proof")
        .await
        .unwrap();
    let pending = old.decrypt_bytes(&encrypted);
    let mut pending = std::pin::pin!(pending);
    require_pending(pending.as_mut());
    old.invalidate();
    assert!(pending.await.is_err());
    assert_eq!(
        next.decrypt_bytes(&encrypted).await.unwrap().as_slice(),
        b"same material is not owner proof"
    );
}

#[wasm_bindgen_test(async)]
async fn dropped_consumer_still_wipes_real_webcrypto_plaintext_at_settlement() {
    let source = cap(port(4).await);
    let encrypted = source
        .encrypt_bytes(b"synthetic nonzero private result")
        .await
        .unwrap();
    let observer = observe_decrypt_output();
    {
        let pending = source.decrypt_bytes(&encrypted);
        let mut pending = std::pin::pin!(pending);
        require_pending(pending.as_mut());
        // Drop the consumer entirely instead of continuing to await an error.
    }
    let observed = observer
        .call1(&JsValue::UNDEFINED, &JsValue::from_str("wait"))
        .unwrap();
    let observed = JsFuture::from(js_sys::Promise::resolve(&observed))
        .await
        .unwrap();
    observer
        .call1(&JsValue::UNDEFINED, &JsValue::from_str("restore"))
        .unwrap();
    assert_eq!(
        Reflect::get(&observed, &JsValue::from_str("sawPlaintext"))
            .unwrap()
            .as_bool(),
        Some(true)
    );
    assert_eq!(
        Reflect::get(&observed, &JsValue::from_str("wiped"))
            .unwrap()
            .as_bool(),
        Some(true)
    );
}

#[wasm_bindgen_test(async)]
async fn shared_eleven_codec_cases_match_actual_webcrypto_for_both_extractability_values() {
    use base64::{Engine, engine::general_purpose::STANDARD};
    use sha2::{Digest, Sha256};
    let specification: serde_json::Value = serde_json::from_str(include_str!(
        "../../openmates-rust/tests/fixtures/master-capability-codecs.json"
    ))
    .unwrap();
    let cases = specification["vectors"].as_array().unwrap();
    assert_eq!(cases.len(), 11);
    for extractable in [false, true] {
        for case in cases {
            let raw = STANDARD.decode(case["key_b64"].as_str().unwrap()).unwrap();
            let fixed: [u8; 32] = raw.as_slice().try_into().unwrap();
            let imported = JsFuture::from(codec_fixture_key(
                &Uint8Array::from(raw.as_slice()),
                extractable,
            ))
            .await
            .unwrap()
            .dyn_into::<CryptoKey>()
            .unwrap();
            let cloned = clone_key(&imported);
            assert_eq!(cloned.extractable(), extractable);
            let _guard = ExportGuard(forbid_export());
            let primitive = Rc::new(BrowserMasterCrypto::new(cloned).unwrap());
            let master = MasterCapability::from_browser_port(primitive.clone());
            let iv: [u8; 12] = STANDARD
                .decode(case["iv_b64"].as_str().unwrap())
                .unwrap()
                .try_into()
                .unwrap();
            let plaintext = match case.get("plaintext_repeat") {
                Some(repeat) => repeat["character"]
                    .as_str()
                    .unwrap()
                    .repeat(repeat["count"].as_u64().unwrap() as usize),
                None => case["plaintext"].as_str().unwrap().to_owned(),
            };
            let ciphertext = primitive.encrypt(&iv, plaintext.as_bytes()).await.unwrap();
            let mut wire = Vec::new();
            match case["wire"].as_str().unwrap() {
                "legacy" => {}
                "om-fnv" => {
                    wire.extend_from_slice(b"OM");
                    wire.extend_from_slice(&openmates_sdk::crypto::key_fingerprint(&fixed));
                }
                "om-python" => wire.extend_from_slice(&[b'O', b'M', 1, 0, 0, 0]),
                _ => panic!("closed shared fixture wire vocabulary"),
            }
            wire.extend_from_slice(&iv);
            wire.extend_from_slice(&ciphertext);
            assert_eq!(
                format!("{:x}", Sha256::digest(&wire)),
                case["ciphertext_sha256"].as_str().unwrap(),
                "{}",
                case["id"]
            );
            let decoded = master.decrypt_bytes(&STANDARD.encode(&wire)).await;
            if case["opaque_browser"] == "plaintext" {
                assert_eq!(
                    decoded.unwrap().as_slice(),
                    plaintext.as_bytes(),
                    "{}",
                    case["id"]
                );
            } else {
                assert!(decoded.is_err(), "{}", case["id"]);
            }
        }
    }
}

#[wasm_bindgen_test(async)]
async fn existing_profile_constructor_accepts_cloned_false_key_without_email_or_salt() {
    let key = key("AES-GCM", 256, false, &["encrypt", "decrypt"], 12).await;
    let _guard = ExportGuard(forbid_export());
    let profile = crate::browser::PreparedBrowserProfile::from_existing_key(
        "22222222-2222-4222-8222-222222222222",
        clone_key(&key),
        None,
        None,
        false,
    )
    .unwrap();
    assert!(!key.extractable());
    drop(profile); // Shape/resource preparation is not server/key-owner admission.
    assert!(
        crate::browser::PreparedBrowserProfile::from_existing_key(
            "invalid",
            clone_key(&key),
            None,
            None,
            false
        )
        .is_err()
    );
    assert!(
        crate::browser::PreparedBrowserProfile::from_existing_key(
            "22222222-2222-4222-8222-222222222222",
            clone_key(&key),
            Some("X".repeat(513)),
            None,
            false
        )
        .is_err()
    );
}

// These cases run real shared Rust/WASM/WebCrypto in a DedicatedWorker. The
// explicit closed loopback endpoint cannot return an authenticated success; its
// genuine Fetch failure admits only the existing-key local read-only variant.
async fn cursor_client() -> crate::browser::BrowserCoreClient {
    let location=Reflect::get(&js_sys::global(),&JsValue::from_str("location")).unwrap();
    let origin=Reflect::get(&location,&JsValue::from_str("origin")).unwrap().as_string().unwrap();
    let prepared=crate::browser::PreparedBrowserProfile::from_existing_key(
        "11111111-1111-4111-8111-111111111111",clone_key(&key("AES-GCM",256,false,&["encrypt","decrypt"],7).await),None,None,false).unwrap();
    let client=crate::browser::BrowserCoreClient::restore("http://127.0.0.1:9",&origin,
        "11111111-1111-4111-8111-111111111111",prepared).await.unwrap();
    assert!(client.admitted_status().unwrap().local_read_only());client
}
fn local_cursor_fixture() -> serde_json::Value {
    serde_json::from_str::<serde_json::Value>(include_str!("../../openmates-rust/tests/fixtures/browser-idb-local-window.json")).unwrap()["input"].take()
}
fn cursor_metadata_reply(plan:&serde_json::Value,input:&serde_json::Value)->String {
    serde_json::json!({"version":1,"kind":"metadata","operationId":plan["operationId"],"databaseVersion":31,
        "chat_metadata":input["chat_metadata"],"messages":[],"wrappers":[],"boundary":null,
        "compression_checkpoints":input["compression_checkpoints"]}).to_string()
}
#[wasm_bindgen_test(async)]
async fn real_worker_binding_local_cursor_uses_opaque_key_and_actual_rust_decode_with_raw_storage_aliases() {
    use std::cell::Cell;
    let client=cursor_client().await;let status=client.admitted_status().unwrap();let input=local_cursor_fixture();
    let _export_guard=ExportGuard(forbid_export());let calls=Rc::new(Cell::new(0));let observed=calls.clone();
    let callback=Closure::<dyn FnMut(String)->JsValue>::new(move|encoded: String|{
        observed.set(observed.get()+1);let plan:serde_json::Value=serde_json::from_str(&encoded).unwrap();
        assert_eq!(plan["owner"],"11111111-1111-4111-8111-111111111111");
        assert_eq!(plan["chatId"],"22222222-2222-4222-8222-222222222222");
        let reply=if plan["kind"]=="metadata"{cursor_metadata_reply(&plan,&input)}else{
            assert_eq!(plan["maxPayloadRows"],20);assert_eq!(plan["lower"],serde_json::json!({"createdAt":110,"messageId":null,"open":true}));
            // Shared independent fixture has exactly ten normal rows after110.
            // This is an IO receipt fixture; output success is real Rust crypto.
            let rows=input["messages"].as_array().unwrap()[22..].iter().rev().cloned().collect::<Vec<_>>();
            serde_json::json!({"version":1,"kind":"messages","operationId":plan["operationId"],"databaseVersion":31,
                "messages":rows,"nextKey":null,"rangeExhausted":true}).to_string()
        };
        js_sys::Promise::resolve(&JsValue::from_str(&reply)).into()
    });
    let encoded=client.read_local_saved_chat_cursor(&status.handle(),status.generation(),&status.principal(),
        "22222222-2222-4222-8222-222222222222","{\"direction\":\"latest\"}",callback.as_ref().unchecked_ref::<js_sys::Function>().clone()).await.unwrap();
    let value:serde_json::Value=serde_json::from_str(&encoded).unwrap();assert_eq!(calls.get(),2);
    assert_eq!(value["chat"]["messages"].as_array().unwrap().len(),10);assert_eq!(value["chat"]["messages"][0]["content"],"Synthetic local row 23 Synthetic Person");
    assert!(value["startCursor"]["messageId"].as_str().unwrap().starts_with("2222222222-"));
    assert_eq!(value["messageMetadata"][0]["sourceMessageId"],value["startCursor"]["messageId"]);
    assert_eq!(value["readOnly"],true);assert_eq!(value["fresh"],false);assert_eq!(value["historyComplete"],false);assert_eq!(value["pagesRead"],0);assert_eq!(value["piiRestoration"],"page_local");
    assert_eq!(value["checkpointPresentation"]["checkpoint"]["summary"],"Latest synthetic summary");assert_eq!(value["checkpointPresentation"]["piiRestoration"],"stored");
}
#[wasm_bindgen_test(async)]
async fn real_worker_cursor_binding_rejects_duplicate_selectors_wrong_scope_and_malformed_io_without_key_export() {
    let client=cursor_client().await;let status=client.admitted_status().unwrap();let _guard=ExportGuard(forbid_export());
    let callback=Closure::<dyn FnMut(String)->JsValue>::new(|_|js_sys::Promise::resolve(&JsValue::from_str("{}")).into());
    for selector in ["{\"direction\":\"latest\",\"direction\":\"latest\"}",
        "{\"direction\":\"before\",\"cursor\":{\"chatId\":\"22222222-2222-4222-8222-222222222222\",\"scope\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"createdAt\":1,\"messageId\":\"physical-composite\"}}",
        "{\"direction\":\"latest\"}"] {
        assert!(client.read_local_saved_chat_cursor(&status.handle(),status.generation(),&status.principal(),
            "22222222-2222-4222-8222-222222222222",selector,callback.as_ref().unchecked_ref::<js_sys::Function>().clone()).await.is_err());
    }
}
#[wasm_bindgen_test(async)]
async fn dropped_real_worker_cursor_future_cannot_restore_a_closed_resource_after_late_io_settlement() {
    let mut client=cursor_client().await;let status=client.admitted_status().unwrap();let input=local_cursor_fixture();
    let resolver=Rc::new(RefCell::new(None::<js_sys::Function>));let held=resolver.clone();
    let reply=Rc::new(RefCell::new(None::<String>));let stored=reply.clone();
    let callback=Closure::<dyn FnMut(String)->JsValue>::new(move|encoded: String|{
        let plan:serde_json::Value=serde_json::from_str(&encoded).unwrap();*stored.borrow_mut()=Some(cursor_metadata_reply(&plan,&input));
        let held=held.clone();js_sys::Promise::new(&mut move|resolve,_reject|{*held.borrow_mut()=Some(resolve);}).into()
    });
    let handle=status.handle();let principal=status.principal();
    let mut future=Box::pin(client.read_local_saved_chat_cursor(&handle,status.generation(),&principal,
        "22222222-2222-4222-8222-222222222222","{\"direction\":\"latest\"}",callback.as_ref().unchecked_ref::<js_sys::Function>().clone()));
    require_pending(future.as_mut());drop(future);client.invalidate();
    resolver.borrow_mut().take().unwrap().call1(&JsValue::UNDEFINED,&JsValue::from_str(&reply.borrow_mut().take().unwrap())).unwrap();
    assert!(client.admitted_status().is_err());
}

#[wasm_bindgen_test(async)]
async fn actual_worker_exact_checkpoint_summary_reuses_opaque_key_and_metadata_callback_only(){
 let client=cursor_client().await;let status=client.admitted_status().unwrap();let input=local_cursor_fixture();let _guard=ExportGuard(forbid_export());
 let callback=Closure::<dyn FnMut(String)->JsValue>::new(move|encoded: String|{let plan:serde_json::Value=serde_json::from_str(&encoded).unwrap();assert_eq!(plan["kind"],"metadata");assert_eq!(plan["maxPayloadRows"],0);js_sys::Promise::resolve(&JsValue::from_str(&cursor_metadata_reply(&plan,&input))).into()});
 let encoded=client.read_local_checkpoint_summary(&status.handle(),status.generation(),&status.principal(),"22222222-2222-4222-8222-222222222222","20000000-0000-4000-8000-000000000001",callback.as_ref().unchecked_ref::<js_sys::Function>().clone()).await.unwrap();
 let value:serde_json::Value=serde_json::from_str(&encoded).unwrap();assert_eq!(value["checkpoint"]["summary"],"Older synthetic summary");assert_eq!(value["checkpoint"]["summaryState"],"loaded");assert_eq!(value["historyComplete"],false);assert_eq!(value["coverage"],"retained_selected");assert_eq!(value["piiRestoration"],"stored");
}
#[wasm_bindgen_test(async)]
async fn dropped_checkpoint_future_cannot_revive_invalidated_worker_on_late_metadata(){
 let mut client=cursor_client().await;let status=client.admitted_status().unwrap();let input=local_cursor_fixture();let resolver=Rc::new(RefCell::new(None::<js_sys::Function>));let held=resolver.clone();let packet=Rc::new(RefCell::new(None::<String>));let stored=packet.clone();
 let callback=Closure::<dyn FnMut(String)->JsValue>::new(move|encoded: String|{let plan:serde_json::Value=serde_json::from_str(&encoded).unwrap();*stored.borrow_mut()=Some(cursor_metadata_reply(&plan,&input));let held=held.clone();js_sys::Promise::new(&mut move|resolve,_|*held.borrow_mut()=Some(resolve)).into()});
 let handle=status.handle();let principal=status.principal();let mut future=Box::pin(client.read_local_checkpoint_summary(&handle,status.generation(),&principal,"22222222-2222-4222-8222-222222222222","20000000-0000-4000-8000-000000000001",callback.as_ref().unchecked_ref::<js_sys::Function>().clone()));
 require_pending(future.as_mut());drop(future);client.invalidate();resolver.borrow_mut().take().unwrap().call1(&JsValue::UNDEFINED,&JsValue::from_str(&packet.borrow_mut().take().unwrap())).unwrap();assert!(client.admitted_status().is_err());
}
