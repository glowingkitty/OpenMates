//! Authored original-scope no-IO tests; runtime UNRUN in this packet.
// contract-test-file: tooling
use super::*;
fn client()->Client {
    let api="https://example.invalid";
    let mut client=Client::new(api,Some(Session{api_url:api.into(),session_id:"inventory-fixture".into(),cookies:BTreeMap::new(),ws_token:None,master_key:Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn existing_apps_inventory_never_acquires_a_new_private_operation_prerequisite() {
    let mut client=client();
    let calls=Arc::new(std::sync::atomic::AtomicUsize::new(0));let called=calls.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{called.fetch_add(1,std::sync::atomic::Ordering::SeqCst);Err(Error::Forbidden)})));
    let prepared=client.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().unwrap();
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst),0,"existing list Apps does not invoke private-operation policy");
    prepared.scope.check(&client).unwrap();
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst),0);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn b_control_cancels_only_original_b_without_replacing_parent_or_ordinary_child_or_a() {
    let mut client=client();let parent=client.operation_parent.clone();let ordinary=client.operation_cancel.clone();
    let a=super::super::owned_operation::OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let b=client.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().unwrap();
    let control=b.control();control.cancel();
    assert!(b.scope.check(&client).is_err());a.check(&client).unwrap();
    assert_eq!(client.operation_parent,parent);assert_eq!(client.operation_cancel,ordinary);
    assert!(!parent.is_cancelled());assert!(!ordinary.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn no_principal_import_uses_only_legacy_mapping_and_never_relabels_owned_denial_as_fallback() {
    let mut client=client();client.user=Value::Null;
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().is_none());
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
    let cancelled=CancellationToken::new();cancelled.cancel();
    assert!(client.prepare_owned_apps_inventory(cancelled).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn unreadable_owner_with_any_retained_original_lease_never_selects_import_compatibility() {
    let mut client=client();
    let original=super::super::owned_operation::OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let registry=client.owned_operations.clone();let parent=client.operation_parent.clone();
    client.user=Value::Null;
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err());
    assert!(Arc::ptr_eq(&registry,&client.owned_operations));assert_eq!(parent,client.operation_parent);assert!(!parent.is_cancelled());
    original.request().cancel();
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err(),"retained cancelled original still cannot be recaptured as import");
    drop(original);
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err(),"prior genuine owned admission remains restrictive after drop");
    let mut fresh=super::tests::client();fresh.user=Value::Null;
    assert!(fresh.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().is_none(),"genuinely original native import keeps existing behavior");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn invalidated_retained_owned_history_never_becomes_native_import_compatibility() {
    let mut client=client();
    let original=super::super::owned_operation::OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    client.user=Value::Null;
    assert!(client.owned_operations.checked_auth_binding(&client).is_err(),"actual unreadable binding retires registry");
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err(),"cleared registry entries do not erase actual owned history");
    drop(original);
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err(),"history remains after last retired lease drops");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn pre_owned_native_import_plumbing_does_not_add_auth_or_private_prerequisite_but_browser_transport_refuses() {
    let mut client=client();client.user=Value::Null;
    client.set_operation_cancel(CancellationToken::new());
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().is_none(),"ordinary pre-admission plumbing is not owned history");
    client.browser_password_transport=true;
    assert!(client.prepare_owned_apps_inventory(CancellationToken::new()).is_err(),"pending browser password transport cannot impersonate native import");
}
