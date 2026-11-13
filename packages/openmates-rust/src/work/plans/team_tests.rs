use super::*;
use crate::work::tasks::tests::{client, mock};

fn vectors() -> Value {
    serde_json::from_str(include_str!("team_plan_ts_vectors.json")).unwrap()
}
fn v(name: &str) -> String {
    vectors()[name].as_str().unwrap().to_owned()
}
fn key(name: &str) -> [u8; 32] {
    use base64::{Engine, engine::general_purpose::STANDARD};
    STANDARD.decode(v(name)).unwrap().try_into().unwrap()
}
/// A Team-scoped record as `GET /v1/user-plans?team_id=` returns it.
fn record(wrappers: Value) -> Value {
    json!({
        "plan_id": v("plan_id"),
        "hashed_team_id": v("hashed_team_id"),
        "hashed_user_id": null,
        "status": "active",
        "version": 3,
        "linked_project_ids": [],
        "encrypted_title": v("encrypted_title"),
        "encrypted_goal": v("encrypted_goal"),
        "key_wrappers": wrappers,
    })
}
fn team_wrapper() -> Value {
    json!({"key_type":"team","hashed_team_id":v("hashed_team_id"),"team_key_epoch":1,"encrypted_plan_key":v("team_wrapper_encrypted_plan_key")})
}
fn master_wrapper() -> Value {
    json!({"key_type":"master","encrypted_plan_key":v("master_wrapper_encrypted_plan_key")})
}
fn team_row() -> Value {
    json!({"team":{"team_id":v("team_id"),"encrypted_team_key":v("encrypted_team_key")}})
}
fn team_plans(client: &mut Client) -> Plans<'_> {
    client.plans().with_filters(PlanFilters {
        team_id: Some(v("team_id")),
        ..Default::default()
    })
}

#[test]
fn ts_team_wrapper_and_owner_master_wrapper_open_the_same_plan_key() {
    let master = key("master_key_b64");
    let team = v("team_id");
    let via_team = team::plan_key(
        &record(json!([team_wrapper()])),
        &master,
        Some(&key("team_key_b64")),
        &team,
    )
    .unwrap();
    let via_master =
        team::plan_key(&record(json!([master_wrapper()])), &master, None, &team).unwrap();
    assert_eq!(*via_team, key("plan_key_b64"));
    assert_eq!(*via_master, key("plan_key_b64"));
    let plan = decode_with_key(record(json!([team_wrapper()])), via_team).unwrap();
    assert_eq!(plan.public["title"], "Synthetic Team Plan");
    assert_eq!(plan.public["goal"], "Synthetic shared goal");
}

#[test]
fn team_scope_never_opens_foreign_or_ambiguous_records() {
    let master = key("master_key_b64");
    let team_key = key("team_key_b64");
    let team = v("team_id");
    let open =
        |raw: Value, team_key: Option<&[u8; 32]>| team::plan_key(&raw, &master, team_key, &team);
    // Personal record (no Team hash) and another Team's record.
    let mut personal = record(json!([master_wrapper()]));
    personal["hashed_team_id"] = Value::Null;
    assert!(matches!(open(personal, None), Err(Error::Forbidden)));
    let mut foreign = record(json!([master_wrapper()]));
    foreign["hashed_team_id"] = json!(hash("99999999-9999-4999-8999-999999999999"));
    assert!(matches!(open(foreign, None), Err(Error::Forbidden)));
    // No wrapper of the caller, duplicate master or duplicate Team wrappers.
    assert!(matches!(
        open(record(json!([])), None),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        open(record(json!([master_wrapper(), master_wrapper()])), None),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        open(
            record(json!([team_wrapper(), team_wrapper()])),
            Some(&team_key)
        ),
        Err(Error::Forbidden)
    ));
    // A non-epoch-1 Team wrapper is not a Team wrapper; nothing else opens it.
    let mut epoch = team_wrapper();
    epoch["team_key_epoch"] = json!(2);
    assert!(matches!(
        open(record(json!([epoch])), None),
        Err(Error::Forbidden)
    ));
    // A wrapper bound to another Plan or already expired is rejected.
    let mut bound = master_wrapper();
    bound["hashed_plan_id"] = json!(hash("aabbccdd-3333-4333-8333-aabbccddeeff"));
    assert!(matches!(
        open(record(json!([bound])), None),
        Err(Error::Forbidden)
    ));
    let mut expired = master_wrapper();
    expired["expires_at"] = json!(1);
    assert!(matches!(
        open(record(json!([expired])), None),
        Err(Error::Forbidden)
    ));
    // Wrong Team key fails authentication instead of falling back.
    assert!(matches!(
        open(
            record(json!([team_wrapper(), master_wrapper()])),
            Some(&[1; 32])
        ),
        Err(Error::Crypto)
    ));
}

