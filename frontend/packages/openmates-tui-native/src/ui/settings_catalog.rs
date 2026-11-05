//! Top-level Settings menu, matching the TS TUI catalog (tuiSettingsCatalog.ts).
// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned

/// Pseudo-route for the trailing "Log out" row; never sent to the SDK.
pub(super) const LOGOUT_ROUTE: &str = "__logout";

/// Main menu rows `(route, title, web_only)` in TS order. `restricted`
/// (paired sessions) hides pages that need browser-level identity.
pub(super) fn main_pages(authenticated: bool, restricted: bool) -> Vec<(String, String, bool)> {
    let all: [(&str, &str, bool); 13] = [
        ("ai", "AI", false),
        ("privacy", "Privacy", false),
        ("projects", "Projects", true),
        ("teams", "Teams", false),
        ("mates", "Mates", false),
        ("notifications", "Notifications", false),
        ("interface", "Interface", false),
        ("account", "Account", false),
        ("developers", "Developers", false),
        ("support", "Support & Community", true),
        ("newsletter", "Newsletter", false),
        ("settings_memories", "Memories", false),
        ("billing", "Billing & Usage", false),
    ];
    let mut rows: Vec<_> = all
        .iter()
        .filter(|(route, _, _)| authenticated || !matches!(*route, "ai" | "privacy" | "teams" | "mates" | "notifications" | "interface" | "account" | "developers" | "settings_memories" | "billing" | "projects"))
        .filter(|(route, _, _)| !restricted || !matches!(*route, "account" | "settings_memories" | "billing"))
        .map(|(r, t, w)| (r.to_string(), t.to_string(), *w))
        .collect();
    // Billing is only offered when payments are enabled; the native client has
    // no payment flag, so it stays out of the menu like the TS default.
    rows.retain(|(route, _, _)| route != "billing");
    if authenticated {
        rows.push((LOGOUT_ROUTE.into(), "Log out".into(), false));
    }
    rows
}

pub(super) const KEY_HINT: &str = "↑/↓ select · Enter open/edit\nEsc back/close";

#[cfg(test)]
mod tests {
    use super::*;
    fn titles(rows: &[(String, String, bool)]) -> Vec<&str> {
        rows.iter().map(|r| r.1.as_str()).collect()
    }
    #[test]
    fn restricted_menu_matches_the_ts_page_set() {
        let rows = main_pages(true, true);
        assert_eq!(
            titles(&rows),
            ["AI", "Privacy", "Projects", "Teams", "Mates", "Notifications", "Interface", "Developers", "Support & Community", "Newsletter", "Log out"]
        );
        assert!(rows[2].2 && rows[8].2);
    }
    #[test]
    fn unrestricted_menu_adds_account_and_memories() {
        let rows = main_pages(true, false);
        assert!(titles(&rows).contains(&"Account") && titles(&rows).contains(&"Memories"));
    }
    #[test]
    fn signed_out_menu_has_no_log_out() {
        assert!(!titles(&main_pages(false, false)).contains(&"Log out"));
    }
}
