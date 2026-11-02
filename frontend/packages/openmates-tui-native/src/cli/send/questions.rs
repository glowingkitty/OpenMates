//! Native interactive-response encoding shared by scripted chat answers.
//! Mirrors the existing interactiveQuestions.ts protocol; no inference routing.
use crate::cli::CliError;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use zeroize::Zeroizing;

fn nonempty(value: &Value) -> bool {
    value.as_str().is_some_and(|value| !value.trim().is_empty())
}
fn invalid() -> CliError {
    CliError::Invalid("Invalid interactive question or answer.".into())
}
pub(super) fn parse(content: &str) -> Option<Value> {
    let block = regex::Regex::new(r"```interactive_question\s*\n([\s\S]*?)\n```")
        .expect("constant interactive question syntax");
    let captures = block.captures(content)?;
    let question: Value = serde_json::from_str(captures.get(1)?.as_str()).ok()?;
    valid(&question).then_some(question)
}
fn valid_options(value: &Value) -> bool {
    let Some(options) = value.as_array().filter(|values| !values.is_empty()) else {
        return false;
    };
    let mut ids = BTreeSet::new();
    options.iter().all(|option| {
        nonempty(&option["id"])
            && ids.insert(option["id"].as_str().unwrap())
            && option["text"].is_string()
            && option.get("embed_id").is_none_or(nonempty)
            && option.get("embed_ids").is_none_or(|value| {
                value
                    .as_array()
                    .is_some_and(|values| values.iter().all(nonempty))
            })
    })
}
pub(super) fn valid(question: &Value) -> bool {
    if !nonempty(&question["id"])
        || ["question", "custom_placeholder", "comment_placeholder"]
            .iter()
            .any(|key| question.get(key).is_some_and(|value| !value.is_string()))
    {
        return false;
    }
    match question["type"].as_str() {
        Some("choice") => {
            nonempty(&question["question"])
                && valid_options(&question["options"])
                && question.get("multiple").is_none_or(Value::is_boolean)
                && question.get("custom_option_id").is_none_or(|id| {
                    nonempty(id)
                        && question["options"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .any(|option| option["id"] == *id)
                })
        }
        Some("input") => {
            let Some(fields) = question["fields"]
                .as_array()
                .filter(|values| !values.is_empty())
            else {
                return false;
            };
            let mut ids = BTreeSet::new();
            fields.iter().all(|field| {
                nonempty(&field["id"])
                    && ids.insert(field["id"].as_str().unwrap())
                    && field["label"].is_string()
                    && field.get("required").is_none_or(Value::is_boolean)
            })
        }
        Some("slider") => {
            let (Some(min), Some(max)) = (question["min"].as_f64(), question["max"].as_f64())
            else {
                return false;
            };
            nonempty(&question["question"])
                && min <= max
                && question
                    .get("step")
                    .is_none_or(|value| value.as_f64().is_some_and(|step| step > 0.0))
                && question.get("default").is_none_or(|value| {
                    value
                        .as_f64()
                        .is_some_and(|value| value >= min && value <= max)
                })
                && question.get("labels").is_none_or(|value| {
                    value
                        .as_object()
                        .is_some_and(|labels| labels.values().all(Value::is_string))
                })
        }
        Some("swipe") => valid_options(&question["cards"]),
        Some("rating") => {
            nonempty(&question["question"])
                && integer(&rating_max(question)).is_some_and(|max| max > 0)
                && question
                    .get("require_comment")
                    .is_none_or(Value::is_boolean)
        }
        _ => false,
    }
}
fn rating_max(question: &Value) -> Value {
    ["max_stars", "max", "scale"]
        .iter()
        .find_map(|key| question.get(key).filter(|value| !value.is_null()))
        .cloned()
        .unwrap_or(json!(5))
}
fn integer(value: &Value) -> Option<u64> {
    value
        .as_f64()
        .filter(|value| *value >= 0.0 && value.fract() == 0.0 && *value < u64::MAX as f64)
        .map(|value| value as u64)
}
fn custom(question: &Value, option: &Value) -> bool {
    if let Some(id) = question.get("custom_option_id") {
        return *id == option["id"];
    }
    let text = option["text"].as_str().unwrap_or("").trim().to_lowercase();
    [
        "i give you my own answer",
        "my own answer",
        "own answer",
        "custom answer",
        "something else",
        "other",
    ]
    .iter()
    .any(|value| text.contains(value))
}
fn refs(options: &[Value]) -> Vec<String> {
    let mut seen = BTreeSet::new();
    options
        .iter()
        .flat_map(|option| {
            option["embed_ids"]
                .as_array()
                .cloned()
                .unwrap_or_else(|| option.get("embed_id").cloned().into_iter().collect())
        })
        .filter_map(|value| {
            value
                .as_str()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
        })
        .filter(|value| seen.insert(value.clone()))
        .collect()
}
pub(super) fn answer(question: &Value, answer: &Value) -> Result<Zeroizing<String>, CliError> {
    if !valid(question) || !answer.is_object() {
        return Err(invalid());
    }
    let mut payload = json!({"id":question["id"]});
    let display = match question["type"].as_str().unwrap() {
        "choice" => {
            let selected = answer["selection"]
                .as_array()
                .filter(|values| !values.is_empty())
                .ok_or_else(invalid)?;
            let mut ids = BTreeSet::new();
            let options = question["options"].as_array().unwrap();
            if selected.iter().any(|id| {
                !nonempty(id)
                    || !ids.insert(id.as_str().unwrap())
                    || !options.iter().any(|option| option["id"] == *id)
            }) || (question["multiple"] != true && selected.len() != 1)
            {
                return Err(invalid());
            }
            let options = options
                .iter()
                .filter(|option| selected.contains(&option["id"]))
                .cloned()
                .collect::<Vec<_>>();
            let custom_text = answer["custom_answer"].as_str().unwrap_or("").trim();
            let uses_custom = options.iter().any(|option| custom(question, option));
            if uses_custom && custom_text.is_empty() {
                return Err(CliError::Invalid("Enter a custom answer.".into()));
            }
            payload["selection"] = json!(selected);
            if uses_custom {
                payload["custom_answer"] = json!(custom_text);
            }
            let refs = refs(&options);
            if !refs.is_empty() {
                payload["embed_ids"] = json!(refs);
            }
            options
                .iter()
                .map(|option| {
                    if custom(question, option) {
                        custom_text
                    } else {
                        option["text"].as_str().unwrap()
                    }
                })
                .collect::<Vec<_>>()
                .join("\n")
        }
        "input" => {
            let source = answer
                .get("inputs")
                .filter(|value| value.is_object())
                .or_else(|| answer.get("values").filter(|value| value.is_object()))
                .unwrap_or(answer);
            let mut inputs = serde_json::Map::new();
            let mut texts = vec![];
            for field in question["fields"].as_array().unwrap() {
                let id = field["id"].as_str().unwrap();
                if source.get(id).is_some_and(|value| !value.is_string())
                    || (field["required"] == true && !nonempty(&source[id]))
                {
                    return Err(invalid());
                }
                let text = source[id].as_str().unwrap_or("");
                inputs.insert(id.into(), json!(text));
                if !text.is_empty() {
                    texts.push(text);
                }
            }
            payload["inputs"] = inputs.into();
            texts.join("\n")
        }
        "slider" => {
            let value = answer["value"].as_f64().ok_or_else(invalid)?;
            let min = question["min"].as_f64().unwrap();
            let max = question["max"].as_f64().unwrap();
            let step = question["step"].as_f64().unwrap_or(1.0);
            let offset = (value - min) / step;
            if value < min || value > max || (offset - offset.round()).abs() > 1e-7 {
                return Err(invalid());
            }
            payload["value"] = answer["value"].clone();
            let number = number_text(&answer["value"]);
            question["labels"][&number]
                .as_str()
                .filter(|label| !label.is_empty())
                .map(|label| format!("{number} ({label})"))
                .unwrap_or(number)
        }
        "swipe" => {
            let cards = question["cards"].as_array().unwrap();
            let mut swipes = answer["swipes"].as_object().cloned().unwrap_or_else(|| {
                let mut values = serde_json::Map::new();
                for (key, action) in [("liked", "like"), ("disliked", "dislike")] {
                    for id in answer[key]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                    {
                        values.insert(id.into(), json!(action));
                    }
                }
                values
            });
            if swipes.len() != cards.len()
                || cards.iter().any(|card| {
                    !matches!(
                        swipes
                            .get(card["id"].as_str().unwrap())
                            .and_then(Value::as_str),
                        Some("like" | "dislike")
                    )
                })
            {
                return Err(invalid());
            }
            let display = cards
                .iter()
                .map(|card| {
                    format!(
                        "{}: {}",
                        card["text"].as_str().unwrap(),
                        swipes[card["id"].as_str().unwrap()].as_str().unwrap()
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            payload["swipes"] = Value::Object(std::mem::take(&mut swipes));
            let refs = refs(cards);
            if !refs.is_empty() {
                payload["embed_ids"] = json!(refs);
            }
            display
        }
        "rating" => {
            let max = integer(&rating_max(question)).unwrap();
            let rating = integer(&answer["rating"])
                .filter(|rating| *rating > 0 && *rating <= max)
                .ok_or_else(invalid)?;
            if answer
                .get("comment")
                .is_some_and(|value| !value.is_string())
            {
                return Err(invalid());
            }
            let comment = answer["comment"].as_str().unwrap_or("").trim();
            if question["require_comment"] == true && comment.is_empty() {
                return Err(invalid());
            }
            payload["rating"] = json!(rating);
            if !comment.is_empty() {
                payload["comment"] = json!(comment);
            }
            format!(
                "{rating}/{max}{}",
                if comment.is_empty() {
                    String::new()
                } else {
                    format!("\n{comment}")
                }
            )
        }
        _ => unreachable!(),
    };
    let encoded = serde_json::to_string_pretty(&payload).map_err(|_| invalid())?;
    Ok(Zeroizing::new(format!(
        "{display}\n\n```interactive_response\n{encoded}\n```"
    )))
}
fn number_text(value: &Value) -> String {
    let value = value.as_f64().unwrap();
    if value == 0.0 {
        "0".into()
    } else if value.fract() == 0.0 {
        format!("{value:.0}")
    } else {
        value.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn choices_preserve_question_order_custom_text_and_only_selected_embed_refs() {
        let q = json!({"id":"q","type":"choice","question":"Choose","multiple":true,"options":[{"id":"a","text":"First","embed_ids":["one","one"]},{"id":"other","text":"Other"},{"id":"b","text":"Third","embed_id":"private-unselected"}]});
        let text = answer(
            &q,
            &json!({"selection":["other","a"],"custom_answer":"  custom 界  "}),
        )
        .unwrap_or_else(|error| panic!("{error}"));
        assert!(text.starts_with("First\ncustom 界\n\n```interactive_response"));
        let payload: Value = serde_json::from_str(
            text.split("```interactive_response\n")
                .nth(1)
                .unwrap()
                .trim_end_matches("\n```"),
        )
        .unwrap();
        assert_eq!(payload["selection"], json!(["other", "a"]));
        assert_eq!(payload["embed_ids"], json!(["one"]));
        assert!(!text.contains("private-unselected"));
        for a in [
            json!({"selection":["a","a"]}),
            json!({"selection":["unknown"]}),
            json!({"selection":["other"]}),
        ] {
            assert!(answer(&q, &a).is_err());
        }
    }
    #[test]
    fn slider_rating_input_and_swipe_enforce_the_original_constraints() {
        let slider = json!({"type":"slider","id":"s","question":"Scale","min":0,"max":2,"step":0.5,"labels":{"1":"middle"}});
        assert!(
            answer(&slider, &json!({"value":1}))
                .unwrap_or_else(|e| panic!("{e}"))
                .starts_with("1 (middle)")
        );
        assert!(answer(&slider, &json!({"value":0.4})).is_err());
        let rating = json!({"type":"rating","id":"r","question":"Rate","max_stars":3,"require_comment":true});
        assert!(
            answer(&rating, &json!({"rating":3,"comment":" great "}))
                .unwrap_or_else(|e| panic!("{e}"))
                .starts_with("3/3\ngreat")
        );
        assert!(answer(&rating, &json!({"rating":3})).is_err());
        assert!(answer(&rating, &json!({"rating":3.0,"comment":"yes"})).is_ok());
        let input = json!({"type":"input","id":"i","fields":[{"id":"required","label":"Name","required":true},{"id":"optional","label":"Note"}]});
        assert!(
            answer(&input, &json!({"values":{"required":"私"}}))
                .unwrap_or_else(|e| panic!("{e}"))
                .starts_with("私\n\n")
        );
        assert!(answer(&input, &json!({"inputs":{"required":"  "}})).is_err());
        let swipe =
            json!({"type":"swipe","id":"w","cards":[{"id":"a","text":"A"},{"id":"b","text":"B"}]});
        assert!(
            answer(&swipe, &json!({"liked":["a"],"disliked":["b"]}))
                .unwrap_or_else(|e| panic!("{e}"))
                .starts_with("A: like\nB: dislike")
        );
        assert!(answer(&swipe, &json!({"swipes":{"a":"like"}})).is_err());
    }
}