#[tokio::test]
async fn team_list_show_and_child_reads_use_team_scope_and_skip_undecryptable() {
    let team = v("team_id");
    let mut criterion = json!({"criterion_id":"c1","encrypted_text":v("encrypted_criterion_text")});
    criterion["status"] = json!("open");
    let mut other = record(json!([]));
    other["plan_id"] = json!("aabbccdd-4444-4444-8444-aabbccddeeff");
    let (api, server) = mock(vec![
        json!({"plans":[record(json!([team_wrapper()])), other]}),
        team_row(),
        json!({"plan":record(json!([master_wrapper()]))}),
        json!({"plan":record(json!([team_wrapper()]))}),
        json!({"criteria":[criterion]}),
    ])
    .await;
    let mut client = client(&api);
    let mut plans = team_plans(&mut client);
    let listed = plans.list().await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0]["title"], "Synthetic Team Plan");
    assert_eq!(
        plans.skipped_plan_ids(),
        ["aabbccdd-4444-4444-8444-aabbccddeeff".to_owned()]
    );
    let shown = plans.show(&v("plan_id")).await.unwrap();
    assert_eq!(shown["goal"], "Synthetic shared goal");
    let criteria = plans.list_criteria(&v("plan_id")).await.unwrap();
    assert_eq!(criteria[0]["text"], "Synthetic team criterion");
    let requests = server.await.unwrap();
    let query = format!("team_id={team}");
    assert!(requests[0].starts_with(&format!("GET /v1/user-plans?{query} ")));
    assert!(requests[1].starts_with(&format!("GET /v1/teams/{team} ")));
    assert!(requests[2].starts_with(&format!("GET /v1/user-plans/{}?{query} ", v("plan_id"))));
    // The cached Team key is reused: no second Team fetch.
    assert!(requests[3].starts_with(&format!("GET /v1/user-plans/{}?{query} ", v("plan_id"))));
    assert!(requests[4].starts_with(&format!(
        "GET /v1/user-plans/{}/criteria?{query} ",
        v("plan_id")
    )));
}

#[tokio::test]
async fn team_scoped_writes_and_personal_only_reads_are_refused_before_any_request() {
    let (api, server) = mock(vec![]).await;
    let mut client = client(&api);
    let id = v("plan_id");
    let refused = |result: Result<Value>| {
        assert!(matches!(
            result,
            Err(Error::Unavailable {
                code: "team_plan_writes_unavailable",
                ..
            })
        ))
    };
    let input = PlanCreate {
        title: "T".into(),
        goal: "G".into(),
        linked_project_ids: vec![id.clone()],
        ..Default::default()
    };
    refused(team_plans(&mut client).create(input).await);
    refused(
        team_plans(&mut client)
            .update(&id, PlanPatch::default())
            .await,
    );
    refused(team_plans(&mut client).delete(&id, true).await);
    refused(team_plans(&mut client).complete(&id).await);
    refused(team_plans(&mut client).activate(&id, None).await);
    refused(
        team_plans(&mut client)
            .history(&id, None)
            .await
            .map(Value::from),
    );
    refused(
        team_plans(&mut client)
            .list_learnings(&id)
            .await
            .map(Value::from),
    );
    let mut both = client.plans().with_filters(PlanFilters {
        personal: true,
        team_id: Some(id.clone()),
        ..Default::default()
    });
    assert!(matches!(both.list().await, Err(Error::Invalid(_))));
    drop(client);
    assert!(server.await.unwrap().is_empty());
}
