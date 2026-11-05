//! Stateless sorting through the shared SDK comparator, without credentials.
use crate::BindingError;
use openmates_sdk::{Error, task_order::TaskOrder};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    locale: String,
    tasks: Vec<Value>,
}

/// Return a permutation for caller-owned rows, preserving foreign object identity.
/// Only the shared SDK chooses ordering. No profile, account or network is used.
pub fn sort_tasks_json(encoded: String) -> Result<String, BindingError> {
    let encoded = zeroize::Zeroizing::new(encoded);
    if encoded.len() > 1024 * 1024 {
        return Err(Error::Invalid("Task ordering input exceeds the supported size.").into());
    }
    let mut input: Input = serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed task ordering input."))?;
    let order = TaskOrder::try_new(&input.locale)?;
    // Choose a marker absent from every input object, so even arbitrary metadata
    // with a similar name cannot overwrite an identity or change tie ordering.
    let mut marker = "__openmates_task_order_index".to_owned();
    while input.tasks.iter().any(|row| row.get(&marker).is_some()) {
        marker.push('_');
    }
    for (index, row) in input.tasks.iter_mut().enumerate() {
        row.as_object_mut()
            .ok_or(Error::Invalid("Task ordering rows must be objects."))?
            .insert(marker.clone(), json!(index));
    }
    order.sort_tasks(&mut input.tasks)?;
    let indices = input
        .tasks
        .iter_mut()
        .map(|row| {
            row.as_object_mut()
                .and_then(|row| row.remove(&marker))
                .ok_or(Error::Protocol)
        })
        .collect::<Result<Vec<_>, _>>()?;
    serde_json::to_string(&json!({"indices":indices})).map_err(|_| Error::Protocol.into())
}

#[cfg(test)]
mod tests {
    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    use super::*;

    #[test]
    fn marker_collision_and_duplicate_rows_preserve_stable_indices() {
        let input = json!({"locale":"en","tasks":[{"title":"b","__openmates_task_order_index":99},{"title":"a"},{"title":"a"}]});
        let output = sort_tasks_json(input.to_string()).unwrap_or_else(|_| panic!("sort"));
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap(),
            json!({"indices":[1,2,0]})
        );
    }

    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    #[test]
    fn strict_configuration_and_rows_return_sanitized_errors() {
        for input in [
            json!({"locale":"en","tasks":[],"unknown":true}),
            json!({"locale":1,"tasks":[]}),
            json!({"locale":"en","tasks":[false]}),
            json!({"locale":"en","tasks":[{"position":true}]}),
            json!({"locale":"en","tasks":[{"title":3}]}),
            json!({"locale":"en","tasks":[{"source":3}]}),
        ] {
            assert_eq!(
                sort_tasks_json(input.to_string())
                    .err()
                    .map(|error| error.code),
                Some("invalid_argument")
            );
        }
    }

    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    #[cfg(feature = "napi-bindings")]
    #[test]
    fn napi_export_calls_the_shared_stateless_helper() {
        let output = crate::node::task_order(
            json!({"locale":"en","tasks":[{"title":"b"},{"title":"a"}]}).to_string(),
        )
        .unwrap_or_else(|_| panic!("native export"));
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap(),
            json!({"indices":[1,0]})
        );
    }
}
