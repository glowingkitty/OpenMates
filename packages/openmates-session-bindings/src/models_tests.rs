//! Model JSON envelope: Rust serde defaults, required-field refusals, workspaces.
use super::*;

fn call(input: Value) -> Result<Value, BindingError> {
    models_json(input.to_string()).map(|output| {
        serde_json::from_str(&output).unwrap_or_else(|_| panic!("binding output is JSON"))
    })
}

#[test]
fn fills_serde_defaults_for_chat_messages_and_items() {
    let chat = call(json!({"kind":"chat","value":{"id":"c","title":"t","messages":[{"id":"m","role":"user","content":"x"}]}}))
        .unwrap_or_else(|_| panic!("chat"));
    assert_eq!(
        chat,
        json!({"id":"c","title":"t","category":"","messages":[{"id":"m","role":"user","content":"x","sender":"","thinking":"","embeds":[]}]})
    );
    let item = call(json!({"kind":"item","value":{"id":"i","title":"t"}}))
        .unwrap_or_else(|_| panic!("item"));
    assert_eq!(item["fields"], Value::Null);
}

#[test]
fn refuses_missing_required_fields_and_lists_workspaces_in_order() {
    let refused = call(json!({"kind":"item","value":{"id":"synthetic-secret"}})).err();
    assert!(
        refused.is_some_and(
            |e| e.code == "invalid_argument" && !e.message.contains("synthetic-secret")
        )
    );
    let workspaces = call(json!({"kind":"workspaces"})).unwrap_or_else(|_| panic!("workspaces"));
    assert_eq!(workspaces[0], json!({"id":"chats","label":"Chats"}));
    assert_eq!(workspaces.as_array().map(Vec::len), Some(6));
}
