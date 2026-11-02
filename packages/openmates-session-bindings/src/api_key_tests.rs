//! Private allocation guards only: synthetic owned values, no runtime credit.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
use super::*;
use serde_json::json;
fn ok<T>(value:Result<T>)->T{match value{Ok(value)=>value,Err(_)=>panic!("binding failed")}}
fn bridge()->ApiKeyBridge{ok(ApiKeyBridge::new(r#"{"api_url":"http://127.0.0.1:1","api_key":"sk-api-fixture.localSuffix","device_id":"explicit-fixture","enhanced_privacy":false,"allow_private_operations":true}"#))}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn positive_final_allocation_wipes_owned_scratch(){let b=bridge();let r=ok(b.request());let mut output=ok(r.seal(Ok(json!({"secret":"synthetic"}))));let text=ok(output.encode_checked(|text|Ok(text.to_owned())));assert!(text.contains("synthetic"));assert!(output.output.is_empty());}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn allocation_cancel_denies_and_wipes(){let b=bridge();let r=ok(b.request());let mut output=ok(r.seal(Ok(json!({"secret":"synthetic"}))));let result=output.encode_checked(|text|{let value=text.to_owned();r.cancel();Ok(value)});assert_eq!(result.err().map(|e|e.code),Some("cancelled"));assert!(output.output.is_empty());}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn close_drops_only_core_owner_and_denies_queued_output(){let b=bridge();let r=ok(b.request());let mut output=ok(r.seal(Ok(json!({"secret":"synthetic"}))));ok(b.close());assert!(b.state.sdk.lock().expect("owner lock").is_none());assert_eq!(output.encode_checked(|text|Ok(text.to_owned())).err().map(|e|e.code),Some("cancelled"));assert!(output.output.is_empty());}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn stale_a_cleanup_does_not_cancel_b(){let b=bridge();let a=ok(b.request());let old=ok(a.seal(Ok(json!({"a":1}))));a.cancel();let next=ok(b.request());let output=ok(next.seal(Ok(json!({"b":2}))));drop(old);drop(a);assert_eq!(ok(output.encode_with(|s|Ok(s.to_owned()))),r#"{"b":2}"#);}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn final_allocation_never_waits_for_registry_lock(){let b=bridge();let r=ok(b.request());let output=ok(r.seal(Ok(json!({"value":1}))));let held=b.state.requests.lock().expect("registry lock");assert_eq!(ok(output.encode_with(|s|Ok(s.to_owned()))),r#"{"value":1}"#);drop(held);let next=ok(b.request());assert_eq!(b.state.requests.lock().expect("registry lock").len(),1);next.cancel();}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn last_gate_callback_cannot_hide_root_revocation(){let mut b=bridge();let fire=Arc::new(AtomicBool::new(false));let root=b.state.root.clone();let flag=fire.clone();match Arc::get_mut(&mut b.state){Some(state)=>state.gate=Arc::new(move||{if flag.load(Ordering::Acquire){root.cancel();}Ok(())}),None=>panic!("unique state")};let r=ok(b.request());let mut output=ok(r.seal(Ok(json!({"secret":"synthetic"}))));assert_eq!(output.encode_checked(|s|{let value=s.to_owned();fire.store(true,Ordering::Release);Ok(value)}).err().map(|e|e.code),Some("cancelled"));assert!(output.output.is_empty());}

fn scratch_bridge()->(ApiKeyBridge,Arc<Mutex<Vec<bool>>>,Arc<Mutex<Vec<bool>>>) {
    let mut b=bridge();let strings=Arc::new(Mutex::new(vec![]));let values=Arc::new(Mutex::new(vec![]));
    match Arc::get_mut(&mut b.state){Some(state)=>{state.input_string_wipes=Some(strings.clone());state.input_value_wipes=Some(values.clone());},None=>panic!("unique state")};(b,strings,values)
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn dropping_unpolled_skill_future_wipes_original_input_string(){
    let(b,strings,values)=scratch_bridge();let r=ok(b.request());
    let future=r.run_skill_prepare("web".into(),"search".into(),r#"{"query":"synthetic private input"}"#.into());
    assert!(strings.lock().expect("string probe").is_empty());drop(future);
    assert_eq!(*strings.lock().expect("string probe"),vec![true]);assert!(values.lock().expect("value probe").is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[tokio::test]
async fn pre_cancel_refuses_before_parse_and_wipes_owned_string(){
    let(b,strings,values)=scratch_bridge();let r=ok(b.request());r.cancel();
    let result=r.run_skill_prepare("web".into(),"search".into(),"malformed synthetic private input".into()).await;
    assert_eq!(result.err().map(|e|e.code),Some("cancelled"));
    assert_eq!(*strings.lock().expect("string probe"),vec![true]);assert!(values.lock().expect("value probe").is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[tokio::test]
async fn driver_refusal_after_parse_wipes_owned_value_before_core_transfer(){
    let(mut b,strings,values)=scratch_bridge();let count=Arc::new(std::sync::atomic::AtomicUsize::new(0));let calls=count.clone();let fire=Arc::new(AtomicBool::new(false));let enabled=fire.clone();let root=b.state.root.clone();
    match Arc::get_mut(&mut b.state){Some(state)=>state.gate=Arc::new(move||{if enabled.load(Ordering::Acquire)&&calls.fetch_add(1,Ordering::AcqRel)==1{root.cancel();}Ok(())}),None=>panic!("unique state")};
    let r=ok(b.request());count.store(0,Ordering::Release);fire.store(true,Ordering::Release);
    assert_eq!(r.run_skill_prepare("web".into(),"search".into(),r#"{"query":"synthetic private input"}"#.into()).await.err().map(|e|e.code),Some("cancelled"));
    assert_eq!(*strings.lock().expect("string probe"),vec![true]);assert_eq!(*values.lock().expect("value probe"),vec![true]);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[tokio::test]
async fn closed_request_refuses_before_parse_and_wipes_owned_string(){
    let(b,strings,values)=scratch_bridge();let r=ok(b.request());ok(b.close());
    let result=r.run_skill_prepare("web".into(),"search".into(),"malformed synthetic private input".into()).await;
    assert_eq!(result.err().map(|e|e.code),Some("cancelled"));assert_eq!(*strings.lock().expect("string probe"),vec![true]);assert!(values.lock().expect("value probe").is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn actual_constructor_malformed_options_after_key_keep_fixed_safe_errors() {
    let secret = "synthetic-key-never-echoed";
    let cases = [
        format!(r#"{{"api_key":"{secret}","unexpected_after_key":true}}"#),
        format!(r#"{{"api_key":"{secret}","api_url":"http://127.0.0.1:1"}}"#),
        r#"{"api_key":123,"api_url":"http://127.0.0.1:1"}"#.to_owned(),
    ];
    for raw in cases {
        let error = match ApiKeyBridge::new(&raw) {
            Ok(_) => panic!("malformed actual constructor must refuse"),
            Err(error) => error,
        };
        assert_eq!(error.code, "invalid_argument");
        assert_eq!(error.message, "Invalid API-key options.");
        assert_eq!(error.json(), r#"{"code":"invalid_argument","message":"Invalid API-key options."}"#);
        assert!(!error.json().contains(secret));
    }
    // Existing explicit valid constructor is still accepted without a network call.
    let client = bridge();
    ok(client.close());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[tokio::test]
async fn nested_driver_refusal_erases_owned_object_keys_and_values_without_core_transfer() {
    let (mut b, strings, values) = scratch_bridge();
    let count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let calls = count.clone();
    let fire = Arc::new(AtomicBool::new(false));
    let enabled = fire.clone();
    let root = b.state.root.clone();
    match Arc::get_mut(&mut b.state) {
        Some(state) => state.gate = Arc::new(move || {
            if enabled.load(Ordering::Acquire) && calls.fetch_add(1, Ordering::AcqRel) == 1 {
                root.cancel();
            }
            Ok(())
        }),
        None => panic!("unique state"),
    }
    let request = ok(b.request());
    count.store(0, Ordering::Release);
    fire.store(true, Ordering::Release);
    let input = json!({
        "nested-private-key": [{"private-value-key": "synthetic nested value"}, "synthetic array value"],
        "another-private-key": {"child-private-key": "synthetic child value"}
    }).to_string();
    let result = request.run_skill_prepare("web".into(), "search".into(), input).await;
    assert_eq!(result.err().map(|error| error.code), Some("cancelled"));
    assert_eq!(count.load(Ordering::Acquire), 2);
    assert_eq!(*strings.lock().expect("string probe"), vec![true]);
    assert_eq!(*values.lock().expect("value probe"), vec![true]);
    assert!(b.state.sdk.lock().expect("owner lock").is_some());
}
