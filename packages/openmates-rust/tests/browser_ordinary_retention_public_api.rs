//! External consumer visibility contract for the ordinary browser operation.
//! The WASM adapter imports this exact public client-module path.
//! Native compilation catches a missing re-export without a WASM target build.
//! No operation is constructed, authenticated, persisted or acknowledged here.
//! Authored UNRUN for isolated Rust CI; no private credential discovery or IO.
// contract-test-file: tooling
use openmates_sdk::{Client,Result,client::BrowserOrdinaryKeyRetention};
#[test]
fn declared_client_module_operation_and_method_are_public_to_other_crates(){
 let _effect:fn(&BrowserOrdinaryKeyRetention,&Client)->Result<String>=BrowserOrdinaryKeyRetention::effect_json;
}
