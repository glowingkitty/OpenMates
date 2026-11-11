//! Home workspace presentation of the terminal UI: the featured Apps order
//! and the workspace defaults. The chat list order ("Continue where you left
//! off") lives in the core (`openmates_sdk::view_model::arrange_chat_list`).
use openmates_sdk::model::Item;

#[path = "workspace_inspirations.rs"]
pub mod defaults;

/// TS `HOME_APP_ORDER`: the featured apps shown on the Apps home before `/browse`.
const HOME_APP_ORDER: [&str; 6] = ["web", "news", "health", "travel", "weather", "audio"];

/// TS `homeTuiApps`: featured apps in home order (all apps, name-sorted after
/// the featured ones, when `show_all`).
pub fn featured_apps(mut apps: Vec<Item>, show_all: bool) -> Vec<Item> {
    let rank = |id: &str| HOME_APP_ORDER.iter().position(|home| *home == id);
    apps.sort_by(|a, b| match (rank(&a.id), rank(&b.id)) {
        (Some(left), Some(right)) => left.cmp(&right),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => a.title.to_lowercase().cmp(&b.title.to_lowercase()),
    });
    if !show_all {
        apps.retain(|app| rank(&app.id).is_some());
    }
    apps
}

#[cfg(test)]
mod apps_tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
    #[test]
    fn featured_apps_follow_home_order_and_browse_shows_the_rest_by_name() {
        let app = |id: &str| Item { id: id.into(), title: id.to_uppercase(), ..Item::default() };
        let apps = vec![app("zeta"), app("audio"), app("web"), app("alpha"), app("travel")];
        let ids = |items: Vec<Item>| items.into_iter().map(|item| item.id).collect::<Vec<_>>();
        assert_eq!(ids(featured_apps(apps.clone(), false)), ["web", "travel", "audio"]);
        assert_eq!(ids(featured_apps(apps, true)), ["web", "travel", "audio", "alpha", "zeta"]);
    }
}
