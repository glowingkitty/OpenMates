//! Durable Task action adapter: journal routing, npm flag parsing and receipt output shapes.
use super::*;
use std::collections::BTreeMap;

fn invocation(path: &str, positionals: &[&str], flags: &[(&str, &str)]) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: positionals.iter().map(|s| (*s).to_owned()).collect(),
        flags: flags
            .iter()
            .map(|(k, v)| ((*k).to_owned(), Value::String((*v).to_owned())))
            .collect::<BTreeMap<_, _>>(),
    }
}

#[test]
fn every_backend_task_mutation_routes_through_the_journal_but_resume_does_not() {
    for path in COMMANDS {
        assert!(handles(path), "{path}");
        let invocation = invocation(path, &[], &[]);
        assert!(super::super::task_queue::supported(&invocation), "{path}");
    }
    assert!(!handles("tasks resume"));
    assert!(!handles("tasks list"));
}

#[test]
fn parsers_keep_npm_flag_contracts() {
    let block = invocation(
        "tasks block",
        &["T"],
        &[("reason", "other"), ("reason-text", "x")],
    );
    assert_eq!(block_args(&block).ok().unwrap(), ("other", Some("x")));
    assert!(block_args(&invocation("tasks block", &["T"], &[])).is_err());
    let movement = task_move(&invocation("tasks reorder", &["T"], &[("position", "7")]))
        .ok()
        .unwrap();
    assert_eq!(movement.position, Some(7));
    assert!(task_move(&invocation("tasks reorder", &["T"], &[("position", "x")])).is_err());
    let dependency = target(&invocation(
        "tasks dependencies add",
        &["T", "plan:P1"],
        &[],
    ))
    .ok()
    .unwrap();
    assert!(matches!(dependency.kind, WorkKind::Plan) && dependency.id == "P1");
    assert!(target(&invocation("tasks dependencies add", &["T", "chat:1"], &[])).is_err());
}

#[test]
fn receipts_render_with_npm_json_shapes() {
    let (value, text) = render("tasks reorder", json!([{"task_id":"t"}]))
        .ok()
        .unwrap();
    assert_eq!(value, json!({"tasks":[{"task_id":"t"}]}));
    assert_eq!(text, "Task reordered.");
    let (value, _) = render("tasks activity delete", json!({"entry_id":"e"}))
        .ok()
        .unwrap();
    assert_eq!(value["entry"]["entry_id"], "e");
    let (value, _) = render("tasks dependencies remove", json!({"deleted":true}))
        .ok()
        .unwrap();
    assert_eq!(value, json!({"deleted":true}));
    assert!(render("tasks block", json!({"task_id":"t"})).is_err());
}
