//! Application-only profile selection. The SDK never reads environment or disk.
use crate::{
    error::{Error, Result},
    storage::Session,
};
use std::path::{Component, Path, PathBuf};

/// Explicit API keys have independent device/journal state. They never unlock a
/// cookie profile or reset its durable logout fence, including with a live TUI.
pub fn api_key_state_dir(profile: &Path, api: &str, credential: &str) -> PathBuf {
    use sha2::{Digest, Sha256};
    let bearer = credential.split('.').next().unwrap_or("");
    let mut hash = Sha256::new();
    hash.update(b"openmates-cli-api-key-state-v1\0");
    hash.update(api.as_bytes());
    hash.update(b"\0");
    hash.update(bearer.as_bytes());
    profile
        .join("api-key-profiles")
        .join(format!("{:x}", hash.finalize()))
}

/// Public free-usage state never reuses an account or API-key device identity.
/// Canonical API origins share an ID; different services cannot correlate the
/// locally generated identifier through an application credential namespace.
pub fn anonymous_state_dir(profile: &Path, api: &str) -> Result<PathBuf> {
    use sha2::{Digest, Sha256};
    let api = normalize_api(api)?;
    let mut hash = Sha256::new();
    hash.update(b"openmates-cli-anonymous-state-v1\0");
    hash.update(api.as_bytes());
    Ok(profile
        .join("anonymous-profiles")
        .join(format!("{:x}", hash.finalize())))
}

