//! Validates the versioned Design scene in the shared core before projection.
//! Phase 0's Canvas renderer supplies the geometry conventions. Saved scenes
//! carry document-owned asset identifiers and bounded vector geometry.

use std::collections::HashSet;

use serde_json::{Value, json};

use super::plaintext::Plain;
use crate::error::{Error, Result};

pub(super) const EMBED_TYPE: &str = "design-document";
const MAX_SCENE_BYTES: usize = 1024 * 1024;
const MAX_PAGES: usize = 16;
const MAX_LAYERS_PER_PAGE: usize = 250;
const MAX_DIMENSION: f64 = 4096.0;

const INVALID_SCENE: Error = Error::Invalid("Malformed Design scene.");
const UNSUPPORTED_VERSION: Error = Error::Invalid("Unsupported Design scene version.");

/// Parses only the canonical JSON wire format. Rejected plaintext is wiped
/// before returning and errors never include values from the scene.
pub(super) fn decode(input: &str) -> Result<Plain<Value>> {
    if input.len() > MAX_SCENE_BYTES {
        return Err(INVALID_SCENE);
    }
    let scene = Plain::new(serde_json::from_str::<Value>(input).map_err(|_| INVALID_SCENE)?);
    if scene["schemaVersion"].as_u64() != Some(1) {
        return Err(UNSUPPORTED_VERSION);
    }
    fields(&scene, &["schemaVersion", "title", "pages"], &["proposal"])?;
    if let Some(proposal) = scene.get("proposal") {
        fields(proposal, &["embedId", "baseVersion"], &[])?;
        canonical_uuid(&proposal["embedId"])?;
        if !proposal["baseVersion"]
            .as_u64()
            .is_some_and(|version| version > 0 && version <= u64::from(u32::MAX))
        {
            return Err(INVALID_SCENE);
        }
    }
    bounded_text(&scene["title"], 256)?;
    let pages = scene["pages"].as_array().ok_or(INVALID_SCENE)?;
    if !(1..=MAX_PAGES).contains(&pages.len()) {
        return Err(INVALID_SCENE);
    }
    let mut page_ids = HashSet::new();
    for page in pages {
        check_page(page, &mut page_ids)?;
    }
    Ok(scene)
}

/// The single explicit Design attachment selected by a composer.
pub(super) fn turn_reference(markdown: &str) -> Option<Plain<Value>> {
    let mut references = Vec::new();
    super::chat_files::for_fenced_json(markdown, |range, body| {
        if body.len() > 360 || references.len() > 1 {
            return;
        }
        let Ok(data) = serde_json::from_str::<Value>(body) else {
            return;
        };
        if data["type"] != EMBED_TYPE
            || fields(&data, &["type", "embed_id"], &["reference_only"]).is_err()
            || canonical_uuid(&data["embed_id"]).is_err()
        {
            return;
        }
        references.push((
            range,
            data["embed_id"].as_str().unwrap_or_default().to_owned(),
        ));
    });
    if references.len() != 1 {
        return None;
    }
    let (range, id) = references.pop()?;
    let mut text = Plain::new(markdown.to_owned());
    text.replace_range(range, "");
    Some(Plain::new(json!({"embedId": id, "text": &*text})))
}

/// Bound and validate the explicitly disclosed scene for the private context phase.
pub(super) fn source_context(
    content: &str,
    embed_id: &str,
    base_version: u32,
) -> Result<Plain<Value>> {
    const SOURCE_LIMIT: usize = 127_000;
    if base_version == 0 || content.len() > SOURCE_LIMIT {
        return Err(INVALID_SCENE);
    }
    let id = Value::String(embed_id.to_owned());
    canonical_uuid(&id)?;
    let scene = decode(content)?;
    if scene.get("proposal").is_some() {
        return Err(INVALID_SCENE);
    }
    Ok(Plain::new(
        json!({"embed_id": id, "base_version": base_version, "scene": &*scene}),
    ))
}

fn canonical_uuid(value: &Value) -> Result<()> {
    let reference = value.as_str().ok_or(INVALID_SCENE)?;
    let uuid = uuid::Uuid::parse_str(reference).map_err(|_| INVALID_SCENE)?;
    if uuid.is_nil() || uuid.hyphenated().to_string() != reference {
        return Err(INVALID_SCENE);
    }
    Ok(())
}

fn check_page<'a>(page: &'a Value, ids: &mut HashSet<&'a str>) -> Result<()> {
    fields(
        page,
        &["id", "name", "width", "height", "background", "layers"],
        &[],
    )?;
    unique_id(&page["id"], ids)?;
    bounded_text(&page["name"], 256)?;
    for key in ["width", "height"] {
        number(&page[key], 1.0, MAX_DIMENSION)?;
    }
    color(&page["background"])?;
    let layers = page["layers"].as_array().ok_or(INVALID_SCENE)?;
    if layers.len() > MAX_LAYERS_PER_PAGE {
        return Err(INVALID_SCENE);
    }
    let mut layer_ids = HashSet::new();
    for layer in layers {
        check_layer(layer, &mut layer_ids)?;
    }
    Ok(())
}

