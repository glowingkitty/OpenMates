//! Bounded schema-driven skill input. Builds only declared properties; never accepts raw JSON.
#[cfg(test)]
use super::Editor;
use super::{Field, FieldKind, Item};
use serde_json::{Value, json};
fn schema(item: &Item) -> Result<&Value, String> {
    item.fields
        .get("input_schema")
        .filter(|v| v.is_object())
        .ok_or("Skill input schema unavailable".into())
}
fn resolve<'a>(root: &'a Value, mut node: &'a Value) -> Result<&'a Value, String> {
    for _ in 0..12 {
        if let Some(reference) = node.get("$ref").and_then(Value::as_str) {
            let path = reference
                .strip_prefix('#')
                .ok_or("External schema references are unavailable in this terminal")?;
            node = root
                .pointer(path)
                .ok_or("Skill schema reference unavailable")?;
            continue;
        }
        if let Some(variants) = node
            .get("anyOf")
            .or_else(|| node.get("oneOf"))
            .and_then(Value::as_array)
        {
            let mut concrete = variants.iter().filter(|v| v["type"] != "null");
            let only = concrete
                .next()
                .ok_or("Skill schema has no supported value type")?;
            if concrete.next().is_some() {
                return Err(
                    "This skill requires a schema choice unavailable in the terminal".into(),
                );
            }
            node = only;
            continue;
        }
        if node.get("allOf").is_some()
            || node.get("patternProperties").is_some()
            || node.get("pattern").is_some()
            || node.get("if").is_some()
        {
            return Err("This skill uses schema constraints unavailable in the terminal".into());
        }
        return Ok(node);
    }
    Err("Skill schema references are recursive".into())
}
fn kind(node: &Value) -> &str {
    node["type"].as_str().unwrap_or_else(|| {
        if node.get("properties").is_some() {
            "object"
        } else if node.get("enum").is_some() || node.get("const").is_some() {
            "string"
        } else {
            "unsupported"
        }
    })
}
fn path(parent: &str, key: &str) -> String {
    format!("{parent}/{}", key.replace('~', "~0").replace('/', "~1"))
}
fn title(pointer: &str, node: &Value) -> String {
    let label = node["title"]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| {
            pointer
                .trim_start_matches('/')
                .replace("~1", "/")
                .replace("~0", "~")
                .replace('/', " › ")
                .replace('_', " ")
        });
    if let Some(description) = node["description"].as_str() {
        let short = description.split('\n').next().unwrap_or("");
        if !short.is_empty() && short.len() < 90 {
            return format!("{label} · {short}");
        }
    }
    label
}
fn text(value: &Value) -> String {
    value.as_str().map(str::to_owned).unwrap_or_else(|| {
        if value.is_null() {
            String::new()
        } else {
            value.to_string()
        }
    })
}
pub(super) fn controls(item: &Item) -> Result<Vec<Field>, String> {
    if item
        .fields
        .get("execution_available")
        .and_then(Value::as_bool)
        != Some(true)
    {
        return Err(item.fields["unavailable_reason"]
            .as_str()
            .unwrap_or("This skill cannot run in this terminal")
            .into());
    }
    let root = schema(item)?;
    let defaults = item.fields.get("defaults").unwrap_or(&Value::Null);
    let mut fields = vec![];
    build(root, root, "", true, defaults, 0, &mut fields)?;
    Ok(fields)
}
fn build(
    root: &Value,
    node: &Value,
    pointer: &str,
    required: bool,
    default: &Value,
    depth: usize,
    fields: &mut Vec<Field>,
) -> Result<(), String> {
    if depth > 8 || fields.len() > 96 {
        return Err("Skill input exceeds the native form size limit".into());
    }
    let outer_default = node.get("default");
    let node = resolve(root, node)?;
    let default = if default.is_null() {
        outer_default
            .or_else(|| node.get("default"))
            .unwrap_or(&Value::Null)
    } else {
        default
    };
    match kind(node) {
        "object" => {
            let properties = node["properties"]
                .as_object()
                .ok_or("Free-form object inputs are unavailable in the terminal")?;
            if let Some(required) = node["required"].as_array()
                && required
                    .iter()
                    .any(|key| key.as_str().is_none_or(|key| !properties.contains_key(key)))
            {
                return Err("Skill requires an undeclared property".into());
            }
            for (key, child) in properties {
                let child_required = node["required"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|v| v == key));
                build(
                    root,
                    child,
                    &path(pointer, key),
                    required && child_required,
                    default.get(key).unwrap_or(&Value::Null),
                    depth + 1,
                    fields,
                )?;
            }
        }
        "array" => {
            let items = resolve(
                root,
                node.get("items").ok_or("Array item schema unavailable")?,
            )?;
            if kind(items) == "object" {
                let defaults = default.as_array();
                let min = node["minItems"]
                    .as_u64()
                    .unwrap_or(if required { 1 } else { 0 }) as usize;
                let count = defaults.map_or(min.max(1), |v| v.len().max(min));
                if count > 20 {
                    return Err("Skill array requires more than 20 native rows".into());
                }
                for i in 0..count {
                    build(
                        root,
                        items,
                        &path(pointer, &i.to_string()),
                        required,
                        defaults.and_then(|v| v.get(i)).unwrap_or(&Value::Null),
                        depth + 1,
                        fields,
                    )?;
                }
            } else if matches!(kind(items), "string" | "number" | "integer" | "boolean") {
                let value = default
                    .as_array()
                    .map(|a| a.iter().map(text).collect::<Vec<_>>().join("\n"))
                    .unwrap_or_default();
                let mut field = Field::multiline(
                    pointer,
                    &format!("{} · one item per line", title(pointer, node)),
                    &value,
                );
                field.required = required;
                fields.push(field);
            } else {
                return Err("This skill uses nested arrays unavailable in the terminal".into());
            }
        }
        "string" | "number" | "integer" | "boolean" => {
            let label = title(pointer, node);
            let value = text(default);
            let mut field = Field::text(pointer, &label, &value, required);
            let enums = node
                .get("enum")
                .and_then(Value::as_array)
                .cloned()
                .or_else(|| node.get("const").map(|v| vec![v.clone()]));
            if let Some(enums) = enums {
                if enums.is_empty()
                    || enums
                        .iter()
                        .any(|v| !v.is_string() && !v.is_number() && !v.is_boolean())
                {
                    return Err("Skill enum values are unavailable in the terminal".into());
                }
                let options = enums.iter().map(text).collect();
                field.kind = FieldKind::Choice(options);
            } else {
                field.kind = match kind(node) {
                    "boolean" => {
                        FieldKind::Choice(vec![String::new(), "true".into(), "false".into()])
                    }
                    "number" | "integer" => FieldKind::Number,
                    _ => {
                        if pointer.ends_with("/prompt")
                            || pointer.ends_with("/query")
                            || pointer.ends_with("/body")
                            || pointer.ends_with("/text")
                        {
                            FieldKind::Multiline
                        } else {
                            FieldKind::Text
                        }
                    }
                };
            }
            if node["format"] == "password"
                || node["writeOnly"] == true
                || [
                    "password",
                    "secret",
                    "api_key",
                    "access_token",
                    "refresh_token",
                ]
                .contains(&pointer.rsplit('/').next().unwrap_or(""))
            {
                return Err("This skill requires a credential field unavailable in the terminal; configure its app settings first".into());
            }
            fields.push(field);
        }
        _ => {
            return Err(format!(
                "{} has an input type unavailable in the terminal",
                title(pointer, node)
            ));
        }
    }
    Ok(())
}
pub(super) fn input(item: &Item, fields: &[Field]) -> Result<Value, String> {
    let root = schema(item)?;
    let declared = controls(item)?;
    if fields
        .iter()
        .any(|field| !declared.iter().any(|allowed| allowed.key == field.key))
    {
        return Err("Skill form contains an undeclared field".into());
    }
    let result = parse(root, root, "", true, fields, 0)?.ok_or("Skill input is empty")?;
    if !result.is_object() {
        return Err("Skill input must be an object".into());
    }
    Ok(result)
}
fn parse(
    root: &Value,
    node: &Value,
    pointer: &str,
    required: bool,
    fields: &[Field],
    depth: usize,
) -> Result<Option<Value>, String> {
    if depth > 8 {
        return Err("Skill input nesting limit exceeded".into());
    }
    let node = resolve(root, node)?;
    match kind(node) {
        "object" => {
            if !required
                && !fields.iter().any(|field| {
                    field.key.starts_with(&format!("{pointer}/"))
                        && !field.editor.text.trim().is_empty()
                })
            {
                return Ok(None);
            }
            let mut output = serde_json::Map::new();
            for (key, child) in node["properties"]
                .as_object()
                .ok_or("Object schema unavailable")?
            {
                let child_required = node["required"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|v| v == key));
                if let Some(value) = parse(
                    root,
                    child,
                    &path(pointer, key),
                    child_required,
                    fields,
                    depth + 1,
                )? {
                    output.insert(key.clone(), value);
                }
            }
            if !required && output.is_empty() {
                Ok(None)
            } else {
                Ok(Some(Value::Object(output)))
            }
        }
        "array" => {
            let item = resolve(root, node.get("items").ok_or("Array schema unavailable")?)?;
            let mut values = vec![];
            if kind(item) == "object" {
                let prefix = format!("{pointer}/");
                let count = fields
                    .iter()
                    .filter_map(|f| {
                        f.key
                            .strip_prefix(&prefix)
                            .and_then(|s| s.split('/').next())
                            .and_then(|i| i.parse::<usize>().ok())
                    })
                    .max()
                    .map_or(0, |i| i + 1);
                for i in 0..count {
                    let row_pointer = path(pointer, &i.to_string());
                    let has_value = fields.iter().any(|f| {
                        f.key.starts_with(&format!("{row_pointer}/"))
                            && !f.editor.text.trim().is_empty()
                    });
                    if !has_value && !required {
                        continue;
                    }
                    if let Some(value) = parse(root, item, &row_pointer, true, fields, depth + 1)? {
                        values.push(value);
                    }
                }
            } else {
                let raw = fields
                    .iter()
                    .find(|f| f.key == pointer)
                    .map(|f| f.editor.text.as_str())
                    .unwrap_or("");
                for line in raw.lines().filter(|s| !s.trim().is_empty()) {
                    values.push(scalar(item, line, pointer)?);
                }
            }
            if values.is_empty() && !required {
                return Ok(None);
            }
            let min = node["minItems"]
                .as_u64()
                .unwrap_or(if required { 1 } else { 0 }) as usize;
            let max = node["maxItems"].as_u64().unwrap_or(20) as usize;
            if values.len() < min || values.len() > max {
                return Err(format!(
                    "{} requires {min}–{max} items",
                    title(pointer, node)
                ));
            }
            Ok(Some(Value::Array(values)))
        }
        _ => {
            let raw = fields
                .iter()
                .find(|f| f.key == pointer)
                .map(|f| f.editor.text.as_str())
                .unwrap_or("");
            if raw.trim().is_empty() {
                if required {
                    return Err(format!("{} is required", title(pointer, node)));
                }
                return Ok(None);
            }
            Ok(Some(scalar(node, raw, pointer)?))
        }
    }
}
fn scalar(node: &Value, raw: &str, pointer: &str) -> Result<Value, String> {
    let fail = |message: &str| format!("{}: {message}", title(pointer, node));
    let value = match kind(node) {
        "number" | "integer" => {
            let number = raw.parse::<f64>().map_err(|_| fail("enter a number"))?;
            if !number.is_finite() || (kind(node) == "integer" && number.fract() != 0.) {
                return Err(fail("enter a valid whole number"));
            }
            if node["minimum"].as_f64().is_some_and(|n| number < n)
                || node["maximum"].as_f64().is_some_and(|n| number > n)
                || node["exclusiveMinimum"]
                    .as_f64()
                    .is_some_and(|n| number <= n)
                || node["exclusiveMaximum"]
                    .as_f64()
                    .is_some_and(|n| number >= n)
            {
                return Err(fail("value outside the allowed range"));
            }
            if let Some(step) = node["multipleOf"].as_f64()
                && (step <= 0. || ((number / step) - (number / step).round()).abs() > 1e-7)
            {
                return Err(fail("value does not match the required step"));
            }
            if kind(node) == "integer" {
                json!(number as i64)
            } else {
                json!(number)
            }
        }
        "boolean" => match raw {
            "true" => json!(true),
            "false" => json!(false),
            _ => return Err(fail("choose true or false")),
        },
        "string" => {
            let length = raw.chars().count() as u64;
            if node["minLength"].as_u64().is_some_and(|n| length < n)
                || node["maxLength"].as_u64().is_some_and(|n| length > n)
            {
                return Err(fail("text length outside the allowed range"));
            }
            json!(raw)
        }
        _ => return Err(fail("unsupported value type")),
    };
    if let Some(enums) = node["enum"].as_array()
        && !enums.contains(&value)
    {
        return Err(fail("choose a declared option"));
    }
    if let Some(expected) = node.get("const")
        && expected != &value
    {
        return Err(fail("value must match the fixed option"));
    }
    Ok(value)
}
pub(super) fn identifiers(item: &Item) -> Result<(String, String), String> {
    let app = item.fields["app_id"]
        .as_str()
        .or_else(|| item.fields["app"].as_str())
        .ok_or("Skill app ID missing")?;
    let skill = item.fields["skill_id"]
        .as_str()
        .or_else(|| item.fields["skill"].as_str())
        .ok_or("Skill ID missing")?;
    if app.is_empty()
        || skill.is_empty()
        || app.len() > 100
        || skill.len() > 100
        || [app, skill].iter().any(|id| {
            id.chars()
                .any(|c| !c.is_ascii_alphanumeric() && !matches!(c, '_' | '-'))
        })
    {
        return Err("Skill identity is invalid".into());
    }
    Ok((app.into(), skill.into()))
}
pub(super) fn summary(item: &Item, input: &Value) -> String {
    let cost = item
        .fields
        .pointer("/pricing/fixed")
        .map(|v| format!("{v} credits per request"))
        .unwrap_or_else(|| "Credits may be charged".into());
    let mut text = format!("# {}\n\n{cost}\n\n", item.title);
    fn visit(value: &Value, label: &str, out: &mut String) {
        match value {
            Value::Object(values) => {
                for (key, value) in values {
                    visit(
                        value,
                        &if label.is_empty() {
                            key.clone()
                        } else {
                            format!("{label} › {key}")
                        },
                        out,
                    )
                }
            }
            Value::Array(values) => {
                for (i, value) in values.iter().enumerate() {
                    visit(value, &format!("{label} [{}]", i + 1), out)
                }
            }
            _ => out.push_str(&format!(
                "- **{label}:** {}\n",
                if super::sensitive_key(label) {
                    "[hidden]".to_owned()
                } else {
                    value
                        .as_str()
                        .map(str::to_owned)
                        .unwrap_or_else(|| value.to_string())
                }
            )),
        }
    }
    visit(input, "", &mut text);
    text
}

