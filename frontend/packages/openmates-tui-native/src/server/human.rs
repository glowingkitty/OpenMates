//! npm-identical human text for server commands whose npm output is plain text.
//!
//! `server features ...` has no JSON mode in the npm CLI; it always prints the lines
//! below. The native `--json` receipts stay available as an additive extension.
use serde_json::Value;

/// Human text for `action`, or `None` when the command keeps the generic rendering.
pub fn human_text(action: &str, value: &Value) -> Option<String> {
    match action {
        "features" | "features list" => Some(features_list(value)),
        "features explain" => Some(features_explain(value)),
        "features enable" | "features disable" | "features reset" => Some(format!(
            "Updated {}\nRestart the server for feature changes to take effect: openmates server restart",
            value["path"].as_str()?
        )),
        _ => None,
    }
}

fn kind(id: &str) -> &str {
    match id.split(':').next() {
        Some(kind) if !kind.is_empty() => kind,
        _ => "unknown",
    }
}

fn ids(value: &Value) -> Vec<&str> {
    value
        .as_array()
        .map(|items| items.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default()
}

fn features_list(value: &Value) -> String {
    let enabled = ids(&value["enabled"]);
    let disabled = ids(&value["disabled"]);
    let joined = |list: &[&str]| {
        if list.is_empty() {
            "none".to_owned()
        } else {
            list.join(", ")
        }
    };
    let mut lines = vec![
        "Feature overrides:".to_owned(),
        format!("  enabled: {}", joined(&enabled)),
        format!("  disabled: {}", joined(&disabled)),
        String::new(),
        "Known off-by-default features:".to_owned(),
    ];
    for feature in value["knownOffByDefault"].as_array().into_iter().flatten() {
        let id = feature["id"].as_str().unwrap_or_default();
        let state = if enabled.contains(&id) {
            "enabled override"
        } else if disabled.contains(&id) {
            "disabled override"
        } else {
            "default off"
        };
        lines.push(format!(
            "  {id} ({}): {state} - {}",
            kind(id),
            feature["reason"].as_str().unwrap_or_default()
        ));
    }
    lines.join("\n")
}

fn features_explain(value: &Value) -> String {
    let id = value["feature"].as_str().unwrap_or_default();
    let default = value["default"].as_str().unwrap_or_default();
    let reason = value["reason"]
        .as_str()
        .map(|reason| format!(" ({reason})"))
        .unwrap_or_default();
    [
        format!("Feature: {id}"),
        format!("Kind: {}", kind(id)),
        format!("Default: {default}{reason}"),
        format!(
            "Override: {}",
            value["override"].as_str().unwrap_or_default()
        ),
        format!(
            "Effective after restart: {}",
            value["effectiveAfterRestart"].as_str().unwrap_or_default()
        ),
    ]
    .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn features_text_matches_the_npm_cli_layout() {
        let list = json!({"command":"features list","enabled":["platform:workflows"],"disabled":[],
            "knownOffByDefault":[{"id":"embed:code:application","reason":"Application previews are still unstable"},
                                 {"id":"platform:workflows","reason":"Workflows workspace is off by default"}]});
        assert_eq!(
            human_text("features list", &list).unwrap(),
            "Feature overrides:\n  enabled: platform:workflows\n  disabled: none\n\nKnown off-by-default features:\n  embed:code:application (embed): default off - Application previews are still unstable\n  platform:workflows (platform): enabled override - Workflows workspace is off by default"
        );
        let explain = json!({"command":"features explain","feature":"embed:code:application","default":"off",
            "reason":"Application previews are still unstable","override":"none","effectiveAfterRestart":"disabled"});
        assert_eq!(
            human_text("features explain", &explain).unwrap(),
            "Feature: embed:code:application\nKind: embed\nDefault: off (Application previews are still unstable)\nOverride: none\nEffective after restart: disabled"
        );
        let update =
            json!({"command":"features enable","path":"/srv/om/backend/config/backend_config.yml"});
        assert_eq!(
            human_text("features enable", &update).unwrap(),
            "Updated /srv/om/backend/config/backend_config.yml\nRestart the server for feature changes to take effect: openmates server restart"
        );
        assert!(human_text("status", &json!({})).is_none());
    }
}
