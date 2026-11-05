//! Local remote-command preset/resource activation (npm
//! `remoteCommandPermissions.ts`, `remoteCommandClient.ts` preset grants,
//! `remoteCommandResourceGrants.ts` and the `remoteAccess.ts` source store).
//!
//! Repository files only *define* presets and resource profiles. Activation
//! grants live in private control state outside the command-writable Project
//! and bind a definition digest, so editing `.openmates/permissions.yml` can
//! never activate or broaden a grant. Digests and store formats are
//! byte-compatible with the npm CLI so grants written by either CLI interoperate.
//!
//! Every function takes the state directory explicitly; this module never
//! reads environment variables, profiles or credentials. Credential grants
//! store environment variable NAMES only, never values.
use std::fmt;

mod digest;
mod permissions;
mod sources;
mod store;

pub use digest::{remote_command_preset_digest, resource_definition_digest, stable_json};
pub use permissions::{
    CredentialProfile, FileAccess, NetworkProfile, REMOTE_COMMAND_PERMISSIONS_PATH,
    RemoteCommandPermissions, RemoteCommandPolicy, RemoteCommandPreset, ResourceProfiles,
    WritableProfile, load_remote_command_permissions, parse_remote_command_permissions,
};
pub use sources::{
    REMOTE_SOURCES_FILE, RemoteAccessSource, list_remote_access_sources,
    select_remote_command_source,
};
pub use store::{
    PRESET_GRANTS_FILE, PresetGrant, RESOURCE_GRANTS_FILE, ResourceKind, disable_preset_grant,
    disable_resource_grant, enable_credential_grant, enable_network_grant, enable_preset_grant,
    enable_writable_grant, list_preset_grants, list_resource_grants,
};

/// A failure with the exact npm CLI error code and message. npm plain
/// `Error`s map to `command_failed`; `CliContractError`s keep their code.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteCommandError {
    pub code: &'static str,
    pub message: String,
}
impl RemoteCommandError {
    pub fn failed(message: impl Into<String>) -> Self {
        Self {
            code: "command_failed",
            message: message.into(),
        }
    }
    pub fn contract(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}
impl fmt::Display for RemoteCommandError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for RemoteCommandError {}

pub type RemoteCommandResult<T> = std::result::Result<T, RemoteCommandError>;

/// Node-style filesystem error text (`ENOENT: no such file or directory,
/// realpath '/x'`) for the common kinds; other kinds keep the OS description.
pub(crate) fn io_error(
    operation: &str,
    path: &std::path::Path,
    error: &std::io::Error,
) -> RemoteCommandError {
    let prefix = match error.kind() {
        std::io::ErrorKind::NotFound => "ENOENT: no such file or directory",
        std::io::ErrorKind::PermissionDenied => "EACCES: permission denied",
        std::io::ErrorKind::AlreadyExists => "EEXIST: file already exists",
        std::io::ErrorKind::NotADirectory => "ENOTDIR: not a directory",
        _ => {
            return RemoteCommandError::failed(format!(
                "{operation} '{}' failed: {error}",
                path.display()
            ));
        }
    };
    RemoteCommandError::failed(format!("{prefix}, {operation} '{}'", path.display()))
}

#[cfg(test)]
mod tests;