pub(super) fn result_rows(item: &Item, width: usize) -> Vec<super::markdown::Row> {
    use super::markdown::{self, Link, Part};
    use ratatui::style::Style;
    fn visit(
        value: &Value,
        width: usize,
        depth: usize,
        out: &mut Vec<markdown::Row>,
        count: &mut usize,
    ) {
        if depth > 7 || *count >= 200 {
            return;
        }
        match value {
            Value::Array(rows) => {
                for row in rows {
                    visit(row, width, depth + 1, out, count)
                }
            }
            Value::Object(object) => {
                let url = object
                    .get("url")
                    .or_else(|| object.get("link"))
                    .and_then(Value::as_str)
                    .filter(|url| url.starts_with("https://") || url.starts_with("http://"));
                let title = object
                    .get("title")
                    .or_else(|| object.get("name"))
                    .and_then(Value::as_str);
                if let (Some(url), Some(title)) = (url, title) {
                    *count += 1;
                    out.extend(markdown::wrap(
                        vec![Part {
                            text: markdown::clean(title),
                            style: Style::default().fg(super::BLUE).bold(),
                            link: Some(Link::Url(url.into())),
                        }],
                        width,
                    ));
                    for key in [
                        "description",
                        "snippet",
                        "text",
                        "start_time",
                        "end_time",
                        "address",
                        "latitude",
                        "longitude",
                    ] {
                        if let Some(value) =
                            object.get(key).filter(|v| v.is_string() || v.is_number())
                        {
                            out.extend(markdown::render(&text(value), width));
                        }
                    }
                    out.extend(markdown::wrap(
                        vec![Part {
                            text: markdown::clean(url),
                            style: Style::default().fg(super::MUTED),
                            link: Some(Link::Url(url.into())),
                        }],
                        width,
                    ));
                    out.push(vec![]);
                } else {
                    for key in ["results", "data", "items", "entries", "content"] {
                        if let Some(value) = object.get(key) {
                            visit(value, width, depth + 1, out, count);
                        }
                    }
                }
            }
            _ => {}
        }
    }
    let mut rows = vec![];
    let mut count = 0;
    visit(
        item.fields.get("content").unwrap_or(&item.fields),
        width.max(1),
        0,
        &mut rows,
        &mut count,
    );
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    fn skill(schema: Value) -> Item {
        Item {
            id: "skill:web/search".into(),
            title: "Search".into(),
            fields: json!({"app_id":"web","skill_id":"search","execution_available":true,"input_schema":schema}),
            ..Default::default()
        }
    }
    #[test]
    fn nested_web_request_is_typed_and_unknown_fields_never_pass() {
        let item = skill(
            json!({"type":"object","properties":{"requests":{"type":"array","items":{"type":"object","properties":{"query":{"type":"string"},"count":{"type":"integer","minimum":1,"maximum":20,"default":10},"filter":{"type":"boolean","default":true}},"required":["query"]}}},"required":["requests"]}),
        );
        let mut fields = controls(&item).unwrap();
        fields
            .iter_mut()
            .find(|f| f.key == "/requests/0/query")
            .unwrap()
            .editor = Editor::from("Rust");
        let value = input(&item, &fields).unwrap();
        assert_eq!(
            value,
            json!({"requests":[{"query":"Rust","count":10,"filter":true}]})
        );
        fields.push(Field::text("/secret", "Injected", "x", false));
        assert!(input(&item, &fields).is_err());
    }
    #[test]
    fn unsupported_union_is_honest_and_numeric_range_enforced() {
        let item = skill(
            json!({"type":"object","properties":{"value":{"oneOf":[{"type":"string"},{"type":"integer"}]}}}),
        );
        assert!(controls(&item).is_err());
        let item = skill(
            json!({"type":"object","properties":{"count":{"type":"integer","minimum":1,"maximum":5}},"required":["count"]}),
        );
        let mut fields = controls(&item).unwrap();
        for value in ["0", "6", "2.5"] {
            fields[0].editor = Editor::from(value);
            assert!(input(&item, &fields).is_err());
        }
        fields[0].editor = Editor::from("3");
        assert_eq!(input(&item, &fields).unwrap(), json!({"count":3}));
    }
}
