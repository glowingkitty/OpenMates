//! Multipart profile-image uploads to the upload origin (npm uploadService
//! `uploadProfileImage`/`uploadTeamProfileImage` and the client status
//! checks). Only the refresh-token cookie and the upload Origin are sent,
//! like npm. Embedded metadata is removed natively before upload; types npm
//! would need a non-native sanitizer for are refused.
use super::upload::{UploadError, multipart_body, upload_base_url, upload_origin};
use super::*;
use crate::upload_privacy::images::{PreparedUpload, prepare_upload};
use zeroize::Zeroizing;

pub const PROFILE_IMAGE_MAX_SIZE_BYTES: usize = 300 * 1024;
const UPLOAD_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const MAX_RESPONSE: usize = 1024 * 1024;

/// A successful profile upload plus whether metadata removal succeeded
/// (false means npm's "Could not remove embedded file metadata" warning).
pub struct ProfileImageUpload {
    pub result: Value,
    pub metadata_removed: bool,
}

/// npm `getProfileImageMime` (extension of the basename, lowercase).
pub fn profile_image_mime(filename: &str) -> std::result::Result<&'static str, UploadError> {
    match crate::upload_privacy::js_extname(filename)
        .to_ascii_lowercase()
        .as_str()
    {
        ".jpg" | ".jpeg" => Ok("image/jpeg"),
        ".png" => Ok("image/png"),
        _ => Err(UploadError::Rejected(
            "Profile images must be JPEG or PNG files.".into(),
        )),
    }
}

/// npm `prepareUpload` with native sanitizers only.
pub fn prepare_local_upload(
    bytes: Vec<u8>,
    filename: &str,
    mime: &str,
) -> std::result::Result<PreparedUpload, UploadError> {
    prepare_upload(bytes, filename, mime).map_err(|unavailable| {
        UploadError::Rejected(format!(
            "Native metadata removal is not available for {} uploads; convert the file to JPEG, PNG, WEBP, GIF or BMP first.",
            unavailable.mime_type
        ))
    })
}

/// npm form field: name escaping like the WHATWG FormData serializer and
/// CRLF-normalized value.
fn field_part(boundary: &str, name: &str, value: &str) -> String {
    let name = name
        .replace('"', "%22")
        .replace('\r', "%0D")
        .replace('\n', "%0A");
    let value = value
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .replace('\n', "\r\n");
    format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
}
/// Text fields first, then the `file` part, as npm appends them.
pub fn multipart_form(
    boundary: &str,
    fields: &[(&str, &str)],
    filename: &str,
    mime: &str,
    bytes: &[u8],
) -> Vec<u8> {
    let mut body = Vec::new();
    for (name, value) in fields {
        body.extend_from_slice(field_part(boundary, name, value).as_bytes());
    }
    body.extend_from_slice(&multipart_body(boundary, filename, mime, bytes));
    body
}

/// JavaScript `String(value)` for a JSON value inside an error message.
fn js_text(value: Option<&Value>) -> String {
    match value {
        None => "undefined".into(),
        Some(Value::String(text)) => text.clone(),
        Some(other) => other.to_string(),
    }
}
/// `data.detail ?? fallback`.
fn detail_or(data: &Value, fallback: String) -> String {
    match data.get("detail") {
        None | Some(Value::Null) => fallback,
        Some(detail) => js_text(Some(detail)),
    }
}

/// npm `uploadedTeamProfileImageMetadata`, serialized in JSON.stringify order.
pub fn uploaded_team_profile_image_metadata(team_id: &str, url: &str, now_seconds: u64) -> String {
    let text = |v: &str| Value::String(v.to_owned()).to_string();
    format!(
        "{{\"version\":1,\"mode\":\"uploaded\",\"image_url\":{},\"content_safety_status\":\"accepted\",\"updated_at\":{now_seconds},\"team_id\":{}}}",
        text(url),
        text(team_id)
    )
}

/// npm `encryptWithAesGcmCombined`: base64(IV || ciphertext+tag).
fn legacy_encrypt(bytes: &[u8], key: &[u8; 32]) -> Result<String> {
    use base64::Engine;
    use rand::RngCore;
    let mut iv = [0u8; 12];
    rand::rngs::OsRng.fill_bytes(&mut iv);
    let mut combined = iv.to_vec();
    combined.extend(crate::crypto::encrypt_aead(bytes, key, &iv, &[])?);
    Ok(base64::engine::general_purpose::STANDARD.encode(combined))
}

fn team_segment(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 256
        || matches!(value, "." | "..")
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
    {
        return Err(Error::Invalid("Invalid Team identifier."));
    }
    Ok(value)
}

/// npm profile-image response status checks.
fn check_status(data: &Value, team: bool) -> std::result::Result<(), UploadError> {
    let subject = if team {
        "Team profile image"
    } else {
        "Profile image"
    };
    match data.get("status").and_then(Value::as_str) {
        Some("rejected") => Err(UploadError::Rejected(detail_or(
            data,
            format!("{subject} rejected by content safety checks."),
        ))),
        Some("account_deleted") => Err(UploadError::Rejected(
            "Account deleted due to repeated profile image policy violations.".into(),
        )),
        Some("ok") if !team || data["url"].as_str().is_some_and(|u| !u.is_empty()) => Ok(()),
        _ => Err(UploadError::Rejected(detail_or(
            data,
            format!(
                "{subject} upload failed with status '{}'.",
                js_text(data.get("status"))
            ),
        ))),
    }
}

