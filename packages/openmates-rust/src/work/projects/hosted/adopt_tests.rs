//! Embed adoption: item id derivation, metadata plaintext per kind, folder choice, error codes and path-derived language.
use super::adopt::{AdoptionTarget, adoption_body, operation_id, project_item_id, turn_embed_key};
use super::adopt_plan::{FileRef, TurnEmbed, choose_folder, plan_turn, title_folder};
use super::tests::{CHAT, PROJECT, chat_key, project_key};
use super::*;

const APP: &str = "33333333-3333-4333-8333-333333333333";
const CHILD_A: &str = "44444444-4444-4444-8444-444444444444";
const CHILD_B: &str = "55555555-5555-4555-8555-555555555555";
const TEST: &str = "66666666-6666-4666-8666-666666666666";
const OTHER_APP: &str = "77777777-7777-4777-8777-777777777777";

fn embed(id: &str, embed_type: &str, status: &str) -> TurnEmbed {
    TurnEmbed {
        embed_id: id.into(),
        embed_type: embed_type.into(),
        status: status.into(),
        ..TurnEmbed::default()
    }
}

fn turn() -> Vec<TurnEmbed> {
    let mut app = embed(APP, "application", "finished");
    app.title = Some("Todo Board".into());
    app.file_refs = vec![
        FileRef {
            path: "index.html".into(),
            embed_id: CHILD_A.into(),
        },
        FileRef {
            path: "src/main.ts".into(),
            embed_id: CHILD_B.into(),
        },
    ];
    let mut a = embed(CHILD_A, "code", "finished");
    a.parent_embed_id = Some(APP.into());
    let b = embed(CHILD_B, "code", "processing");
    let mut test = embed(TEST, "test_result", "finished");
    test.run_id = Some("run-1".into());
    vec![app, a, b, test]
}

fn open(body: &Value, field: &str) -> String {
    crypto::server_fields::decrypt_text(body[field].as_str().unwrap(), &project_key(), &[]).unwrap()
}

#[test]
fn turn_plan_adopts_finished_children_then_application_then_test_results() {
    let plan: Vec<AdoptionTarget> = plan_turn(CHAT, &turn(), &[])
        .into_iter()
        .map(|planned| planned.unwrap())
        .collect();
    let order: Vec<(&str, AdoptEmbedKind, Option<&str>)> = plan
        .iter()
        .map(|t| (t.embed_id.as_str(), t.kind, t.path.as_deref()))
        .collect();
    // The unfinished child is skipped.
    assert_eq!(
        order,
        [
            (CHILD_A, AdoptEmbedKind::File, Some("web-app/index.html")),
            (APP, AdoptEmbedKind::Application, Some("web-app")),
            (TEST, AdoptEmbedKind::TestResult, None),
        ]
    );
}

#[test]
fn adopted_file_item_id_is_the_hosted_identity_of_its_folder_path() {
    let key = project_key();
    let plan = plan_turn(CHAT, &turn(), &[]);
    let file = plan[0].as_ref().unwrap();
    assert_eq!(
        project_item_id(&key, file).unwrap(),
        hosted_file_identity(&key, "web-app/index.html", HostedIdentityKind::Item).unwrap()
    );
    // Application and test-result links are keyed by their embed, never a path.
    let app = plan[1].as_ref().unwrap();
    assert_ne!(
        project_item_id(&key, app).unwrap(),
        hosted_file_identity(&key, "web-app", HostedIdentityKind::Item).unwrap()
    );
    // Deterministic, path-bound idempotency key.
    assert_eq!(
        operation_id(&key, PROJECT, file).unwrap(),
        operation_id(&key, PROJECT, file).unwrap()
    );
    let mut moved = file.clone();
    moved.path = Some("web-app/other.html".into());
    assert_ne!(
        operation_id(&key, PROJECT, file).unwrap(),
        operation_id(&key, PROJECT, &moved).unwrap()
    );
}

