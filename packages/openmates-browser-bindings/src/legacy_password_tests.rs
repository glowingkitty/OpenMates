//! Real DedicatedWorker/WebCrypto comparisons, AUTHORED UNRUN until isolated CI.
//! Vectors independently pin UTF8/NUL, KDF, IV/tag layout and exact32-byte output.
//! Instrumentation observes only synthetic test buffers and actual key metadata.
//! No raw-key getter, production endpoint, storage mutation or enrollment exists.
//! Rejection/drop tests must retain the same primitive and settlement helper.
use super::*;
use js_sys::{Array, Function, Promise, Reflect};
use wasm_bindgen::{JsCast, JsValue};
use wasm_bindgen_futures::JsFuture;
use std::{cell::Cell, future::Future};
use wasm_bindgen_test::*;
fn vectors() -> serde_json::Value { serde_json::from_str(include_str!("../../openmates-rust/tests/crypto_fixtures/browser-legacy-password.json")).unwrap() }
async fn run(v: &serde_json::Value, guard: impl Fn() -> Result<()>) -> Result<Key> {
    unwrap(v["password"].as_str().unwrap(), 1, v["ciphertext"].as_str().unwrap(), v["salt"].as_str().unwrap(), v["iv"].as_str().unwrap(), guard).await
}
#[wasm_bindgen::prelude::wasm_bindgen(inline_js = "
export function observeLegacyPrimitive(hold) {
  const target=crypto.subtle, records=[], originals={}; let view, release, ready;
  const reached=new Promise(resolve=>{ready=resolve;});
  for(const name of ['importKey','deriveKey','decrypt','exportKey']) {
    const descriptor=Object.getOwnPropertyDescriptor(target,name), original=target[name]; originals[name]=()=>{if(descriptor)Object.defineProperty(target,name,descriptor);else delete target[name];};
    Object.defineProperty(target,name,{configurable:true,value:function(...args){
      if(name==='exportKey')throw Error('forbidden');
      const bytes=name==='importKey'?args[1]:name==='deriveKey'?args[0].salt:args[2];
      const operation=Reflect.apply(original,this,args);
      return operation.then(value=>{
        records.push({name,wiped:[...bytes].every(byte=>byte===0),extractable:value?.extractable,algorithm:value?.algorithm?.name,usages:value?.usages});
        if(name!=='decrypt')return value;
        view=new Uint8Array(value); if(!hold)return value;
        return new Promise(resolve=>{release=()=>resolve(value);ready();});
      });
    }});
  }
  return async action=>{
    if(action==='ready'){await reached;return true;}
    if(action==='release'){release();await new Promise(resolve=>setTimeout(resolve,0));return {wiped:[...view].every(byte=>byte===0),records};}
    if(action==='read')return {wiped:[...view].every(byte=>byte===0),records};
    for(const restore of Object.values(originals))restore();
  };
}
")]
extern "C" { #[wasm_bindgen::prelude::wasm_bindgen(js_name=observeLegacyPrimitive)] fn observe_legacy(hold: bool) -> Function; }
async fn observe(action: &Function, name: &str) -> JsValue {
    JsFuture::from(action.call1(&JsValue::UNDEFINED, &JsValue::from_str(name)).unwrap().dyn_into::<Promise>().unwrap()).await.unwrap()
}
struct Restore(Function);
impl Drop for Restore { fn drop(&mut self) { let _ = self.0.call1(&JsValue::UNDEFINED, &JsValue::from_str("restore")); } }
#[wasm_bindgen_test(async)]
async fn real_webcrypto_equals_native_rust_and_independent_vectors_without_export() {
    for v in vectors()["vectors"].as_array().unwrap() {
        let observer = observe_legacy(false); let _restore = Restore(observer.clone());
        let actual = run(v, || Ok(())).await.unwrap();
        let native = unwrap_password_master_key(v["password"].as_str().unwrap(), 1, v["ciphertext"].as_str().unwrap(), v["salt"].as_str().unwrap(), v["iv"].as_str().unwrap()).unwrap();
        assert_eq!(actual.as_ref(), native.as_ref()); assert_eq!(encode_key(&actual), v["master"]);
        let report = observe(&observer,"read").await;
        assert_eq!(Reflect::get(&report,&JsValue::from_str("wiped")).unwrap(),JsValue::TRUE);
        let records=Array::from(&Reflect::get(&report,&JsValue::from_str("records")).unwrap());
        assert_eq!(records.length(),3);
        for row in records.iter() { assert_eq!(Reflect::get(&row,&JsValue::from_str("wiped")).unwrap(),JsValue::TRUE); }
        let derived=records.get(1); assert_eq!(Reflect::get(&derived,&JsValue::from_str("extractable")).unwrap(),JsValue::FALSE);
        assert_eq!(Reflect::get(&derived,&JsValue::from_str("algorithm")).unwrap().as_string().as_deref(),Some("AES-GCM"));
        let usages=Array::from(&Reflect::get(&derived,&JsValue::from_str("usages")).unwrap()); assert_eq!(usages.length(),1);assert_eq!(usages.get(0).as_string().as_deref(),Some("decrypt"));
    }
}
#[wasm_bindgen_test(async)]
async fn every_original_scope_checkpoint_refuses_before_plaintext_publication() {
    let fixture=vectors(); let v=&fixture["vectors"][0];
    for fail_at in 1..=8 { let calls=Cell::new(0); assert!(run(v,||{calls.set(calls.get()+1);if calls.get()==fail_at{Err(Error::Cancelled)}else{Ok(())}}).await.is_err()); }
    for (field,bad) in [("salt","%%%"),("iv","%%%"),("ciphertext","%%%"),("password","wrong")] {
        let mut v=v.clone();v[field]=serde_json::Value::String(bad.into());assert!(run(&v,||Ok(())).await.is_err());
    }
}
#[wasm_bindgen_test(async)]
async fn dropped_consumer_wipes_late_real_decrypt_output() {
    let observer=observe_legacy(true);let _restore=Restore(observer.clone());let fixture=vectors();let v=&fixture["vectors"][0];
    let mut future=Box::pin(run(v,||Ok(())));let mut waiting=Box::pin(observe(&observer,"ready"));
    std::future::poll_fn(|cx| {
        assert!(future.as_mut().poll(cx).is_pending(), "decrypt must remain held");
        waiting.as_mut().poll(cx)
    }).await;
    drop(future);
    let report=observe(&observer,"release").await;
    assert_eq!(Reflect::get(&report,&JsValue::from_str("wiped")).unwrap(),JsValue::TRUE);
}
