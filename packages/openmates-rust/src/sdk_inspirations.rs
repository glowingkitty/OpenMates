//! API-key daily inspirations list (npm `client.inspirations`).
use crate::{OpenMates, Result, sdk_transport::with_query};
use serde_json::Value;

#[derive(Clone, Default)]
pub struct InspirationsOptions {
    pub language: Option<String>,
}
pub struct Inspirations<'a> {
    client: &'a OpenMates,
}
impl<'a> Inspirations<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    pub async fn list(&self, options: InspirationsOptions) -> Result<Value> {
        self.client.get(&inspirations_path(&options)).await
    }
}
fn inspirations_path(options: &InspirationsOptions) -> String {
    with_query(
        "/v1/sdk/inspirations",
        &[("lang", options.language.clone())],
    )
}
impl OpenMates {
    pub fn inspirations(&self) -> Inspirations<'_> {
        Inspirations::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn route_matches_npm() {
        assert_eq!(
            inspirations_path(&Default::default()),
            "/v1/sdk/inspirations"
        );
        assert_eq!(
            inspirations_path(&InspirationsOptions {
                language: Some("de".into())
            }),
            "/v1/sdk/inspirations?lang=de"
        );
    }
}
