//! Team request paths and bodies (shared Rust core `work` op, slice 2: Teams).
//!
//! spec: specifications/features/teams#teams.lifecycle.encrypted-profiled
//!
//! Mirrors the request building of the web `teamService.ts` as ordered
//! [`Body`] steps. Plaintexts leave only as `encrypt` steps the page seals with
//! the Team key (`"team"`); the master-wrapped Team key, the name approval
//! token, the invite-key-sealed Team key and the uploaded file stay page
//! `slot`s, so no key bytes and no invite secret cross. JSON plaintexts are
//! written in the TS literal key order (they are encrypted byte for byte).

use serde_json::{Map, Value, json};

use super::teams::{default_profile_image_json, js_trim, number};
use super::{Body, Decision, input_text, member, object, refusal, search_params, template, truthy};
use crate::web_apps::encode_uri_component;

/// Runs one Team path or body op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "teamPath" => path(input),
        "teamMemberAvatarPath" => member_avatar_path(input),
        "teamNameApprovalBody" => name_approval(input),
        "teamCreateBody" => create(input),
        "teamNameUpdateBody" => name_update(input),
        "teamProfileMetadataBody" => profile_metadata(input),
        "teamProfileImageForm" => profile_image_form(input),
        "teamMemberRoleBody" => member_role(input),
        "teamMemberRemoveBody" => member_remove(input),
        "teamInvitePreviewBody" => invite_preview(input),
        "teamInviteAcceptBody" => invite_accept(input),
        "teamInviteDeclineBody" => invite_decline(input),
        "teamEmailInviteBody" => email_invite(input),
        "teamLinkInviteBody" => link_invite(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

impl Body {
    /// A plain object member written in this pair order: the page rebuilds it
    /// with `Object.fromEntries`, so the wire JSON keeps the TS literal order.
    fn object(&mut self, name: &str, pairs: &[(&str, Value)]) {
        let pairs: Vec<Value> = pairs.iter().map(|(k, v)| json!([k, v])).collect();
        self.0.push(json!([name, { "object": pairs }]));
    }
}

/// `encodeURIComponent(<input member>)` (a missing member reads `undefined`, as in TS).
fn enc(input: &Value, name: &str) -> String {
    encode_uri_component(&template(input.get(name)))
}

/// `/v1/teams/${encodeURIComponent(teamId)}`.
fn team_path(input: &Value) -> String {
    format!("/v1/teams/{}", enc(input, "team_id"))
}

fn timestamp(input: &Value) -> Result<Value, String> {
    member(input, "timestamp").cloned()
}

/// `timestamp + seconds` as a JS number.
fn later(input: &Value, seconds: f64) -> Result<Value, String> {
    let at = timestamp(input)?.as_f64().ok_or("bad_field:timestamp")?;
    Ok(number(at + seconds))
}

/// `value.trim().toLowerCase()` of a required string member.
fn lower_trim(input: &Value, name: &str) -> Result<String, String> {
    let value = member(input, name)?.as_str().ok_or_else(|| format!("bad_field:{name}"))?;
    Ok(js_trim(value).to_lowercase())
}

fn json_text(value: &Value) -> Result<String, String> {
    serde_json::to_string(value).map_err(|e| e.to_string())
}

/// `JSON.stringify(ownTeamMemberProfile())` for the page's current `username`.
fn member_profile_json(input: &Value) -> Result<String, String> {
    let username = match input.get("username") {
        None | Some(Value::Null) => "",
        Some(Value::String(name)) => js_trim(name),
        Some(_) => return Err("bad_field:username".into()),
    };
    let name = if username.is_empty() { "Team member" } else { username };
    Ok(format!(
        r##"{{"display_name":{},"avatar":{{"mode":"generated","icon_name":"mate","background_color":"#4d73ff"}}}}"##,
        json_text(&json!(name))?
    ))
}

/// GET/DELETE paths of the Team service (`route` names the TS call site).
fn path(input: &Value) -> Decision {
    let route = member(input, "route")?.as_str().ok_or("bad_field:route")?;
    let team = team_path(input);
    let path = match route {
        "team" => team,
        "members" | "invites" | "security" | "billing" | "storage" | "memories" => format!("{team}/{route}"),
        "storage_notice" => {
            let mut pairs = vec![("limit", "50".to_owned())];
            if truthy(input.get("after_unit_id")) {
                pairs.push(("after_unit_id", template(input.get("after_unit_id"))));
            }
            format!("{team}/storage/notice?{}", search_params(&pairs))
        }
        "invite_revoke" => format!("{team}/invites/{}/revoke", enc(input, "invite_id")),
        _ => return Err("bad_field:route".into()),
    };
    Ok(json!(path))
}

/// `loadTeamMemberAvatar`'s guard: the member's own Team avatar route, or `null`.
fn member_avatar_path(input: &Value) -> Decision {
    let member_record = object(input, "member")?;
    let user_id = member_record.get("user_id");
    if !truthy(user_id) {
        return Ok(Value::Null);
    }
    let expected = format!("/v1/teams/{}/members/{}/profile-image", template(input.get("team_id")), template(user_id));
    Ok(if member_record.get("profile_image_url") == Some(&json!(expected)) { json!(expected) } else { Value::Null })
}

/// `approveTeamName`.
fn name_approval(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("name", json!(lower_trim(input, "name")?));
    Ok(body.request("/v1/teams/name-approval".into(), "POST", Map::new()))
}

/// `createTeam`'s payload (`name_approval_token` and the wrapped Team key are page slots).
fn create(input: &Value) -> Decision {
    let team = object(input, "input")?;
    let name = js_trim(input_text(team, "name")?);
    if name.is_empty() {
        return Ok(refusal("Team name is required"));
    }
    let at = timestamp(input)?;
    let mut body = Body::default();
    body.value("team_id", member(input, "team_id")?.clone());
    body.encrypt("encrypted_name", name, "team");
    if truthy(team.get("description")) {
        body.encrypt("encrypted_description", input_text(team, "description")?, "team");
    }
    match team.get("profileImageMetadata") {
        // The page stringifies its own object, keeping the caller's key order.
        Some(metadata) if !metadata.is_null() => {
            body.encrypt_input("encrypted_profile_image_metadata", "profileImageMetadata", "team");
        }
        _ => body.encrypt("encrypted_profile_image_metadata", default_profile_image_json(), "team"),
    }
    body.encrypt("encrypted_member_profile", &member_profile_json(input)?, "team");
    body.slot("encrypted_team_key");
    body.encrypt("encrypted_zero_balance", "0", "team");
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    body.slot("name_approval_token");
    Ok(body.request("/v1/teams".into(), "POST", Map::new()))
}

/// `updateTeamName` (after the page's Team key check and name approval).
fn name_update(input: &Value) -> Decision {
    let name = member(input, "name")?.as_str().ok_or("bad_field:name")?;
    let mut body = Body::default();
    body.encrypt("encrypted_name", js_trim(name), "team");
    body.slot("name_approval_token");
    body.value("updated_at", timestamp(input)?);
    Ok(body.request(team_path(input), "PATCH", Map::new()))
}

/// `updateTeamProfileMetadata` (the page stringifies its own `metadata` object).
fn profile_metadata(input: &Value) -> Decision {
    let mut body = Body::default();
    body.encrypt_input("encrypted_profile_image_metadata", "metadata", "team");
    body.value("updated_at", timestamp(input)?);
    Ok(body.request(team_path(input), "PATCH", Map::new()))
}

/// `uploadTeamProfileImage`'s form fields in append order (`path` is the upload endpoint path).
fn profile_image_form(input: &Value) -> Decision {
    let team_id = member(input, "team_id")?;
    let image_url = format!("/v1/teams/{}/profile-image", template(Some(team_id)));
    let metadata = format!(
        r#"{{"version":1,"mode":"uploaded","image_url":{},"content_safety_status":"accepted","updated_at":{},"team_id":{}}}"#,
        json_text(&json!(image_url))?,
        json_text(&timestamp(input)?)?,
        json_text(team_id)?
    );
    let mut body = Body::default();
    body.value("team_id", team_id.clone());
    body.encrypt("encrypted_profile_image_metadata", &metadata, "team");
    body.slot("file");
    Ok(body.request("/v1/upload/team-profile-image".into(), "POST", Map::new()))
}

/// `updateTeamMemberRole`.
fn member_role(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("role", input.get("role").cloned().ok_or("missing_field:role")?);
    body.value("updated_at", timestamp(input)?);
    let path = format!("{}/members/{}", team_path(input), enc(input, "user_id"));
    Ok(body.request(path, "PATCH", Map::new()))
}

/// `removeTeamMember`.
fn member_remove(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("removed_at", timestamp(input)?);
    let path = format!("{}/members/{}/remove", team_path(input), enc(input, "user_id"));
    Ok(body.request(path, "POST", Map::new()))
}

fn invite_path(input: &Value, action: &str) -> String {
    format!("/v1/teams/invites/{}/{action}", enc(input, "invite_id"))
}

/// The invite preview request of `acceptTeamInviteFromFragment`.
fn invite_preview(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("verified_email", json!(lower_trim(input, "verified_email")?));
    Ok(body.request(invite_path(input, "preview"), "POST", Map::new()))
}

/// The accept request (the page re-wraps the Team key with its master key: `encrypted_team_key` slot).
fn invite_accept(input: &Value) -> Decision {
    let mut body = Body::default();
    body.slot("encrypted_team_key");
    body.encrypt("encrypted_member_profile", &member_profile_json(input)?, "team");
    body.value("verified_email", json!(lower_trim(input, "verified_email")?));
    body.value("accepted_at", timestamp(input)?);
    Ok(body.request(invite_path(input, "accept"), "POST", Map::new()))
}

/// `declineTeamInvite`.
fn invite_decline(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("verified_email", json!(lower_trim(input, "verified_email")?));
    body.value("declined_at", timestamp(input)?);
    Ok(body.request(invite_path(input, "decline"), "POST", Map::new()))
}

/// The `invite_key_kdf_context` literal (HKDF-SHA256 / AES-256-GCM, v1).
fn kdf_context(body: &mut Body, input: &Value) -> Result<(), String> {
    body.object(
        "invite_key_kdf_context",
        &[
            ("v", json!(1)),
            ("kdf", json!("HKDF-SHA256")),
            ("cipher", json!("AES-256-GCM")),
            ("team_id", member(input, "team_id")?.clone()),
            ("invite_id", member(input, "invite_id")?.clone()),
            ("origin", member(input, "origin")?.clone()),
        ],
    );
    Ok(())
}

/// `createTeamEmailInvite`'s payload; `recipient_email` is returned for the page's HKDF info.
fn email_invite(input: &Value) -> Decision {
    let email = lower_trim(input, "email")?;
    if email.is_empty() {
        return Ok(refusal("Recipient email is required"));
    }
    let role = member(input, "role")?;
    let hint = format!(r#"{{"recipient_email":{},"role":{}}}"#, json_text(&json!(email))?, json_text(role)?);
    let mut body = Body::default();
    body.value("invite_id", member(input, "invite_id")?.clone());
    body.value("role", role.clone());
    body.value("recipient_email", json!(email));
    body.encrypt("encrypted_recipient_hint", &hint, "team");
    body.slot("encrypted_invite_team_key");
    kdf_context(&mut body, input)?;
    body.value("created_at", timestamp(input)?);
    body.value("expires_at", later(input, 7.0 * 24.0 * 60.0 * 60.0)?);
    let mut extra = Map::new();
    extra.insert("recipient_email".into(), json!(email));
    Ok(body.request(format!("{}/invites", team_path(input)), "POST", extra))
}

/// `createTeamLinkInvite`'s payload (no recipient binding, one-day expiry).
fn link_invite(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("invite_id", member(input, "invite_id")?.clone());
    body.value("role", member(input, "role")?.clone());
    body.slot("encrypted_invite_team_key");
    kdf_context(&mut body, input)?;
    body.value("created_at", timestamp(input)?);
    body.value("expires_at", later(input, 24.0 * 60.0 * 60.0)?);
    Ok(body.request(format!("{}/invites", team_path(input)), "POST", Map::new()))
}
