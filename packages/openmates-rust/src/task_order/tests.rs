// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,cli.output.actionable-readable
use super::*;
use serde_json::json;

#[test]
fn qualified_node24_vectors_preserve_rows_stable_ties_and_explicit_locales() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../tests/task_order/task-order.json")).unwrap();
    for vector in fixture["capabilities"]["local.task-order.v1"]["vectors"]
        .as_array()
        .unwrap()
    {
        let original = vector["tasks"].as_array().unwrap().clone();
        let mut tasks = original.clone();
        let result = TaskOrder::try_new(vector["locale"].as_str().unwrap())
            .and_then(|order| order.sort_tasks(&mut tasks));
        if vector["error"].is_string() {
            assert!(matches!(result, Err(Error::Invalid(_))), "{}", vector["id"]);
            assert_eq!(
                tasks, original,
                "invalid input must not reorder: {}",
                vector["id"]
            );
        } else {
            result.unwrap();
            let expected = vector["expected_indices"]
                .as_array()
                .unwrap()
                .iter()
                .map(|index| original[index.as_u64().unwrap() as usize].clone())
                .collect::<Vec<_>>();
            assert_eq!(tasks, expected, "{}", vector["id"]);
        }
    }
}

#[test]
fn native_items_use_identical_position_and_title_policy_without_mutating_fields() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../tests/task_order/task-order.json")).unwrap();
    for vector in fixture["capabilities"]["local.task-order.v1"]["vectors"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|v| v["expected_indices"].is_array())
    {
        let mut items = vector["tasks"]
            .as_array()
            .unwrap()
            .iter()
            .enumerate()
            .map(|(i, row)| Item {
                id: i.to_string(),
                title: row["title"].as_str().unwrap_or("").into(),
                fields: row.clone(),
                ..Default::default()
            })
            .collect::<Vec<_>>();
        let original = items.iter().map(|i| i.fields.clone()).collect::<Vec<_>>();
        TaskOrder::try_new(vector["locale"].as_str().unwrap())
            .unwrap()
            .sort_items(&mut items)
            .unwrap();
        assert_eq!(
            items
                .iter()
                .map(|i| i.id.parse::<usize>().unwrap())
                .collect::<Vec<_>>(),
            vector["expected_indices"]
                .as_array()
                .unwrap()
                .iter()
                .map(|i| i.as_u64().unwrap() as usize)
                .collect::<Vec<_>>(),
            "{}",
            vector["id"]
        );
        for item in items {
            assert_eq!(item.fields, original[item.id.parse::<usize>().unwrap()]);
        }
    }
}

#[test]
fn invalid_last_row_does_not_partially_reorder_and_equivalent_titles_keep_input_order() {
    assert!(TaskOrder::try_new("en_US").is_err());
    assert!(TaskOrder::try_new("en--US").is_err());
    let order = TaskOrder::try_new("en-US").unwrap();
    let mut rows = vec![
        json!({"title":"Zulu","position":100}),
        json!({"title":"Alpha","position":1}),
        json!({"title":"Bad","position":"0"}),
    ];
    let before = rows.clone();
    assert!(order.sort_tasks(&mut rows).is_err());
    assert_eq!(rows, before);
    let mut items = vec![
        Item {
            title: "Zulu".into(),
            fields: json!({"position":2}),
            ..Default::default()
        },
        Item {
            title: "Alpha".into(),
            fields: json!({"position":false}),
            ..Default::default()
        },
    ];
    assert!(order.sort_items(&mut items).is_err());
    assert_eq!(items[0].title, "Zulu");
    let mut rows = vec![
        json!({"id":"z","title":"é","position":-0.0}),
        json!({"id":"a","title":"e\u{301}","position":0}),
    ];
    order.sort_tasks(&mut rows).unwrap();
    assert_eq!(rows[0]["id"], "z");
    assert_eq!(rows[1]["id"], "a");
}
