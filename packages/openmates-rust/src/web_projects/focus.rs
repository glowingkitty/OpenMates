//! Project focus send decisions: the single Project a composer document mentions
//! (structured mention nodes only) and the default focus a send activates. Shared core
//! part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/projectFocusPolicy.ts`; refusals answer `{focusError: code}`.

use super::js::{as_str, js_string, opt_prop, prop, trim};
use super::{Fault, Outcome};
use serde_json::{Value, json};

/// Mention node types that carry Project consent, with their canonical syntax prefix.
const PROJECT_MENTION_PREFIXES: [(&str, &str); 3] =
    [("project", "@project:"), ("project_folder", "@project-folder:"), ("project_file", "@project-file:")];

/// Collects the Project ids of structured mention nodes, depth first, in first-seen order.
fn visit(node: &Value, ids: &mut Vec<String>) -> Result<(), Fault> {
    let node = Some(node);
    let attrs = prop(node, "attrs")?;
    if as_str(prop(node, "type")?) == Some("genericMention") {
        // `String(node.attrs?.mentionType ?? "")`
        let mention_type = match opt_prop(attrs, "mentionType") {
            None | Some(Value::Null) => String::new(),
            raw => js_string(raw),
        };
        if let Some((_, prefix)) = PROJECT_MENTION_PREFIXES.iter().find(|(kind, _)| *kind == mention_type) {
            let direct = as_str(opt_prop(attrs, "projectId")).map(trim).filter(|id| !id.is_empty());
            let id = match direct {
                Some(id) => Some(id.to_owned()),
                // Draft HTML rehydration can retain the structured Project mention and
                // canonical syntax while losing optional node-only attributes. Recover only
                // from that structured node; ordinary plaintext remains untrusted.
                None => as_str(opt_prop(attrs, "mentionSyntax"))
                    .and_then(|syntax| syntax.strip_prefix(prefix))
                    .map(|rest| trim(rest.split(':').next().unwrap_or("")).to_owned())
                    .filter(|id| !id.is_empty()),
            };
            if let Some(id) = id {
                if !ids.contains(&id) {
                    ids.push(id);
                }
            }
        }
    }
    match prop(node, "content")? {
        None | Some(Value::Null) => Ok(()),
        Some(Value::Array(children)) => children.iter().try_for_each(|child| visit(child, ids)),
        // A string iterates as one-character strings, which carry no mention fields.
        Some(Value::String(_)) => Ok(()),
        Some(_) => Err(Fault::Malformed("content_not_iterable".to_owned())),
    }
}

/// `projectFocusIntent`: the one Project the composer mentions, `null`, or `MULTIPLE_PROJECTS`.
pub(super) fn intent(input: &Value) -> Outcome {
    let mut ids = Vec::new();
    if let Some(document @ (Value::Object(_) | Value::Array(_))) = input.get("document") {
        visit(document, &mut ids)?;
    }
    Ok(match ids.as_slice() {
        [] => json!({ "intent": null }),
        [id] => json!({ "intent": { "projectId": id, "source": "composer_project_mention" } }),
        _ => json!({ "focusError": "MULTIPLE_PROJECTS" }),
    })
}

/// `projectDefaultFocusRead`: the trimmed default focus id and instructions, or unavailable.
pub(super) fn default_focus_read(input: &Value) -> Outcome {
    let unavailable = json!({ "focusError": "PROJECT_FOCUS_UNAVAILABLE" });
    let Some(Value::Object(candidate)) = prop(input.get("settings"), "default_focus")? else {
        return Ok(unavailable);
    };
    let focus_id = as_str(candidate.get("focus_id")).map(trim).filter(|s| !s.is_empty());
    let instructions = as_str(candidate.get("instructions")).map(trim).filter(|s| !s.is_empty());
    Ok(match (focus_id, instructions) {
        (Some(focus_id), Some(instructions)) => json!({ "focus": { "focus_id": focus_id, "instructions": instructions } }),
        _ => unavailable,
    })
}
