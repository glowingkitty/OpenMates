//! Stable presentation ordering shared by native and foreign hosts.
//!
//! Credentials, account scope, filtering, and wire pagination are unchanged.
//! The host supplies its BCP47 locale explicitly; this module never discovers
//! environment variables, installed CLI state, or operating-system preferences.
//! ICU4X/data are pinned by Cargo.lock. Equality across arbitrary ICU/CLDR
//! versions is not promised; qualified compatibility vectors record the oracle.
use crate::{Error, Result, model::Item};
use icu_collator::{Collator, CollatorBorrowed, options::CollatorOptions};
use icu_locale_core::Locale;
use serde_json::Value;
use std::cmp::Ordering;

/// Locale-aware Task board ordering, with stable ties and no ID tie breaker.
pub struct TaskOrder {
    collator: CollatorBorrowed<'static>,
}
impl TaskOrder {
    /// Construct the default sort/variant collator for an explicit BCP47 locale.
    /// Unicode locale keywords and supported locale fallback follow ICU4X.
    pub fn try_new(locale: &str) -> Result<Self> {
        if locale.is_empty() || locale.len() > 512 || locale.contains('_') {
            return Err(Error::Invalid(
                "Supply a valid explicit Task collation locale.",
            ));
        }
        let locale: Locale = locale
            .parse()
            .map_err(|_| Error::Invalid("Supply a valid BCP47 Task collation locale."))?;
        let collator = Collator::try_new(locale.into(), CollatorOptions::default())
            .map_err(|_| Error::Invalid("Task collation data is unavailable for this locale."))?;
        Ok(Self { collator })
    }

    /// Sort decoded Task JSON rows, preserving every row and unknown metadata.
    /// Missing/null positions are zero. Finite JSON numbers use JavaScript
    /// Number semantics, including fractions, large values and -0 == 0.
    /// Missing/empty titles use the canonical Task/projection display fallback
    /// for comparison only; the caller's row remains unchanged.
    /// Invalid typed fields fail before any row is moved.
    pub fn sort_tasks(&self, tasks: &mut [Value]) -> Result<()> {
        let keys = tasks
            .iter()
            .map(|task| {
                let object = task
                    .as_object()
                    .ok_or(Error::Invalid("Task ordering requires object rows."))?;
                Ok((
                    position(object.get("position"))?,
                    title(object.get("title"), object.get("source"))?,
                ))
            })
            .collect::<Result<Vec<_>>>()?;
        let order = self.permutation(&keys);
        reorder(tasks, &order);
        Ok(())
    }

    /// Sort native Task items using the same policy as decoded JSON rows.
    pub fn sort_items(&self, tasks: &mut [Item]) -> Result<()> {
        let keys = tasks
            .iter()
            .map(|task| Ok((position(task.fields.get("position"))?, item_title(task)?)))
            .collect::<Result<Vec<_>>>()?;
        let order = self.permutation(&keys);
        reorder(tasks, &order);
        Ok(())
    }

    fn permutation(&self, keys: &[(f64, &str)]) -> Vec<usize> {
        let mut order = (0..keys.len()).collect::<Vec<_>>();
        order.sort_by(|a, b| {
            let (a, b) = (keys[*a], keys[*b]);
            if a.0 < b.0 {
                Ordering::Less
            } else if a.0 > b.0 {
                Ordering::Greater
            } else {
                self.collator.compare(a.1, b.1)
            }
        });
        order
    }
}
fn position(value: Option<&Value>) -> Result<f64> {
    match value {
        None | Some(Value::Null) => Ok(0.0),
        Some(Value::Number(number)) => {
            number
                .as_f64()
                .filter(|n| n.is_finite())
                .ok_or(Error::Invalid(
                    "Task position must be a finite JSON number.",
                ))
        }
        _ => Err(Error::Invalid(
            "Task position must be a finite JSON number or null.",
        )),
    }
}
fn title<'a>(value: Option<&'a Value>, source: Option<&Value>) -> Result<&'a str> {
    let projected = match source {
        None | Some(Value::Null) => false,
        Some(Value::String(source)) => source == "workflow_run",
        _ => return Err(Error::Invalid("Task source must be a string or null.")),
    };
    match value {
        Some(Value::String(value)) if !value.is_empty() => Ok(value),
        None | Some(Value::Null) | Some(Value::String(_)) => Ok(if projected {
            "Workflow run"
        } else {
            "(untitled task)"
        }),
        _ => Err(Error::Invalid("Task title must be a string or null.")),
    }
}
fn item_title(task: &Item) -> Result<&str> {
    let source = task.fields.get("source");
    if source.is_some_and(|v| !v.is_null() && !v.is_string()) {
        return Err(Error::Invalid("Task source must be a string or null."));
    }
    Ok(if !task.title.is_empty() {
        &task.title
    } else if source.and_then(Value::as_str) == Some("workflow_run") {
        "Workflow run"
    } else {
        "(untitled task)"
    })
}
fn reorder<T>(rows: &mut [T], order: &[usize]) {
    let mut destinations = vec![0; order.len()];
    for (destination, original) in order.iter().enumerate() {
        destinations[*original] = destination;
    }
    for index in 0..destinations.len() {
        while destinations[index] != index {
            let destination = destinations[index];
            rows.swap(index, destination);
            destinations.swap(index, destination);
        }
    }
}

#[cfg(test)]
mod tests;
