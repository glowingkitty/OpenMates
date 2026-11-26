//! Opt-in, payload-free diagnostics for a native saved-chat open.
use crate::error::{Error, Result};
use openmates_sdk::local_cache::ByteStoreError;
use openmates_sdk::view_model::{ChatWindowSource, ViewErrorKind};
use std::{io::Write, os::unix::fs::OpenOptionsExt, path::Path};

const TRACE_FILE: &str = "OPENMATES_NATIVE_CHAT_OPEN_TRACE";

pub fn phase(stage: &'static str, result: Result<()>) {
    let detail = match result {
        Ok(()) => "Ok".to_owned(),
        Err(Error::Unavailable { .. }) => "Unavailable".to_owned(),
        Err(error) => format!("{:?}", ViewErrorKind::from(&error)),
    };
    record(stage, &detail);
}

pub fn window(source: ChatWindowSource) {
    record(
        "window",
        match source {
            ChatWindowSource::Cached => "Cached",
            ChatWindowSource::CachedOffline => "CachedOffline",
            ChatWindowSource::CacheSettled => "CacheSettled",
            ChatWindowSource::FirstPage => "FirstPage",
            ChatWindowSource::Canonical => "Canonical",
            ChatWindowSource::Live => "Live",
            ChatWindowSource::LiveSettled => "LiveSettled",
        },
    );
}

pub(crate) fn cache_error(stage: &'static str, error: ByteStoreError) {
    record(stage, &format!("{error:?}"));
}

fn record(stage: &'static str, detail: &str) {
    if let Some(path) = std::env::var_os(TRACE_FILE) {
        append(Path::new(&path), stage, detail);
    }
}

fn append(path: &Path, stage: &'static str, detail: &str) {
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(path)
    {
        let _ = file.write_all(format!("{stage} {detail}\n").as_bytes());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn private_trace_appends_only_phase_labels_and_finite_error_kinds() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("open.trace");
        append(&path, "open.start", "Ok");
        append(
            &path,
            "open.finish",
            &format!(
                "{:?}",
                ViewErrorKind::from(&Error::Invalid("private detail"))
            ),
        );
        assert_eq!(
            std::fs::read_to_string(path).unwrap(),
            "open.start Ok\nopen.finish Invalid\n"
        );
    }
}
