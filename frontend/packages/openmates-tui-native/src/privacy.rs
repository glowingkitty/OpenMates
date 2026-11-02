//! CLI profile preference I/O stays in the native application.
use crate::error::{Error, Result};
pub use openmates_sdk::privacy::*;
use serde_json::Value;
#[cfg(test)]
use serde_json::json;
use std::{
    fs::{self, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
};
/// Select paths in the application, once, instead of reading process-global
/// profile variables inside a reusable SDK. Check legacy preferences as well
/// during transition so changing binaries cannot silently disable an opt-in.
pub fn gate_for_profile(
    profile: &crate::profile::ResolvedProfile,
    home: &Path,
) -> std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync> {
    let native = profile.state_dir.join("privacy-preferences.json");
    let legacy = match &profile.profile {
        Some(name) => home.join(".openmates/profiles").join(name),
        None => home.join(".openmates"),
    }
    .join("privacy-preferences.json");
    std::sync::Arc::new(move || {
        verify_preferences_path(&legacy)?;
        verify_preferences_path(&native)
    })
}
/// Enhanced offline semantic privacy has no Rust model implementation yet.
/// Existing opted-in preferences therefore block submission instead of degrading it.
pub fn verify_enhanced_disabled() -> Result<()> {
    let directory = state_directory()?;
    verify_preferences_path(&directory.join("privacy-preferences.json"))
}
fn state_directory() -> Result<PathBuf> {
    if let Some(value) = std::env::var_os("OPENMATES_STATE_DIR").filter(|v| !v.is_empty()) {
        let path = PathBuf::from(value);
        if !path.is_absolute() {
            return Err(Error::Invalid("OPENMATES_STATE_DIR must be absolute."));
        }
        return Ok(path);
    }
    let home = std::env::var_os("HOME")
        .filter(|v| !v.is_empty())
        .ok_or(Error::Invalid(
            "The account state directory is unavailable.",
        ))?;
    let base = PathBuf::from(home).join(".openmates");
    let profile = std::env::var("OPENMATES_PROFILE").unwrap_or_default();
    let profile = profile.trim();
    if profile.is_empty() {
        return Ok(base);
    }
    if profile.len() > 64
        || profile.starts_with('-')
        || !profile
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
    {
        return Err(Error::Invalid("Invalid account profile."));
    }
    Ok(base.join("profiles").join(profile))
}
fn verify_preferences_path(path: &Path) -> Result<()> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => {
            return Err(Error::Invalid(
                "Privacy preferences could not be read safely.",
            ));
        }
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 65536 {
        return Err(Error::Invalid(
            "Privacy preferences could not be read safely.",
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
        if metadata.mode() & 0o077 != 0 || metadata.uid() != rustix::process::getuid().as_raw() {
            return Err(Error::Invalid(
                "Privacy preferences must be private to this account.",
            ));
        }
        options.custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32);
    }
    let file = options
        .open(path)
        .map_err(|_| Error::Invalid("Privacy preferences could not be read safely."))?;
    let opened = file.metadata().map_err(|_| Error::Io)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if opened.dev() != metadata.dev()
            || opened.ino() != metadata.ino()
            || opened.mode() & 0o077 != 0
            || opened.uid() != rustix::process::getuid().as_raw()
        {
            return Err(Error::Invalid(
                "Privacy preferences changed during validation.",
            ));
        }
    }
    if !opened.is_file() {
        return Err(Error::Invalid("Invalid privacy preference file."));
    }
    let mut raw = String::new();
    file.take(65537)
        .read_to_string(&mut raw)
        .map_err(|_| Error::Invalid("Invalid privacy preferences."))?;
    if raw.len() > 65536 {
        return Err(Error::Invalid("Invalid privacy preferences."));
    }
    let preferences: Value =
        serde_json::from_str(&raw).map_err(|_| Error::Invalid("Invalid privacy preferences."))?;
    let projects = preferences["projects"]
        .as_array()
        .ok_or(Error::Invalid("Invalid privacy preferences."))?;
    if preferences["version"] != 1
        || preferences["enabled"].as_bool().is_none()
        || preferences["documents"].as_bool().is_none()
        || projects.len() > 512
        || projects.iter().any(|v| {
            v.as_str().is_none_or(|s| {
                s.len() != 36 || !s.bytes().all(|c| c.is_ascii_hexdigit() || c == b'-')
            })
        })
    {
        return Err(Error::Invalid("Invalid privacy preferences."));
    }
    if preferences["enabled"] == true {
        return Err(Error::Invalid(
            "Enhanced personal data anonymization is enabled but unavailable in this Rust client. Disable it explicitly in privacy settings before sending.",
        ));
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "../tests/privacy_preferences/mod.rs"]
mod tests;
