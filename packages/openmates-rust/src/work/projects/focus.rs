//! Project focus for one chat (npm ensureProjectDefaultFocus +
//! activate/deactivate/current focus routes). The focus instructions are read
//! from the Project's encrypted settings; a missing default focus is generated
//! and stored encrypted with the Project key, like the legacy CLI.
use super::*;

impl Projects<'_> {
    /// The Project's decrypted default focus, generating and saving one when
    /// the Project has none yet. Returns `(project_id, project_name, focus)`.
    pub async fn ensure_default_focus(
        &mut self,
        selector: &str,
    ) -> Result<(String, String, ProjectDefaultFocus)> {
        let project = self.show(selector).await?;
        let id = string(&project, "project_id")?.to_owned();
        let name = project["name"].as_str().unwrap_or("").to_owned();
        let settings = self.settings(&id).await?;
        if !settings["default_focus"].is_null() {
            let focus: ProjectDefaultFocus =
                serde_json::from_value(settings["default_focus"].clone()).map_err(|_| {
                    Error::Invalid(
                        "The Project encrypted settings do not contain a valid default focus.",
                    )
                })?;
            validate_focus(&focus).map_err(|_| {
                Error::Invalid(
                    "The Project encrypted settings do not contain a valid default focus.",
                )
            })?;
            return Ok((id, name, focus));
        }
        let label = if name.trim().is_empty() {
            "Untitled project"
        } else {
            name.trim()
        };
        let focus = ProjectDefaultFocus {
            focus_id: uuid::Uuid::new_v4().to_string(),
            name: format!("Work on {label}"),
            instructions: format!(
                "Help with work in {label}. Follow the user's instructions and the Project's connected source guidance."
            ),
            source: "generated".into(),
        };
        let write_mode = if settings["write_mode"] == "always_ask" {
            ProjectWriteMode::AlwaysAsk
        } else {
            ProjectWriteMode::ApplyAndShow
        };
        self.update_settings(
            &id,
            ProjectSettingsPatch {
                write_mode: Some(write_mode),
                default_focus: Some(focus.clone()),
                ..Default::default()
            },
        )
        .await?;
        Ok((id, name, focus))
    }
    /// Activate the Project's default focus in one chat.
    pub async fn activate_focus(&mut self, selector: &str, chat_id: &str) -> Result<Value> {
        uuid(chat_id)?;
        let (id, _, focus) = self.ensure_default_focus(selector).await?;
        let route = self.path(&format!("/v1/projects/{id}/focus/activate"), &[]);
        let data = self
            .backend
            .request(
                Method::POST,
                &route,
                Some(json!({"chat_id":chat_id,"focus_id":focus.focus_id,"instruction":focus.instructions})),
                None,
            )
            .await?;
        data.get("focus")
            .filter(|f| f.is_object())
            .cloned()
            .ok_or(Error::Protocol)
    }
    /// The chat's active Project focus, if any.
    pub async fn active_focus(&mut self, chat_id: &str) -> Result<Value> {
        uuid(chat_id)?;
        let route = path(
            "/v1/projects/focus/current",
            None,
            &[("chat_id".into(), chat_id.into())],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        Ok(data.get("focus").cloned().unwrap_or(Value::Null))
    }
    pub async fn deactivate_focus(&mut self, chat_id: &str) -> Result<()> {
        uuid(chat_id)?;
        self.backend
            .request(
                Method::POST,
                "/v1/projects/focus/deactivate",
                Some(json!({"chat_id":chat_id})),
                None,
            )
            .await?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "focus_tests.rs"]
mod tests;