#[derive(Default)]
pub struct ProfileOptions {
    pub profile: Option<String>,
    pub state_dir: Option<PathBuf>,
    pub api_url: Option<String>,
}
#[derive(Default)]
pub struct ProfileEnvironment {
    pub profile: Option<String>,
    pub state_dir: Option<PathBuf>,
    pub api_url: Option<String>,
}
impl ProfileEnvironment {
    pub fn capture() -> Self {
        let text = |key| std::env::var(key).ok().filter(|s| !s.trim().is_empty());
        Self {
            profile: text("OPENMATES_PROFILE"),
            state_dir: text("OPENMATES_STATE_DIR").map(PathBuf::from),
            api_url: text("OPENMATES_API_URL"),
        }
    }
}
pub struct ResolvedProfile {
    pub state_dir: PathBuf,
    pub profile: Option<String>,
    pub api_url_override: Option<String>,
}
impl ResolvedProfile {
    /// Resolve before opening a store. Explicit target changes require a fresh
    /// login; a cookie obtained for another API is never sent to the new target.
    pub fn api_url(
        &self,
        session: Option<&Session>,
        installed_api: Option<&str>,
    ) -> Result<String> {
        let target = self
            .api_url_override
            .as_deref()
            .or_else(|| session.map(|s| s.api_url.as_str()))
            .or(installed_api)
            .unwrap_or("https://api.openmates.org");
        let target = normalize_api(target)?;
        if let Some(session) = session
            && normalize_api(&session.api_url)? != target
        {
            return Err(Error::Invalid(
                "Selected API differs from this profile's session. Use a separate profile or sign out first.",
            ));
        }
        Ok(target)
    }
}
fn normalize_api(value: &str) -> Result<String> {
    let mut parsed = url::Url::parse(value)
        .map_err(|_| Error::Invalid("API URL must be an absolute HTTP(S) URL."))?;
    if !matches!(parsed.scheme(), "http" | "https")
        || parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || !matches!(parsed.path(), "" | "/")
    {
        return Err(Error::Invalid(
            "API URL must be an absolute HTTP(S) URL without credentials, query or fragment.",
        ));
    }
    if parsed.scheme() == "http"
        && !matches!(
            parsed.host_str(),
            Some("localhost" | "127.0.0.1" | "[::1]" | "::1")
        )
    {
        return Err(Error::Invalid("Remote API URLs require HTTPS."));
    }
    if parsed.scheme() == "http" && parsed.host_str() == Some("localhost") {
        parsed
            .set_host(Some("127.0.0.1"))
            .map_err(|_| Error::Invalid("Invalid loopback API."))?;
    }
    Ok(parsed.as_str().trim_end_matches('/').to_owned())
}
/// Installed application origins apply only to their matching API. A saved
/// cloud session must not inherit the local self-host server's browser origin.
pub fn application_origin(
    api: &str,
    explicit: Option<String>,
    installed_api: Option<&str>,
    installed_app: Option<String>,
) -> Result<Option<String>> {
    if explicit.is_some() {
        return Ok(explicit);
    }
    if installed_api.map(normalize_api).transpose()?.as_deref()
        == Some(normalize_api(api)?.as_str())
    {
        Ok(installed_app)
    } else {
        Ok(None)
    }
}
pub fn resolve(
    options: ProfileOptions,
    environment: ProfileEnvironment,
    home: &Path,
) -> Result<ResolvedProfile> {
    let profile = options
        .profile
        .or(environment.profile)
        .map(|s| s.trim().to_owned())
        .filter(|s| !s.is_empty());
    let state = options.state_dir.or(environment.state_dir);
    if profile.is_some() && state.is_some() {
        return Err(Error::Invalid(
            "Choose either a named profile or a state directory.",
        ));
    }
    if let Some(name) = &profile
        && (name.len() > 64
            || !name
                .as_bytes()
                .first()
                .is_some_and(u8::is_ascii_alphanumeric)
            || !name
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'))
    {
        return Err(Error::Invalid(
            "Profile names use 1–64 lowercase letters, digits or hyphens and start with a letter or digit.",
        ));
    }
    let state_dir = state.unwrap_or_else(|| match &profile {
        Some(name) => home.join(".openmates-rust/profiles").join(name),
        None => home.join(".openmates-rust"),
    });
    if !state_dir.is_absolute()
        || state_dir
            .components()
            .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
    {
        return Err(Error::Invalid(
            "State directory must be an absolute normalized path.",
        ));
    }
    let legacy = home.join(".openmates");
    if state_dir.starts_with(&legacy) {
        return Err(Error::Invalid(
            "The installed TypeScript CLI state is separate. Select native state and sign in again; rotating sessions cannot be copied safely.",
        ));
    }
    let api_url_override = options
        .api_url
        .or(environment.api_url)
        .map(|s| normalize_api(&s))
        .transpose()?;
    Ok(ResolvedProfile {
        state_dir,
        profile,
        api_url_override,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn anonymous_state_is_canonical_per_origin_and_separate_from_credentials() {
        let profile = Path::new("/example/.openmates-rust");
        let path = anonymous_state_dir(profile, "https://API.example:443/").unwrap();
        assert_eq!(
            path,
            anonymous_state_dir(profile, "https://api.example").unwrap()
        );
        assert_eq!(path.parent().unwrap(), profile.join("anonymous-profiles"));
        assert_ne!(
            path,
            anonymous_state_dir(profile, "https://other.example").unwrap()
        );
        assert_ne!(
            path,
            api_key_state_dir(profile, "https://api.example", "bearer.secret")
        );
        assert!(anonymous_state_dir(profile, "https://user:pass@api.example").is_err());
        assert!(anonymous_state_dir(profile, "http://remote.example").is_err());
        assert_eq!(
            anonymous_state_dir(profile, "http://localhost:8000/").unwrap(),
            anonymous_state_dir(profile, "http://127.0.0.1:8000").unwrap()
        );
    }
    #[test]
    fn api_key_state_isolated_by_origin_and_bearer_without_secret_paths() {
        let profile = Path::new("/example/.openmates-rust");
        let path = api_key_state_dir(profile, "https://api.example", "bearer-a.secret-one");
        assert_eq!(path.parent().unwrap(), profile.join("api-key-profiles"));
        assert_ne!(path, profile);
        assert_eq!(
            path,
            api_key_state_dir(profile, "https://api.example", "bearer-a.secret-two")
        );
        assert_ne!(
            path,
            api_key_state_dir(profile, "https://other.example", "bearer-a.secret-one")
        );
        assert_ne!(
            path,
            api_key_state_dir(profile, "https://api.example", "bearer-b.secret-one")
        );
        let name = path.file_name().unwrap().to_str().unwrap();
        assert_eq!(name.len(), 64);
        assert!(name.bytes().all(|c| c.is_ascii_hexdigit()));
        assert!(!path.to_string_lossy().contains("bearer-a"));
        assert!(!path.to_string_lossy().contains("secret-one"));
    }
    #[tokio::test]
    async fn explicit_api_key_device_state_does_not_unlock_or_reset_cookie_revocation() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let cookie =
            crate::runtime_store::RuntimeStore::new(Some(directory.path().to_path_buf()), true)
                .await
                .unwrap();
        cookie.revoke().await.unwrap();
        let fence = std::fs::read(directory.path().join("revocation.json")).unwrap();
        let path = api_key_state_dir(directory.path(), "https://api.example", "bearer.secret");
        let explicit = crate::runtime_store::RuntimeStore::new(Some(path), false)
            .await
            .unwrap();
        let device = explicit.device_identity().await.unwrap();
        assert!(!device.is_empty());
        assert!(explicit.load(None).await.unwrap().is_none());
        assert!(cookie.load(None).await.unwrap().is_none());
        assert_eq!(
            std::fs::read(directory.path().join("revocation.json")).unwrap(),
            fence
        );
    }
    #[test]
    fn installed_app_origin_only_applies_to_its_selected_api() {
        assert_eq!(
            application_origin(
                "https://api.cloud.test",
                None,
                Some("http://127.0.0.1:8000"),
                Some("http://localhost:5173".into())
            )
            .unwrap(),
            None
        );
        assert_eq!(
            application_origin(
                "http://127.0.0.1:8000",
                None,
                Some("http://localhost:8000"),
                Some("http://localhost:5173".into())
            )
            .unwrap()
            .as_deref(),
            Some("http://localhost:5173")
        );
        assert_eq!(
            application_origin(
                "https://api.cloud.test",
                Some("https://app.cloud.test".into()),
                None,
                None
            )
            .unwrap()
            .as_deref(),
            Some("https://app.cloud.test")
        );
        assert_eq!(
            normalize_api("http://localhost:8000/").unwrap(),
            "http://127.0.0.1:8000"
        );
        assert!(normalize_api("https://api.cloud.test/v1").is_err());
    }
    #[test]
    fn named_profiles_are_isolated_and_legacy_state_is_rejected() {
        let result = resolve(
            ProfileOptions {
                profile: Some("work-2".into()),
                ..Default::default()
            },
            ProfileEnvironment::default(),
            Path::new("/example"),
        )
        .unwrap();
        assert_eq!(
            result.state_dir,
            Path::new("/example/.openmates-rust/profiles/work-2")
        );
        for path in [
            "/example/.openmates",
            "/example/.openmates/profiles/work",
            "/example/native/../.openmates",
        ] {
            assert!(
                resolve(
                    ProfileOptions {
                        state_dir: Some(path.into()),
                        ..Default::default()
                    },
                    ProfileEnvironment::default(),
                    Path::new("/example")
                )
                .is_err()
            );
        }
        for profile in ["../work", "Work", "-work", "a/b"] {
            assert!(
                resolve(
                    ProfileOptions {
                        profile: Some(profile.into()),
                        ..Default::default()
                    },
                    ProfileEnvironment::default(),
                    Path::new("/example")
                )
                .is_err()
            );
        }
    }
    #[test]
    fn flags_override_environment_and_conflicts_fail_closed() {
        let options = ProfileOptions {
            api_url: Some("https://custom.example/".into()),
            ..Default::default()
        };
        let environment = ProfileEnvironment {
            api_url: Some("https://env.example".into()),
            ..Default::default()
        };
        let result = resolve(options, environment, Path::new("/example")).unwrap();
        assert_eq!(
            result.api_url(None, None).unwrap(),
            "https://custom.example"
        );
        assert!(
            resolve(
                ProfileOptions {
                    profile: Some("work".into()),
                    ..Default::default()
                },
                ProfileEnvironment {
                    state_dir: Some("/state".into()),
                    ..Default::default()
                },
                Path::new("/example")
            )
            .is_err()
        );
        assert!(normalize_api("https://user:secret@example.com").is_err());
        assert!(normalize_api("http://remote.example").is_err());
        assert_eq!(
            normalize_api("http://127.0.0.1:8000/").unwrap(),
            "http://127.0.0.1:8000"
        );
    }
    #[test]
    fn api_override_never_reuses_a_session_from_another_target() {
        let session = Session {
            api_url: "https://original.example".into(),
            session_id: "isolated".into(),
            cookies: std::collections::BTreeMap::new(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: "fixture-salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let resolved = resolve(
            ProfileOptions {
                api_url: Some("https://different.example".into()),
                ..Default::default()
            },
            ProfileEnvironment::default(),
            Path::new("/example"),
        )
        .unwrap();
        assert!(resolved.api_url(Some(&session), None).is_err());
        let resolved = resolve(
            ProfileOptions::default(),
            ProfileEnvironment::default(),
            Path::new("/example"),
        )
        .unwrap();
        assert_eq!(
            resolved
                .api_url(Some(&session), Some("https://installed.example"))
                .unwrap(),
            "https://original.example"
        );
        assert_eq!(
            resolved
                .api_url(None, Some("https://installed.example"))
                .unwrap(),
            "https://installed.example"
        );
    }
}
