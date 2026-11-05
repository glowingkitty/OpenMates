//! Owner-initiated exports and fragment-only share encryption. No decrypted key
//! is included in HTTP request bodies, query parameters, or local file metadata.
use super::*;
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use rand::{RngCore, rngs::OsRng};
use std::{io::Write, path::Path};
use zeroize::{Zeroize, Zeroizing};

impl Client {
    pub(crate) fn sdk_embed_share_blob(
        id: &str,
        key: &[u8; 32],
        expires: i64,
        password: &str,
    ) -> Result<String> {
        // SDK share methods historically accept arbitrary duration/password length;
        // chat CLI policy remains enforced by its existing wrapper.
        if id.is_empty() || id.chars().any(char::is_control) {
            return Err(Error::Invalid("Invalid embed ID."));
        }
        share_blob_for_kind("embed", id, key, expires, password, now_ms() / 1000)
    }
    pub async fn share_chat(
        &mut self,
        chat_id: &str,
        expires_in: u64,
        password: &str,
        include_sensitive: bool,
    ) -> Result<String> {
        validate_share_options(expires_in, password)?;
        self.open_chat_live(chat_id).await?;
        let row = self.chats.get(chat_id).ok_or(Error::Protocol)?.clone();
        let wrapping = self.wrapping_key().await?;
        let key = self.chat_key(&row, &wrapping)?;
        // Prepare the complete local blob before changing server share metadata.
        let blob = share_blob(chat_id, &key, expires_in, password, now_ms() / 1000)?;
        let response = self
            .request(
                Method::POST,
                "/v1/share/chat/metadata",
                Some(json!({
                    "chat_id":chat_id,"title":null,"summary":null,"share_cta_text":null,
                    "is_shared":true,"share_pii":include_sensitive,
                })),
            )
            .await?;
        if response["success"] != true {
            return Err(Error::Protocol);
        }
        Ok(format!(
            "{}/share/chat/{}#key={}",
            share_origin(&self.base)?,
            segment(chat_id),
            blob
        ))
    }

    /// Project files use `project_uuid/embed_uuid` as the explicit authority scope.
    pub async fn download(
        &mut self,
        workspace: Workspace,
        id: &str,
        destination: &Path,
        overwrite: bool,
    ) -> Result<()> {
        self.require_session()?;
        let target = Destination::new(destination, overwrite)?;
        let bytes = match workspace {
            Workspace::Chats => {
                // Live pagination must finish successfully before any export is written.
                let chat = self.open_chat_live(id).await?;
                Zeroizing::new(chat_markdown(&chat).into_bytes())
            }
            Workspace::Projects => {
                let (project_id, embed_id) = id
                    .split_once('/')
                    .or_else(|| id.split_once(':'))
                    .ok_or(Error::Invalid("Choose a Project file to download."))?;
                uuid::Uuid::parse_str(project_id)
                    .map_err(|_| Error::Invalid("Invalid Project ID."))?;
                uuid::Uuid::parse_str(embed_id)
                    .map_err(|_| Error::Invalid("Invalid Project file ID."))?;
                let path = self.scoped(&format!("/v1/projects/{}", segment(project_id)))?;
                let project = self.request(Method::GET, &path, None).await?;
                let row = project.get("project").ok_or(Error::Protocol)?;
                if required(row, "project_id")? != project_id {
                    return Err(Error::Forbidden);
                }
                let wrapping = self.wrapping_key().await?;
                let project_key = self.object_key(Workspace::Projects, row, &wrapping)?;
                let mut linked = false;
                for item in project["items"].as_array().ok_or(Error::Protocol)? {
                    if ["embed", "upload"].contains(&text(item, "item_type"))
                        && sync::decrypt_optional(item, "target_id_encrypted", &project_key)?
                            == embed_id
                    {
                        linked = true;
                    }
                }
                if !linked {
                    return Err(Error::Forbidden);
                }
                let path = self.scoped(&format!(
                    "/v1/embeds/{}/encrypted?project_id={}",
                    segment(embed_id),
                    segment(project_id)
                ))?;
                let response = self.request(Method::GET, &path, None).await?;
                let embed = response.get("embed").ok_or(Error::Protocol)?;
                if embed
                    .get("embed_id")
                    .and_then(Value::as_str)
                    .is_some_and(|id| id != embed_id)
                    || embed
                        .get("hashed_embed_id")
                        .and_then(Value::as_str)
                        .is_some_and(|hash| hash != sha256(embed_id))
                {
                    return Err(Error::Forbidden);
                }
                if embed
                    .get("version_number")
                    .is_some_and(|version| version.as_u64().is_none_or(|version| version == 0))
                {
                    return Err(Error::Protocol);
                }
                let wrapper = response["embed_keys"]
                    .as_array()
                    .ok_or(Error::Forbidden)?
                    .iter()
                    .find(|wrapper| {
                        text(wrapper, "key_type") == "project"
                            && wrapper
                                .get("hashed_project_id")
                                .and_then(Value::as_str)
                                .is_none_or(|hash| hash == sha256(project_id))
                    })
                    .ok_or(Error::Forbidden)?;
                let key = key_from_bytes(&crypto::decrypt_bytes(
                    required(wrapper, "encrypted_embed_key")?,
                    &project_key,
                )?)?;
                let plaintext = Zeroizing::new(crypto::decrypt_combined(
                    required(embed, "encrypted_content")?,
                    &key,
                )?);
                let payload = super::toon::decode(&plaintext)?;
                let source = project_file_source(&payload)?;
                Zeroizing::new(source.as_bytes().to_vec())
            }
            _ => {
                return Err(Error::Invalid(
                    "Downloads are available for chats and selected Project files.",
                ));
            }
        };
        target.write(&bytes)
    }
}

