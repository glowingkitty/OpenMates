use super::*;
use crate::mentions::{AppInfo, MentionContext, NamedEntry};

fn entry(id: &str, name: &str) -> NamedEntry {
    NamedEntry { id: id.into(), name: name.into(), kind: None }
}

fn context() -> MentionContext {
    MentionContext::with_apps(vec![AppInfo {
        id: "ai".into(),
        name: "ai".into(),
        skills: vec![entry("ask", "ask"), entry("think", "deep think")],
        focus_modes: vec![entry("plan", "project_plan")],
        settings_and_memories: vec![entry("pref", "preferred tech")],
    }])
}

#[test]
fn aliases_models_and_mates_match_npm_labels() {
    let all = list_mention_options(&context(), None, "2026-11-03");
    assert_eq!(all[0].display_name, "@Best");
    assert!(all[0].description.starts_with("Alias \u{2192} "));
    assert!(all.iter().any(|o| o.display_name == "@Gemini-3.8-Flash" && o.description == "Model: Gemini 3.8 Flash"));
    let sophia = all.iter().find(|o| o.display_name == "@Sophia").unwrap();
    assert_eq!(sophia.description, "Mate: Software Development");
}

#[test]
fn ai_ask_is_skipped_and_app_entries_are_dashed_and_capitalised() {
    let skills = list_mention_options(&context(), Some(MentionType::Skill), "2026-11-03");
    assert_eq!(skills.len(), 1);
    assert_eq!(skills[0].display_name, "@Ai-Deep-Think");
    assert_eq!(skills[0].description, "Skill: Ai \u{2192} Deep Think");
    let focus = list_mention_options(&context(), Some(MentionType::FocusMode), "2026-11-03");
    assert_eq!(focus[0].display_name, "@Ai-Project-Plan");
    assert_eq!(focus[0].description, "Focus: Ai \u{2192} Project Plan");
    let memory = list_mention_options(&context(), Some(MentionType::SettingsMemory), "2026-11-03");
    assert_eq!(memory[0].description, "Memory: Ai \u{2192} Preferred Tech");
}

#[test]
fn filter_restricts_types_and_json_uses_npm_keys() {
    let mates = list_mention_options(&context(), Some(MentionType::Mate), "2026-11-03");
    assert!(mates.iter().all(|o| o.kind == MentionType::Mate));
    let json = serde_json::to_value(&mates[0]).unwrap();
    assert_eq!(json["type"], "mate");
    assert_eq!(json["displayName"], "@Sophia");
}

#[test]
fn search_is_separator_insensitive_and_capped() {
    let all = list_mention_options(&context(), None, "2026-11-03");
    let hits = search_mention_options(all.clone(), "deep-think");
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].display_name, "@Ai-Deep-Think");
    assert_eq!(search_mention_options(all.clone(), "mate").len().min(15), search_mention_options(all, "mate").len());
    assert!(search_mention_options(list_mention_options(&context(), None, "2026-11-03"), "zzzz-nothing").is_empty());
}

#[test]
fn listable_types_reject_unknown_values() {
    assert_eq!(parse_listable_type("focus_mode"), Some(MentionType::FocusMode));
    assert_eq!(parse_listable_type("settings_memory_entry"), None);
    assert_eq!(parse_listable_type("bogus"), None);
}