fn check_layer<'a>(layer: &'a Value, ids: &mut HashSet<&'a str>) -> Result<()> {
    let base = [
        "kind", "id", "name", "x", "y", "width", "height", "rotation",
    ];
    let common_optional = ["hidden", "locked"];
    let kind = layer["kind"].as_str().ok_or(INVALID_SCENE)?;
    let (payload, extra_optional): (&[&str], &[&str]) = match kind {
        "shape" => (&["shape", "color"], &["radius"]),
        "text" => (&["text", "font", "fontSize", "weight", "color"], &[]),
        "image" => (&["assetId"], &[]),
        "path" => (&["path", "viewWidth", "viewHeight", "color"], &[]),
        _ => return Err(INVALID_SCENE),
    };
    let required: Vec<_> = base.into_iter().chain(payload.iter().copied()).collect();
    let optional: Vec<_> = common_optional
        .into_iter()
        .chain(extra_optional.iter().copied())
        .collect();
    fields(layer, &required, &optional)?;
    unique_id(&layer["id"], ids)?;
    bounded_text(&layer["name"], 256)?;
    for key in ["hidden", "locked"] {
        if layer.get(key).is_some_and(|value| !value.is_boolean()) {
            return Err(INVALID_SCENE);
        }
    }
    for key in ["x", "y"] {
        number(&layer[key], -MAX_DIMENSION, MAX_DIMENSION)?;
    }
    for key in ["width", "height"] {
        number(&layer[key], 1.0, MAX_DIMENSION)?;
    }
    number(&layer["rotation"], -360.0, 360.0)?;
    if kind != "image" {
        color(&layer["color"])?;
    }
    match kind {
        "shape" => {
            if !matches!(layer["shape"].as_str(), Some("rectangle" | "ellipse")) {
                return Err(INVALID_SCENE);
            }
            if let Some(radius) = layer.get("radius") {
                number(radius, 0.0, MAX_DIMENSION)?;
            }
        }
        "text" => {
            bounded_text(&layer["text"], 8192)?;
            if !matches!(layer["font"].as_str(), Some("Sans" | "Serif" | "Mono")) {
                return Err(INVALID_SCENE);
            }
            number(&layer["fontSize"], 1.0, 512.0)?;
            number(&layer["weight"], 100.0, 900.0)?;
        }
        "image" => {
            canonical_uuid(&layer["assetId"])?;
        }
        "path" => {
            number(&layer["viewWidth"], 1.0, MAX_DIMENSION)?;
            number(&layer["viewHeight"], 1.0, MAX_DIMENSION)?;
            path(&layer["path"])?;
        }
        _ => return Err(INVALID_SCENE),
    }
    Ok(())
}

fn fields(value: &Value, required: &[&str], optional: &[&str]) -> Result<()> {
    let object = value.as_object().ok_or(INVALID_SCENE)?;
    if required.iter().any(|field| !object.contains_key(*field))
        || object
            .keys()
            .any(|field| !required.contains(&field.as_str()) && !optional.contains(&field.as_str()))
    {
        return Err(INVALID_SCENE);
    }
    Ok(())
}

fn bounded_text(value: &Value, limit: usize) -> Result<&str> {
    value
        .as_str()
        .filter(|text| !text.is_empty() && text.len() <= limit)
        .ok_or(INVALID_SCENE)
}

fn unique_id<'a>(value: &'a Value, ids: &mut HashSet<&'a str>) -> Result<()> {
    let id = bounded_text(value, 80)?;
    if !id
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        || !ids.insert(id)
    {
        return Err(INVALID_SCENE);
    }
    Ok(())
}

fn number(value: &Value, min: f64, max: f64) -> Result<()> {
    value
        .as_f64()
        .filter(|number| (min..=max).contains(number))
        .map(|_| ())
        .ok_or(INVALID_SCENE)
}

fn color(value: &Value) -> Result<()> {
    let color = value.as_str().ok_or(INVALID_SCENE)?;
    let digits = color.strip_prefix('#').ok_or(INVALID_SCENE)?;
    if digits.len() != 6 || !digits.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(INVALID_SCENE);
    }
    Ok(())
}

fn path(value: &Value) -> Result<()> {
    let source = bounded_text(value, 16 * 1024)?;
    let mut tokens = source.split_ascii_whitespace().peekable();
    if tokens.peek() != Some(&"M") {
        return Err(INVALID_SCENE);
    }
    let mut commands = 0;
    // A separate token for each command and operand keeps conversion deterministic.
    while let Some(command) = tokens.next() {
        commands += 1;
        if commands > 512 {
            return Err(INVALID_SCENE);
        }
        let operands = match command {
            "M" | "L" => 2,
            "H" | "V" => 1,
            "C" => 6,
            "Q" => 4,
            "Z" => 0,
            _ => return Err(INVALID_SCENE),
        };
        for _ in 0..operands {
            let number = tokens.next().and_then(|token| token.parse::<f64>().ok());
            if !number.is_some_and(|number| (-MAX_DIMENSION..=MAX_DIMENSION).contains(&number)) {
                return Err(INVALID_SCENE);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "design_scene_tests.rs"]
mod tests;
