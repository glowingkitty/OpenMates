//! Session effects of Project embed adoption: Project resolution and the
//! item-link request, shared with the hosted writer (rename, delete).
use super::*;

impl Projects<'_> {
    /// Cookie-only resolution of one Project plus its decoded settings.
    pub(in crate::work::projects) async fn hosted_project(
        &mut self,
        selector: &str,
    ) -> HostedResult<(String, Key, Value)> {
        self.hosted_client()?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let route = self.path(&format!("/v1/projects/{project_id}/settings"), &[]);
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let settings = super::super::decode_settings(&data["settings"], &project.key)?;
        Ok((project_id, project.key, settings))
    }

    /// One Project item-link request (adopt, rename, delete). A refusal whose
    /// body names a stable link code (`path_conflict`, `embed_already_linked`,
    /// …) becomes [`HostedFileError::Rejected`] with that code; other failures
    /// keep the core error.
    ///
    /// # Errors
    /// As described; cookie sessions only.
    pub(in crate::work::projects) async fn item_link_request(
        &mut self,
        method: Method,
        route: &str,
        body: Value,
    ) -> HostedResult<Value> {
        let client = self.hosted_client()?;
        client.clear_project_item_error();
        match client
            .request_task_headers(method, route, Some(body), None, None, None)
            .await
        {
            Ok(value) => Ok(value),
            Err(error) => match client.take_project_item_error() {
                Some(code) => Err(HostedFileError::Rejected(code.to_owned())),
                None => Err(HostedFileError::Core(error)),
            },
        }
    }

    /// The session client; hosted files are first-party session data only.
    pub(in crate::work::projects) fn hosted_client(&mut self) -> Result<&mut Client> {
        match &mut self.backend {
            Backend::Cookie(client) => Ok(client),
            Backend::ApiKey(_) => Err(Error::Unavailable {
                code: "hosted_project_files_unavailable",
                reason: "HOSTED_PROJECT_FILES_REQUIRE_COOKIE_SESSION",
            }),
        }
    }
}
