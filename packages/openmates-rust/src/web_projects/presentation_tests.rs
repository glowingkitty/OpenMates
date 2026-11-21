//! `projectPresentationPlan` and `projectBackfillPick` JSON adapters.
use super::*;

#[test]
fn plan_answers_fields_and_state_for_a_user_edit() {
    let out = plan(&json!({"origin": "user", "state": null,
        "current": {"description": "", "icon": "folder", "category": ""},
        "proposal": {"icon": "Chef-Hat"}, "itemCount": 0, "chats": []}))
    .unwrap();
    assert_eq!(out["write"], true);
    assert_eq!(out["fields"], json!({"icon": "chef-hat"}));
    assert_eq!(out["state"]["sources"]["icon"], "user");
}

#[test]
fn backfill_pick_takes_stateless_projects_with_items_up_to_the_limit() {
    let out = backfill_pick(&json!({"limit": 2, "projects": [
        {"projectId": "a", "hasState": true, "itemCount": 4},
        {"projectId": "b", "hasState": false, "itemCount": 0},
        {"projectId": "c", "hasState": false, "itemCount": 1},
        {"projectId": "d", "hasState": false, "itemCount": 2},
        {"projectId": "e", "hasState": false, "itemCount": 2}]}))
    .unwrap();
    assert_eq!(out, json!({"projectIds": ["c", "d"]}));
}