impl Client {
    /// npm `uploadProfileImageForm`: one multipart POST, no retries.
    pub(crate) async fn post_profile_form(
        &mut self,
        url: &str,
        fields: &[(&str, &str)],
        filename: &str,
        prepared: &PreparedUpload,
    ) -> std::result::Result<Value, UploadError> {
        let cookie = self.refresh_cookie()?;
        let origin = upload_origin(&self.base);
        let boundary = format!("----OpenMatesFormBoundary{}", uuid::Uuid::new_v4().simple());
        let body = Zeroizing::new(multipart_form(
            &boundary,
            fields,
            filename,
            &prepared.mime_type,
            &prepared.bytes,
        ));
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        let mut request = self
            .http
            .post(url)
            .timeout(UPLOAD_TIMEOUT)
            .header("Origin", &origin)
            .header(
                "Content-Type",
                format!("multipart/form-data; boundary={boundary}"),
            )
            .body(body.to_vec());
        if let Some(cookie) = &cookie {
            request = request.header(reqwest::header::COOKIE, cookie.as_str());
        }
        let mut response = request.send().await.map_err(|_| Error::Offline)?;
        let status = response.status();
        if status.is_redirection() {
            return Err(Error::Forbidden.into());
        }
        let mut bytes = Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if bytes.len() + chunk.len() > MAX_RESPONSE {
                return Err(Error::Protocol.into());
            }
            bytes.extend_from_slice(&chunk);
        }
        // `response.json().catch(() => ({}))`
        let data = serde_json::from_slice::<Value>(&bytes).unwrap_or_else(|_| json!({}));
        let has_status = !matches!(data.get("status"), None | Some(Value::Null))
            && data["status"] != json!("")
            && data["status"] != json!(false)
            && data["status"] != json!(0);
        if !status.is_success() && !has_status {
            return Err(UploadError::Rejected(detail_or(
                &data,
                format!("Profile image upload failed (HTTP {}).", status.as_u16()),
            )));
        }
        Ok(data)
    }

    /// npm `updateProfileImage(filePath)` given the file's basename and bytes.
    pub async fn upload_profile_image(
        &mut self,
        filename: &str,
        bytes: Vec<u8>,
    ) -> std::result::Result<ProfileImageUpload, UploadError> {
        self.require_session()?;
        let mime = profile_image_mime(filename)?;
        if bytes.len() > PROFILE_IMAGE_MAX_SIZE_BYTES {
            return Err(UploadError::Rejected(
                "Profile image must be 300 KB or smaller. Resize/compress the image and try again."
                    .into(),
            ));
        }
        let prepared = prepare_local_upload(bytes, filename, mime)?;
        let url = format!("{}/v1/upload/profile-image", upload_base_url(&self.base));
        let result = self
            .post_profile_form(&url, &[], filename, &prepared)
            .await?;
        check_status(&result, false)?;
        Ok(ProfileImageUpload {
            result,
            metadata_removed: prepared.sanitized,
        })
    }

    /// npm `updateTeamProfileImage`: the Team key encrypts the uploaded image
    /// metadata, then the refreshed Team record is returned with the URL.
    pub async fn upload_team_profile_image(
        &mut self,
        team_id: &str,
        filename: &str,
        bytes: Vec<u8>,
    ) -> std::result::Result<ProfileImageUpload, UploadError> {
        let team_id = team_segment(team_id)?;
        let key = self
            .teams()
            .key(team_id)
            .await
            .map_err(|error| match error {
                Error::Invalid(message) if message == "Unable to load the Team key." => {
                    UploadError::Rejected(
                        "Unable to load local team key for encrypted team profile image update."
                            .into(),
                    )
                }
                other => UploadError::Client(other),
            })?;
        let proxy = format!("/v1/teams/{team_id}/profile-image");
        let metadata = Zeroizing::new(uploaded_team_profile_image_metadata(
            team_id,
            &proxy,
            crate::work::now(),
        ));
        let encrypted = legacy_encrypt(metadata.as_bytes(), &key)?;
        let mime = profile_image_mime(filename)?;
        if bytes.len() > PROFILE_IMAGE_MAX_SIZE_BYTES {
            return Err(UploadError::Rejected(
                "Profile image must be 300 KB or smaller. Resize/compress the image and try again."
                    .into(),
            ));
        }
        let prepared = prepare_local_upload(bytes, filename, mime)?;
        let url = format!(
            "{}/v1/upload/team-profile-image",
            upload_base_url(&self.base)
        );
        let fields = [
            ("team_id", team_id),
            ("encrypted_profile_image_metadata", encrypted.as_str()),
        ];
        let uploaded = self
            .post_profile_form(&url, &fields, filename, &prepared)
            .await?;
        check_status(&uploaded, true)?;
        let team = self.teams().get(team_id).await?;
        Ok(ProfileImageUpload {
            result: json!({"status": uploaded["status"], "url": uploaded["url"], "team": team}),
            metadata_removed: prepared.sanitized,
        })
    }
}

#[cfg(test)]
#[path = "profile_upload_tests.rs"]
mod tests;
