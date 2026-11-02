//! Shared interactive-question wire semantics expressed as native typed form controls.
use super::{Field, FieldKind};
use serde_json::{Value, json};
pub(super) fn fields(question: &Value) -> Result<Vec<Field>, String> {
    let mut fields = vec![];
    let id = question["id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("Question ID missing")?;
    let _ = id;
    match question["type"].as_str().unwrap_or("") {
        "input" => {
            for value in question["fields"]
                .as_array()
                .ok_or("Question fields missing")?
            {
                let id = value["id"].as_str().ok_or("Input ID missing")?;
                let label = value["label"].as_str().unwrap_or(id);
                fields.push(Field::text(id, label, "", value["required"] == true));
            }
        }
        "choice" => {
            let options = question["options"]
                .as_array()
                .ok_or("Question options missing")?;
            if question["multiple"] == true {
                for option in options {
                    let id = option["id"].as_str().ok_or("Option ID missing")?;
                    let label = option["text"].as_str().unwrap_or(id);
                    let mut field = Field::text(id, label, "false", false);
                    field.kind = FieldKind::Bool;
                    fields.push(field);
                }
            } else {
                let labels = options
                    .iter()
                    .map(|o| o["text"].as_str().unwrap_or("").to_owned())
                    .collect::<Vec<_>>();
                let mut field = Field::choice(
                    "selection",
                    question["question"].as_str().unwrap_or("Choose one"),
                    "",
                    labels,
                );
                field.editor = super::Editor::default();
                fields.push(field);
            }
            if question.get("custom_option_id").is_some()
                || options.iter().any(|o| is_custom(question, o))
            {
                fields.push(Field::text(
                    "custom_answer",
                    question["custom_placeholder"]
                        .as_str()
                        .unwrap_or("Custom answer (if selected)"),
                    "",
                    false,
                ));
            }
        }
        "slider" => {
            let mut field = Field::text(
                "value",
                question["question"].as_str().unwrap_or("Choose value"),
                &question
                    .get("default")
                    .map(Value::to_string)
                    .unwrap_or_default(),
                true,
            );
            field.kind = FieldKind::Number;
            fields.push(field);
        }
        "rating" => {
            let max = rating_max(question);
            let mut field = Field::text("rating", &format!("Rating (1–{max})"), "", true);
            field.kind = FieldKind::Number;
            fields.push(field);
            fields.push(Field::text(
                "comment",
                question["comment_placeholder"]
                    .as_str()
                    .unwrap_or("Comment"),
                "",
                question["require_comment"] == true,
            ));
        }
        "swipe" => {
            for card in question["cards"]
                .as_array()
                .ok_or("Question cards missing")?
            {
                let id = card["id"].as_str().ok_or("Card ID missing")?;
                fields.push(Field::choice(
                    id,
                    card["text"].as_str().unwrap_or(id),
                    "",
                    vec!["like".into(), "dislike".into()],
                ));
            }
        }
        _ => return Err("Unsupported interactive question type".into()),
    }
    if fields.is_empty() {
        return Err("Question has no controls".into());
    }
    Ok(fields)
}
fn is_custom(question: &Value, option: &Value) -> bool {
    if let Some(custom) = question["custom_option_id"].as_str() {
        return option["id"].as_str() == Some(custom);
    }
    let text = option["text"].as_str().unwrap_or("").to_lowercase();
    [
        "my own answer",
        "own answer",
        "custom answer",
        "something else",
        "other",
    ]
    .iter()
    .any(|word| text.contains(word))
}
fn rating_max(question: &Value) -> i64 {
    question
        .get("max_stars")
        .or_else(|| question.get("max"))
        .or_else(|| question.get("scale"))
        .and_then(Value::as_i64)
        .unwrap_or(5)
}
pub(super) fn response(question: &Value, fields: &[Field]) -> Result<String, String> {
    let get = |key: &str| {
        fields
            .iter()
            .find(|f| f.key == key)
            .map(|f| f.editor.text.as_str())
            .unwrap_or("")
    };
    let mut response = json!({"id":question["id"]});

    let display = match question["type"].as_str().unwrap_or("") {
        "input" => {
            let mut values = serde_json::Map::new();
            let mut labels = vec![];
            for field in fields {
                if field.required && field.editor.text.trim().is_empty() {
                    return Err(format!("{} is required", field.label));
                }
                values.insert(field.key.clone(), json!(field.editor.text.as_str()));
                if !field.editor.text.is_empty() {
                    labels.push(field.editor.text.to_string());
                }
            }
            response["inputs"] = Value::Object(values);
            labels.join("\n")
        }
        "choice" => {
            let options = question["options"]
                .as_array()
                .ok_or("Question options missing")?;
            let multiple = question["multiple"] == true;
            let selected = options
                .iter()
                .filter(|o| {
                    if multiple {
                        get(o["id"].as_str().unwrap_or("")) == "true"
                    } else {
                        get("selection") == o["text"].as_str().unwrap_or("")
                    }
                })
                .collect::<Vec<_>>();
            if selected.is_empty() {
                return Err("Select an option".into());
            }
            let custom = get("custom_answer").trim();
            if selected.iter().any(|o| is_custom(question, o)) && custom.is_empty() {
                return Err("Enter a custom answer".into());
            }
            response["selection"] = json!(
                selected
                    .iter()
                    .filter_map(|o| o["id"].as_str())
                    .collect::<Vec<_>>()
            );
            if !custom.is_empty() && selected.iter().any(|o| is_custom(question, o)) {
                response["custom_answer"] = json!(custom);
            }
            let embeds = selected
                .iter()
                .flat_map(|o| {
                    o.get("embed_ids")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_else(|| {
                            o.get("embed_id")
                                .map(|id| vec![id.clone()])
                                .unwrap_or_default()
                        })
                })
                .collect::<Vec<_>>();
            if !embeds.is_empty() {
                response["embed_ids"] = json!(embeds);
            }
            selected
                .iter()
                .map(|o| {
                    if is_custom(question, o) && !custom.is_empty() {
                        custom
                    } else {
                        o["text"].as_str().unwrap_or("")
                    }
                })
                .collect::<Vec<_>>()
                .join("\n")
        }
        "slider" => {
            let value = get("value")
                .parse::<f64>()
                .map_err(|_| "Choose a numeric value")?;
            let min = question["min"].as_f64().ok_or("Slider minimum missing")?;
            let max = question["max"].as_f64().ok_or("Slider maximum missing")?;
            let step = question["step"].as_f64().unwrap_or(1.);
            let offset = (value - min) / step;
            if !value.is_finite()
                || step <= 0.
                || value < min
                || value > max
                || (offset - offset.round()).abs() > 1e-7
            {
                return Err(format!(
                    "Choose a value from {min} to {max}, in steps of {step}"
                ));
            }
            response["value"] = json!(value);
            value.to_string()
        }
        "rating" => {
            let value = get("rating")
                .parse::<i64>()
                .map_err(|_| "Choose a whole-number rating")?;
            let max = rating_max(question);
            if value < 1 || value > max {
                return Err(format!("Choose a rating from 1 to {max}"));
            }
            response["rating"] = json!(value);
            let comment = get("comment").trim();
            if question["require_comment"] == true && comment.is_empty() {
                return Err("Enter a comment".into());
            }
            if !comment.is_empty() {
                response["comment"] = json!(comment);
            }
            format!(
                "{value}/{max}{}",
                if comment.is_empty() {
                    String::new()
                } else {
                    format!("\n{comment}")
                }
            )
        }
        "swipe" => {
            let mut swipes = serde_json::Map::new();
            let mut labels = vec![];
            for card in question["cards"]
                .as_array()
                .ok_or("Question cards missing")?
            {
                let id = card["id"].as_str().ok_or("Card ID missing")?;
                let value = get(id);
                if !["like", "dislike"].contains(&value) {
                    return Err("Review every card".into());
                }
                swipes.insert(id.into(), json!(value));
                labels.push(format!("{}: {value}", card["text"].as_str().unwrap_or(id)));
            }
            response["swipes"] = Value::Object(swipes);
            labels.join("\n")
        }
        _ => return Err("Unsupported interactive question".into()),
    };
    Ok(format!(
        "{display}\n\n```interactive_response\n{}\n```",
        serde_json::to_string_pretty(&response).map_err(|_| "Invalid answer")?
    ))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn choice_uses_option_ids_and_explicit_custom_validation() {
        let q = json!({"id":"q1","type":"choice","question":"Pick","options":[{"id":"a","text":"A"},{"id":"other","text":"Other"}],"custom_option_id":"other"});
        let mut f = fields(&q).unwrap();
        assert!(response(&q, &f).is_err());
        f[0].editor = super::super::Editor::from("Other");
        assert!(response(&q, &f).is_err());
        f[1].editor = super::super::Editor::from("Custom");
        let text = response(&q, &f).unwrap();
        assert!(text.contains("\"selection\": [\n    \"other\""));
        assert!(!text.contains("question_id"));
    }
    #[test]
    fn slider_rejects_out_of_range_and_step() {
        let q = json!({"id":"q2","type":"slider","question":"Amount","min":0,"max":10,"step":2});
        let mut f = fields(&q).unwrap();
        for v in ["11", "3", "NaN"] {
            f[0].editor = super::super::Editor::from(v);
            assert!(response(&q, &f).is_err());
        }
        f[0].editor = super::super::Editor::from("4");
        assert!(response(&q, &f).unwrap().contains("\"value\": 4.0"));
    }
}
