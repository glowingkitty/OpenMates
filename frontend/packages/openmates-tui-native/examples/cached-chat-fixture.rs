//! CI-only synthetic profile fixture. No production flags or cache-file writes.
//! Explicit loopback credentials use the actual encrypted RuntimeStore boundary;
//! subsequent actual native reads must authenticate and populate their own cache.
use openmates_sdk::{Client, Session};
use openmates_tui_native::runtime_store::RuntimeStore;
use serde_json::{Value, json};
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
use std::{collections::BTreeMap, io::Read, path::PathBuf};
use zeroize::Zeroizing;
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::var("CI").as_deref() != Ok("true") || std::env::args().len() != 1 {
        return Err("CI synthetic fixture only".into());
    }
    let mut raw = Zeroizing::new(Vec::new());
    std::io::stdin().take(8193).read_to_end(&mut raw)?;
    if raw.len() > 8192 {
        return Err("Fixture input bound".into());
    }
    let value: Value = serde_json::from_slice(&raw)?;
    let api = value["endpoint"].as_str().ok_or("Fixture endpoint")?;
    let url = url::Url::parse(api)?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("Ephemeral literal loopback required".into());
    }
    let path = PathBuf::from(value["state_dir"].as_str().ok_or("Fresh fixture state")?);
    let meta = path.symlink_metadata()?;
    if !path.is_absolute()
        || path.canonicalize()? != path
        || !meta.is_dir()
        || meta.file_type().is_symlink()
        || std::fs::read_dir(&path)?.next().is_some()
    {
        return Err("Fresh owned directory required".into());
    }
    #[cfg(unix)]
    if meta.uid() != rustix::process::getuid().as_raw() || meta.mode() & 0o077 != 0 {
        return Err("Private owned directory required".into());
    }
    let session = Session {
        api_url: api.into(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::from([(
            "auth_refresh_token".into(),
            "synthetic-refresh-token".into(),
        )]),
        ws_token: None,
        master_key: Zeroizing::new(std::array::from_fn(|n| n as u8)),
        hashed_email: "synthetic-cached-ui-owner".into(),
        user_email_salt: "synthetic-salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let app_origin = Client::new(api, None)?.application_url();
    let profile = path.clone();
    let store = RuntimeStore::new(Some(path), true).await?;
    store.begin_session(session.clone()).await?;
    store
        .save(
            session,
            Some(Zeroizing::new("SyntheticCachedFixturePassphrase".into())),
        )
        .await?;
    for entry in std::fs::read_dir(&profile)? {
        let name = entry?.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("cache-") && name.ends_with(".json") {
            return Err("Fixture seeder must not write chat cache".into());
        }
    }
    println!(
        "{}",
        json!({"status":"seeded-explicit-synthetic-session","app_origin":app_origin,"cache_written":false})
    );
    Ok(())
}
