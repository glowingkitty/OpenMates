//! Keep the maintained CLI catalog honest: a command the native dispatcher
//! accepts must not be declared unsupported, and an unsupported declaration
//! must not hide a native handler. Partial still means not feature complete.
use super::*;

#[test]
fn catalog_status_matches_native_dispatch() {
    // `chat` dispatches only with a goal positional, so a bare path is not
    // a meaningful probe of its declared partial status.
    const POSITIONAL_ONLY: &[&str] = &["chat"];
    let drift = catalog()
        .commands
        .iter()
        .filter(|record| !POSITIONAL_ONLY.contains(&record.path.join(" ").as_str()))
        .filter(|record| {
            let invocation = Invocation {
                path: record.path.clone(),
                positionals: vec![],
                flags: Default::default(),
            };
            handlers::requirements(&invocation).supported
                != (record.implementation.status != "unsupported")
        })
        .map(|record| record.path.join(" "))
        .collect::<Vec<_>>();
    assert!(
        drift.is_empty(),
        "Update config/cli-command-catalog.json implementation status for: {drift:?}"
    );
    let raw: Value =
        serde_json::from_str(include_str!("../../assets/cli-command-catalog.json")).unwrap();
    let count = |status: &str| {
        catalog()
            .commands
            .iter()
            .filter(|record| record.implementation.status == status)
            .count()
    };
    assert_eq!(raw["coverage"]["native_handlers_partial"], count("partial"));
    assert_eq!(raw["coverage"]["unsupported"], count("unsupported"));
}
