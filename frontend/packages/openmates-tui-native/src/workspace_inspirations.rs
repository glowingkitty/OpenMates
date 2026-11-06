//! Hardcoded per-workspace inspirations (`workspaceInspirationDefaults.ts`)
//! the TS TUI shows on the Apps, Projects and Workflows homes.
use openmates_sdk::client::overview::inspirations::Inspiration;
use openmates_sdk::model::Workspace;

const DEFAULTS: &[(&str, &str, &str, &str, &str, &str)] = &[
    ("Apps", "hardcoded-apps-search", "Find information directly with an app skill, and keep the results for later.", "Use a Skill Directly", "general_knowledge", "Search the web"),
    ("Apps", "hardcoded-apps-weather", "Check the forecast before making plans. Your saved results stay together in Apps.", "Plan Around the Weather", "travel", "Weather forecast"),
    ("Projects", "hardcoded-project-brief", "Start every project with a short brief: goal, audience, deadline, and the first concrete next step.", "Write a Project Brief", "productivity", "Project planning tip"),
    ("Projects", "hardcoded-project-milestones", "Use milestones as folders: research, prototype, review, launch. It keeps work visible without extra UI.", "Milestone Folders", "software_development", "Milestone structure"),
    ("Projects", "hardcoded-project-assets", "Save the source next to the output: prompts, PDFs, images, and final embeds belong in the same project context.", "Keep Sources Together", "general_knowledge", "Project organization"),
    ("Workflows", "hardcoded-workflow-trigger", "A useful workflow starts with one trigger, one decision, and one visible result.", "Design a Workflow Trigger", "productivity", "Workflow planning tip"),
];

/// Fallback inspirations for a workspace home; empty for the Chats home, which uses the server list.
pub fn workspace_defaults(workspace: Workspace) -> Vec<Inspiration> {
    let label = workspace.label();
    DEFAULTS
        .iter()
        .filter(|row| row.0 == label)
        .map(|(_, id, phrase, title, category, feature)| Inspiration {
            id: (*id).into(),
            phrase: (*phrase).into(),
            title: (*title).into(),
            category: (*category).into(),
            feature_title: Some((*feature).into()),
            surface: label.to_lowercase(),
            legacy_json: serde_json::Value::Null,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
    #[test]
    fn apps_projects_and_workflows_have_defaults_but_chats_does_not() {
        assert_eq!(workspace_defaults(Workspace::Apps).len(), 2);
        assert_eq!(workspace_defaults(Workspace::Projects).len(), 3);
        assert_eq!(workspace_defaults(Workspace::Workflows).len(), 1);
        assert!(workspace_defaults(Workspace::Chats).is_empty());
        assert_eq!(workspace_defaults(Workspace::Apps)[0].feature_title.as_deref(), Some("Search the web"));
    }
}
