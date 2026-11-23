//! Rust-only Project presentation decisions of the web `projectDecide` op set.
//!
//! Thin JSON adapter over `work::projects::presentation` (the single rule owner); the page
//! only encrypts and sends what these ops answer. Contract section 8 of
//! `docs/plans/project-presentation/contract.md`; spec `projects.presentation.*`.
use super::{Fault, Outcome};
use crate::work::{
    PresentationChat, PresentationFields, PresentationOrigin, PresentationState,
    PresentationValues, plan_write,
};
use serde_json::{Value, json};

fn malformed(reason: &str) -> Fault {
    Fault::Malformed(reason.to_owned())
}

/// `projectPresentationPlan`: `{write, fields, state}` for one origin.
pub(super) fn plan(input: &Value) -> Outcome {
    let origin: PresentationOrigin =
        serde_json::from_value(input["origin"].clone()).map_err(|_| malformed("origin"))?;
    let state: Option<PresentationState> = match &input["state"] {
        Value::Null => None,
        value => Some(serde_json::from_value(value.clone()).map_err(|_| malformed("state"))?),
    };
    let proposal = PresentationFields::from_json(&input["proposal"]).map_err(|e| malformed(&e))?;
    let current = PresentationValues::from_json(&input["current"]);
    let item_count = input["itemCount"].as_u64().unwrap_or(0) as usize;
    let chats: Vec<PresentationChat> = match &input["chats"] {
        Value::Null => vec![],
        value => serde_json::from_value(value.clone()).map_err(|_| malformed("chats"))?,
    };
    Ok(
        match plan_write(
            origin,
            state.as_ref(),
            &current,
            &proposal,
            item_count,
            &chats,
        ) {
            Some(write) => json!({"write": true, "fields": write.fields, "state": write.state}),
            None => json!({"write": false, "fields": {}, "state": input["state"]}),
        },
    )
}

/// `projectBackfillPick`: ids of Projects without state that have items, in list order.
pub(super) fn backfill_pick(input: &Value) -> Outcome {
    let projects = input["projects"]
        .as_array()
        .ok_or_else(|| malformed("projects"))?;
    let limit = input["limit"].as_u64().unwrap_or(5) as usize;
    let ids: Vec<&Value> = projects
        .iter()
        .filter(|p| p["hasState"] != true && p["itemCount"].as_u64().unwrap_or(0) > 0)
        .map(|p| &p["projectId"])
        .take(limit)
        .collect();
    Ok(json!({ "projectIds": ids }))
}

#[cfg(test)]
#[path = "presentation_tests.rs"]
mod presentation_tests;