fn validate_share_options(duration: u64, password: &str) -> Result<()> {
    if ![0, 60, 3600, 86400, 604800, 1209600, 2592000, 7776000].contains(&duration) {
        return Err(Error::Invalid("Choose a supported share expiration."));
    }
    if password.encode_utf16().count() > 10 {
        return Err(Error::Invalid(
            "Share passwords are limited to ten characters.",
        ));
    }
    Ok(())
}
fn password_key(password: &str, salt: &[u8]) -> Key {
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(password.as_bytes(), salt, 100_000, key.as_mut());
    key
}
fn encrypt_share(plaintext: &[u8], key: &[u8; 32]) -> Result<String> {
    let mut iv = [0u8; 12];
    OsRng.fill_bytes(&mut iv);
    let mut bytes = iv.to_vec();
    bytes.extend(crypto::encrypt_aead(plaintext, key, &iv, &[])?);
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}
fn share_blob(
    chat_id: &str,
    key: &[u8; 32],
    duration: u64,
    password: &str,
    generated_at: u64,
) -> Result<String> {
    validate_share_options(duration, password)?;
    uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
    share_blob_for_kind(
        "chat",
        chat_id,
        key,
        duration as i64,
        password,
        generated_at,
    )
}
fn share_blob_for_kind(
    kind: &str,
    chat_id: &str,
    key: &[u8; 32],
    duration: i64,
    password: &str,
    generated_at: u64,
) -> Result<String> {
    let mut encoded = Zeroizing::new(crypto::encode_key(key));
    let pwd = if password.is_empty() {
        "0"
    } else {
        let salt = format!("openmates-pwd-{chat_id}");
        let wrapping = password_key(password, salt.as_bytes());
        let wrapped = encrypt_share(encoded.as_bytes(), &wrapping)?;
        encoded.zeroize();
        *encoded = wrapped;
        "1"
    };
    let serialized = Zeroizing::new(
        url::form_urlencoded::Serializer::new(String::with_capacity(1024))
            .append_pair(&format!("{kind}_encryption_key"), &encoded)
            .append_pair("generated_at", &generated_at.to_string())
            .append_pair("duration_seconds", &duration.to_string())
            .append_pair("pwd", pwd)
            .finish(),
    );
    let id_key = password_key(chat_id, b"openmates-share-v1");
    encrypt_share(serialized.as_bytes(), &id_key)
}
fn share_origin(base: &url::Url) -> Result<String> {
    let mut origin = base.clone();
    let hostname = base.host_str().ok_or(Error::Protocol)?;
    if let Some(rest) = hostname.strip_prefix("api.") {
        origin
            .set_host(Some(&format!("app.{rest}")))
            .map_err(|_| Error::Protocol)?;
    }
    origin.set_port(None).map_err(|_| Error::Protocol)?;
    origin.set_path("");
    origin.set_query(None);
    origin.set_fragment(None);
    Ok(origin.origin().ascii_serialization())
}
fn chat_markdown(chat: &Chat) -> String {
    let mut markdown = if chat.title.is_empty() {
        String::new()
    } else {
        format!("# {}\n\n", chat.title)
    };
    for message in &chat.messages {
        let sender = if message.role == "user" {
            "You"
        } else if message.sender.is_empty() {
            "Assistant"
        } else {
            &message.sender
        };
        markdown.push_str(&format!("## {sender}\n\n{}\n\n", message.content));
    }
    markdown
}
fn project_file_source(payload: &Value) -> Result<&str> {
    let source = payload
        .get("code")
        .filter(|value| !value.is_null())
        .or_else(|| payload.get("content"))
        .and_then(Value::as_str)
        .ok_or(Error::Invalid(
            "The selected Project item has no downloadable text file.",
        ))?;
    if source.len() > 16 * 1024 * 1024 || source.contains('\0') {
        return Err(Error::Invalid("Unsupported Project file content."));
    }
    Ok(source)
}

