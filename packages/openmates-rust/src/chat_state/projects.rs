//! Chat organisation into Projects (`chatProjectService.ts`,
//! `utils/chatProjectNavigation.ts`). Rust plans which project calls to make;
//! the adapter performs them in order (re-checking its workspace identity
//! fence before each call), decrypts names and refreshes the project index.
//! Move persists every destination link before removing any old one.
use super::js::{js_trim, utf16_len, utf16_prefix};
use crate::{Error, Result};
use serde::Deserialize;
use std::collections::HashSet;

pub const MAX_NAME_TITLES: usize = 8;
pub const MAX_TITLE_CHARS: usize = 200;

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SidebarFolder {
    pub id: String,
    pub hash: String,
    #[serde(default)]
    pub parent_hash: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SidebarProjectItem {
    pub id: String,
    pub chat_id: String,
    #[serde(default)]
    pub folder_hash: Option<String>,
}

/// One project of the sidebar index (names are not needed for planning).
#[derive(Clone, Debug, Deserialize)]
pub struct SidebarProject {
    pub id: String,
    pub folders: Vec<SidebarFolder>,
    pub chats: Vec<SidebarProjectItem>,
}

/// `projectFolderChatIds`: chats directly in (or, recursively, below) a
/// folder; `None` is the project root. An unknown folder holds nothing.
pub fn folder_chat_ids(
    project: &SidebarProject,
    folder_id: Option<&str>,
    recursive: bool,
) -> HashSet<String> {
    let folder = folder_id.and_then(|id| project.folders.iter().find(|f| f.id == id));
    if folder_id.is_some() && folder.is_none() {
        return HashSet::new();
    }
    let mut hashes: HashSet<Option<&str>> = HashSet::from([folder.map(|f| f.hash.as_str())]);
    if recursive {
        let mut previous = 0;
        while previous != hashes.len() {
            previous = hashes.len();
            for candidate in &project.folders {
                if hashes.contains(&candidate.parent_hash.as_deref()) {
                    hashes.insert(Some(candidate.hash.as_str()));
                }
            }
        }
    }
    project
        .chats
        .iter()
        .filter(|c| hashes.contains(&c.folder_hash.as_deref()))
        .map(|c| c.chat_id.clone())
        .collect()
}

/// Organisation flags for one chat (demo/legal/public lists stay in the adapter).
#[derive(Clone, Debug, Default, Deserialize)]
pub struct OrganizableChat {
    pub chat_id: String,
    #[serde(default)]
    pub is_incognito: bool,
    #[serde(default)]
    pub is_shared_by_others: bool,
    #[serde(default)]
    pub is_static: bool,
    #[serde(default)]
    pub team_id: Option<String>,
}

pub const NOT_ORGANIZABLE: Error =
    Error::Invalid("These chats cannot be organized in this workspace");

/// `assertOrganizableChats`.
pub fn assert_organizable(chats: &[OrganizableChat], active_team_id: Option<&str>) -> Result<()> {
    let refused = chats.is_empty()
        || chats.iter().any(|c| {
            c.is_incognito
                || c.is_shared_by_others
                || c.is_static
                || c.team_id.as_deref() != active_team_id
        });
    if refused {
        Err(NOT_ORGANIZABLE)
    } else {
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlacementMode {
    Add,
    Move,
}

/// One project call, executed strictly in order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PlacementOp {
    /// `moveProjectItemToFolder(project, item_id, folder_id)`.
    MoveItem { item_id: String, chat_id: String },
    /// `addExistingTargetToProject(project, chat_id, "chat", name, folder_id)`.
    AddChat { chat_id: String },
    /// `removeChatFromProject(project_id, chat_id)` for another project.
    RemoveFromProject { project_id: String, chat_id: String },
}

/// `placeChatsInProject` plan against a freshly loaded index.
pub fn plan_placement(
    index: &[SidebarProject],
    project_id: &str,
    folder_id: Option<&str>,
    chat_ids: &[String],
    mode: PlacementMode,
) -> Result<Vec<PlacementOp>> {
    let destination = index
        .iter()
        .find(|p| p.id == project_id)
        .ok_or(Error::Invalid("Project is unavailable"))?;
    if let Some(folder) = folder_id
        && !destination.folders.iter().any(|f| f.id == folder)
    {
        return Err(Error::Invalid("Folder is unavailable"));
    }
    let already_there = folder_chat_ids(destination, folder_id, false);
    let mut ops = Vec::new();
    for chat_id in chat_ids.iter().filter(|id| !already_there.contains(*id)) {
        ops.push(
            match destination
                .chats
                .iter()
                .find(|item| &item.chat_id == chat_id)
            {
                Some(item) => PlacementOp::MoveItem {
                    item_id: item.id.clone(),
                    chat_id: chat_id.clone(),
                },
                None => PlacementOp::AddChat {
                    chat_id: chat_id.clone(),
                },
            },
        );
    }
    if mode == PlacementMode::Move {
        for source in index.iter().filter(|p| p.id != project_id) {
            for chat_id in chat_ids
                .iter()
                .filter(|id| source.chats.iter().any(|item| &item.chat_id == *id))
            {
                ops.push(PlacementOp::RemoveFromProject {
                    project_id: source.id.clone(),
                    chat_id: chat_id.clone(),
                });
            }
        }
    }
    Ok(ops)
}

/// Titles submitted for an AI project name: the first 8 chats, 200 units each.
pub fn naming_titles(titles: &[String]) -> Vec<String> {
    titles
        .iter()
        .take(MAX_NAME_TITLES)
        .map(|t| utf16_prefix(t, MAX_TITLE_CHARS).to_owned())
        .collect()
}

/// Validate `proposed_project.name` from `/v1/projects/ask/plan`.
pub fn validate_project_name(proposed: Option<&str>) -> Result<String> {
    let name = proposed.map(js_trim).unwrap_or_default();
    if name.is_empty() || utf16_len(name) > MAX_TITLE_CHARS {
        return Err(Error::Invalid("The generated project title is invalid"));
    }
    Ok(name.to_owned())
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "projects_tests.rs"]
mod tests;
