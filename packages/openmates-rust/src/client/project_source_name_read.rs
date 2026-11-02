//! Original Client resources for the name-only read. This private observer cannot
//! authorize a request, supply a key, or replace a Project row.
use super::{Client, Result, sync_capability::AsyncCryptoScope};
pub(crate) struct ProjectSourceNameReadScope(AsyncCryptoScope);
impl ProjectSourceNameReadScope {
    pub(crate) fn check(&self, client: &Client) -> Result<()> {
        self.0.check(client)
    }
}
impl Client {
    pub(crate) fn begin_project_source_name_read(&self) -> Result<ProjectSourceNameReadScope> {
        Ok(ProjectSourceNameReadScope(AsyncCryptoScope::begin(self)?))
    }
}