#[cfg(unix)]
type FileIdentity = (i128, u64, i128, i128, i128);
#[cfg(unix)]
fn file_identity(metadata: &rustix::fs::Stat) -> FileIdentity {
    (
        metadata.st_dev.into(),
        metadata.st_ino,
        metadata.st_size.into(),
        metadata.st_mtime.into(),
        metadata.st_mtime_nsec.into(),
    )
}
#[cfg(unix)]
struct Destination {
    directory: std::os::fd::OwnedFd,
    name: std::ffi::OsString,
    original: Option<FileIdentity>,
    overwrite: bool,
}
#[cfg(unix)]
impl Destination {
    fn new(path: &Path, overwrite: bool) -> Result<Self> {
        use rustix::fs::{CWD, Mode, OFlags, openat};
        use std::path::Component;
        if path.as_os_str().as_encoded_bytes().ends_with(b"/") {
            return Err(Error::Invalid("Choose an explicit destination file."));
        }
        let name = path
            .file_name()
            .filter(|n| !n.is_empty())
            .ok_or(Error::Invalid("Choose an explicit destination file."))?
            .to_owned();
        let mut directory = openat(
            CWD,
            ".",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(|_| Error::Io)?;
        for component in path.parent().unwrap_or(Path::new(".")).components() {
            let value = match component {
                Component::RootDir => Path::new("/"),
                Component::CurDir => continue,
                Component::ParentDir => Path::new(".."),
                Component::Normal(name) => Path::new(name),
                _ => return Err(Error::Invalid("Unsupported destination path.")),
            };
            directory = openat(
                &directory,
                value,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| {
                Error::Invalid("Destination directories must exist and contain no symbolic links.")
            })?;
        }
        let mut result = Self {
            directory,
            name,
            original: None,
            overwrite,
        };
        result.original = result.identity()?;
        if result.original.is_some() && !overwrite {
            return Err(Error::Invalid(
                "Destination exists. Confirm replacement before downloading.",
            ));
        }
        Ok(result)
    }
    fn identity(&self) -> Result<Option<FileIdentity>> {
        use rustix::fs::{AtFlags, FileType, statat};
        let metadata = match statat(&self.directory, &self.name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(m) => m,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(_) => return Err(Error::Io),
        };
        if FileType::from_raw_mode(metadata.st_mode) != FileType::RegularFile
            || metadata.st_nlink != 1
            || metadata.st_uid != rustix::process::getuid().as_raw()
        {
            return Err(Error::Invalid(
                "Destination must be an owned regular file without symbolic or hard links.",
            ));
        }
        Ok(Some(file_identity(&metadata)))
    }
    fn write(self, data: &[u8]) -> Result<()> {
        use rustix::fs::{AtFlags, Mode, OFlags, fsync, linkat, openat, renameat, unlinkat};
        let temporary = format!(".openmates-download-{}", uuid::Uuid::new_v4());
        let descriptor = openat(
            &self.directory,
            &temporary,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|_| Error::Io)?;
        let result = (|| {
            let mut file = std::fs::File::from(descriptor);
            file.write_all(data)?;
            file.sync_all()?;
            if self.identity()? != self.original {
                return Err(Error::Invalid(
                    "Destination changed. Review it before retrying.",
                ));
            }
            if self.original.is_some() {
                if !self.overwrite {
                    return Err(Error::Invalid("Confirm destination replacement."));
                }
                renameat(&self.directory, &temporary, &self.directory, &self.name)
                    .map_err(|_| Error::Io)?;
            } else {
                // Hard-link creation atomically refuses a concurrently-created target.
                linkat(
                    &self.directory,
                    &temporary,
                    &self.directory,
                    &self.name,
                    AtFlags::empty(),
                )
                .map_err(|_| Error::Invalid("Destination changed. Review it before retrying."))?;
                unlinkat(&self.directory, &temporary, AtFlags::empty()).map_err(|_| Error::Io)?;
            }
            fsync(&self.directory).map_err(|_| Error::Io)?;
            Ok(())
        })();
        let _ = unlinkat(&self.directory, &temporary, AtFlags::empty());
        result
    }
}
#[cfg(not(unix))]
struct Destination;
#[cfg(not(unix))]
impl Destination {
    fn new(_: &Path, _: bool) -> Result<Self> {
        Err(Error::Invalid(
            "Secure file downloads are unavailable on this platform.",
        ))
    }
    fn write(self, _: &[u8]) -> Result<()> {
        Err(Error::Invalid(
            "Secure file downloads are unavailable on this platform.",
        ))
    }
}

#[cfg(test)]
#[path = "../../tests/actions_unit/mod.rs"]
mod tests;