#[test]
fn adoption_body_seals_metadata_per_kind_and_wraps_the_existing_key() {
    let key = project_key();
    let embeds = turn();
    let plan: Vec<AdoptionTarget> = plan_turn(CHAT, &embeds, &[])
        .into_iter()
        .map(|planned| planned.unwrap())
        .collect();
    let expected = [
        json!({"path": "web-app/index.html", "source": "hosted_project_file",
            "application_embed_id": APP, "application_path": "index.html"}),
        json!({"path": "web-app", "source": "project_application", "entry_path": "index.html"}),
        json!({"source": "project_test_result", "run_id": "run-1"}),
    ];
    for (target, metadata) in plan.iter().zip(expected) {
        let embed_key = turn_embed_key(&embeds, &target.embed_id, &chat_key()).unwrap();
        let body = adoption_body(&key, PROJECT, Some("team-1"), target, &embed_key).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&open(&body, "encrypted_metadata")).unwrap(),
            metadata
        );
        assert_eq!(open(&body, "target_id_encrypted"), target.embed_id);
        assert_eq!(body["kind"], target.kind.wire());
        assert_eq!(body["chat_id"], CHAT);
        assert_eq!(body["team_id"], "team-1");
        let wrapped = crypto::server_fields::decrypt_bytes(
            body["project_key_wrapper"].as_str().unwrap(),
            &key,
            &[],
        )
        .unwrap();
        assert_eq!(wrapped.as_slice(), embed_key.as_slice());
    }
    assert_eq!(
        open(
            &adoption_body(&key, PROJECT, None, &plan[1], &[0; 32]).unwrap(),
            "encrypted_display_name"
        ),
        "Todo Board"
    );
}

#[test]
fn turn_embed_keys_follow_the_persisted_parent_chain() {
    let embeds = turn();
    let chat = chat_key();
    let app_key = crypto::derive_embed_key(&chat, APP).unwrap();
    assert_eq!(*turn_embed_key(&embeds, CHILD_A, &chat).unwrap(), *app_key);
    assert_eq!(
        *turn_embed_key(&embeds, CHILD_B, &chat).unwrap(),
        *crypto::derive_embed_key(&chat, CHILD_B).unwrap()
    );
    assert_eq!(
        turn_embed_key(&embeds, "missing", &chat).unwrap_err(),
        HostedFileError::Refused("embed_key_unavailable")
    );
}

#[test]
fn folder_choice_defaults_to_web_app_and_slugs_the_title_when_taken() {
    assert_eq!(choose_folder(&[], APP, "Todo Board"), "web-app");
    let taken = [("web-app".to_owned(), OTHER_APP.to_owned())];
    assert_eq!(choose_folder(&taken, APP, "Todo Board"), "todo-board");
    let both = [
        ("web-app".to_owned(), OTHER_APP.to_owned()),
        ("todo-board".to_owned(), OTHER_APP.to_owned()),
    ];
    assert_eq!(choose_folder(&both, APP, "Todo Board"), "todo-board-2");
    // An already adopted application keeps its folder.
    let own = [("my-app".to_owned(), APP.to_owned())];
    assert_eq!(choose_folder(&own, APP, "Todo Board"), "my-app");
    assert_eq!(title_folder("!!!", APP), "app-33333333");
    let plan = plan_turn(CHAT, &turn(), &taken);
    assert_eq!(
        plan[0].as_ref().unwrap().path.as_deref(),
        Some("todo-board/index.html")
    );
}

