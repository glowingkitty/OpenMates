//! spec: sdk.client.thin-platform-boundary
//! The single "may the answer body render this embed" rule (port of
//! `bodyMayShowEmbed` / `isSkillUseEmbedType` in the web `bodyEmbedPolicy.ts`).
//! Skill-invocation embeds (`app-skill-use`) never render inside the message
//! text; their result children do. Shells ask this before placing a card.

/// Whether `type_name` is a skill-invocation embed type (single or grouped).
pub fn is_skill_use_embed_type(type_name: &str) -> bool {
    matches!(
        type_name,
        "app-skill-use" | "app_skill_use" | "app-skill-use-group"
    )
}

/// Generated-media parent refs look like `generated-media-images-0123456789ab`.
fn is_generated_media_parent_ref(reference: &str) -> bool {
    let id = reference.strip_prefix("embed:").unwrap_or(reference).trim();
    let Some(rest) = id
        .to_ascii_lowercase()
        .strip_prefix("generated-media-")
        .map(str::to_owned)
    else {
        return false;
    };
    let Some((kind, hash)) = rest.rsplit_once('-') else {
        return false;
    };
    matches!(
        kind,
        "images" | "audio" | "music" | "videos" | "models3d" | "design"
    ) && hash.len() == 12
        && hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// May an authored answer-body reference render this embed? A known type
/// decides (anything but a skill invocation); with no type yet, a
/// generated-media parent ref is already recognisable as an invocation.
pub fn body_may_show_embed(embed_ref: Option<&str>, type_name: Option<&str>) -> bool {
    if let Some(type_name) = type_name.filter(|t| !t.is_empty()) {
        return !is_skill_use_embed_type(type_name);
    }
    match embed_ref {
        Some(reference) => !is_generated_media_parent_ref(reference),
        None => true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_type_decides() {
        assert!(!body_may_show_embed(Some("x"), Some("app-skill-use")));
        assert!(!body_may_show_embed(None, Some("app-skill-use-group")));
        assert!(body_may_show_embed(
            Some("generated-media-images-0123456789ab"),
            Some("image")
        ));
    }

    #[test]
    fn untyped_generated_media_parent_is_hidden() {
        assert!(!body_may_show_embed(
            Some("embed:generated-media-videos-0123456789AB"),
            None
        ));
        assert!(body_may_show_embed(
            Some("generated-media-images-short"),
            None
        ));
        assert!(body_may_show_embed(Some("some-slug"), None));
        assert!(body_may_show_embed(None, Some("")));
    }
}
