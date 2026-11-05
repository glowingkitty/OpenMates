//! Explicit local approval intent; no foreign callback/file IO or authority DTO.
use super::*;
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct WorkflowFileSyncInput {
    pub(crate) workflow_id: String,
    pub(crate) expected_version: String,
    #[serde(default)]
    pub(crate) source_chat: Option<String>,
    #[serde(default)]
    pub(crate) approved_paths: Vec<String>,
}
impl WorkflowFileSyncInput {
    pub(super) fn validate(&self) -> Result<()> {
        if uuid::Uuid::parse_str(&self.workflow_id).is_err()
            || self.expected_version.is_empty()
            || self.expected_version.len() > 512
            || self.expected_version.chars().any(char::is_control)
            || self.approved_paths.len() > 64
            || self
                .source_chat
                .as_ref()
                .is_some_and(|s| s.is_empty() || s.len() > 512 || s.chars().any(char::is_control))
        {
            return Err(Error::Invalid("Invalid Workflow file synchronization input.").into());
        }
        let mut unique = std::collections::HashSet::new();
        for path in &self.approved_paths {
            if path.is_empty()
                || path.encode_utf16().count() > 2048
                || path.starts_with('/')
                || path.contains('\\')
                || path.chars().any(char::is_control)
                || path.split('/').any(|part| matches!(part, "" | "." | ".."))
                || !path.ends_with(".workflow.yml")
                || !unique.insert(path)
            {
                return Err(Error::Invalid(
                    "Supply distinct exact relative Workflow approval paths.",
                )
                .into());
            }
        }
        Ok(())
    }
    pub(super) async fn sync(
        self,
        client: &mut Client,
        filters: openmates_sdk::work::ProjectFilters,
    ) -> openmates_sdk::Result<Value> {
        let approved = self
            .approved_paths
            .into_iter()
            .collect::<std::collections::HashSet<_>>();
        let rows = client
            .projects()
            .with_filters(filters)
            .sync_workflow_files(
                &self.workflow_id,
                &self.expected_version,
                self.source_chat.as_deref(),
                openmates_sdk::work::serialize_workflow_file,
                move |path| {
                    let accepted = approved.contains(&path);
                    async move { Ok(accepted) }
                },
            )
            .await?;
        serde_json::to_value(rows).map_err(Error::from)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=cli.surface.semantic-parity,auth.secrets.lifecycle
    #[test]
    fn exact_approval_intent_schema_rejects_arbitrary_authority_and_ambiguous_paths() {
        let input = || WorkflowFileSyncInput {
            workflow_id: "11111111-1111-4111-8111-111111111111".into(),
            expected_version: "version-2".into(),
            source_chat: None,
            approved_paths: vec!["workflows/updated.workflow.yml".into()],
        };
        assert!(input().validate().is_ok());
        for path in [
            "../x.workflow.yml",
            "/x.workflow.yml",
            "a\\x.workflow.yml",
            "a//x.workflow.yml",
            "a/./x.workflow.yml",
            "x.yml",
            "x\n.workflow.yml",
        ] {
            let mut value = input();
            value.approved_paths = vec![path.into()];
            assert!(value.validate().is_err());
        }
        let mut value = input();
        value.approved_paths.push(value.approved_paths[0].clone());
        assert!(value.validate().is_err());
        let raw = r#"{"workflow_id":"11111111-1111-4111-8111-111111111111","expected_version":"v","approved_paths":[],"authenticated":true}"#;
        assert!(serde_json::from_str::<WorkflowFileSyncInput>(raw).is_err());
    }
}