#[test]
fn server_codes_map_to_typed_errors() {
    for (code, error) in [
        ("project_not_found", ProjectEmbedAdoptError::ProjectNotFound),
        ("forbidden", ProjectEmbedAdoptError::Forbidden),
        ("embed_not_found", ProjectEmbedAdoptError::EmbedNotFound),
        (
            "embed_already_linked",
            ProjectEmbedAdoptError::EmbedAlreadyLinked,
        ),
        ("path_conflict", ProjectEmbedAdoptError::PathConflict),
        ("invalid_request", ProjectEmbedAdoptError::InvalidRequest),
    ] {
        let mapped = ProjectEmbedAdoptError::from(HostedFileError::Rejected(code.into()));
        assert_eq!(mapped, error);
        assert_eq!(mapped.code(), code);
    }
    assert_eq!(
        ProjectEmbedAdoptError::from(HostedFileError::Rejected("other".into())).code(),
        "adopt_rejected"
    );
    // Backend codes beyond the typed set keep their stable code.
    assert_eq!(
        ProjectEmbedAdoptError::from(HostedFileError::Rejected(
            "operation_payload_mismatch".into()
        ))
        .code(),
        "operation_payload_mismatch"
    );
    assert_eq!(
        ProjectEmbedAdoptError::from(HostedFileError::Refused("invalid_path")).code(),
        "invalid_path"
    );
    assert_eq!(
        ProjectEmbedAdoptError::Core(Error::Cancelled).code(),
        "cancelled"
    );
}

#[test]
fn embed_types_map_to_adoption_kinds() {
    assert_eq!(
        AdoptEmbedKind::of_embed_type("code"),
        Some(AdoptEmbedKind::File)
    );
    assert_eq!(
        AdoptEmbedKind::of_embed_type("application"),
        Some(AdoptEmbedKind::Application)
    );
    assert_eq!(
        AdoptEmbedKind::of_embed_type("code-test-result"),
        Some(AdoptEmbedKind::TestResult)
    );
    assert_eq!(AdoptEmbedKind::of_embed_type("sheet"), None);
}

#[test]
fn turn_embed_record_reads_paths_titles_and_refs_from_content() {
    let record = TurnEmbed::from_row(
        APP,
        &json!({"type": "application", "status": "finished"}),
        &json!({"name": "Todo", "file_refs": [{"path": "a.js", "embed_id": CHILD_A, "role": "source"}],
            "code": "never copied"}),
    );
    assert_eq!(record.title.as_deref(), Some("Todo"));
    assert_eq!(
        record.file_refs,
        vec![FileRef {
            path: "a.js".into(),
            embed_id: CHILD_A.into()
        }]
    );
    assert!(record.starts_adoption());
    assert!(
        !serde_json::to_string(&record)
            .unwrap()
            .contains("never copied")
    );
}

#[test]
fn new_file_language_comes_from_its_path() {
    for (path, language) in [
        ("src/main.ts", "typescript"),
        ("app.py", "python"),
        ("README.md", "markdown"),
        ("styles/site.css", "css"),
        ("notes.unknownext", "text"),
    ] {
        assert_eq!(language_for_path(path).unwrap(), language, "{path}");
    }
}

#[test]
fn application_and_test_result_links_are_not_listed_as_files() {
    let key = project_key();
    let link = |target: &str, metadata: Value, kind: Option<&str>| {
        json!({
            "item_type": "embed",
            "link_kind": kind,
            "project_item_id": hosted_file_identity(&key, &format!("x/{target}"), HostedIdentityKind::Item).unwrap(),
            "target_id_encrypted": super::job::seal(target, &key).unwrap(),
            "encrypted_metadata": super::job::seal(&metadata.to_string(), &key).unwrap(),
        })
    };
    let items = json!([
        link(
            CHILD_A,
            super::adopt_plan::file_metadata("web-app/index.html", Some((APP, "index.html"))),
            Some("file")
        ),
        link(
            APP,
            super::adopt_plan::application_metadata("web-app", Some("index.html")),
            Some("application")
        ),
        // A listing without `link_kind` still recognizes the link by its source.
        link(
            OTHER_APP,
            super::adopt_plan::application_metadata("other", None),
            None
        ),
        link(
            TEST,
            super::adopt_plan::test_result_metadata(Some("run-1")),
            Some("test_result")
        ),
    ]);
    let files = super::io::linked_files(&items, &key).unwrap();
    let paths: Vec<&str> = files.iter().map(|f| f.path.as_str()).collect();
    assert_eq!(paths, vec!["web-app/index.html"]);
}
