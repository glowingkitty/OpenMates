//! API-key benchmark run/estimate (npm `client.benchmark`). Command handling for
//! `openmates benchmark ...` stays in the CLI; it calls these functions.
use crate::{OpenMates, Result};
use serde_json::Value;

pub struct Benchmark<'a> {
    client: &'a OpenMates,
}
impl<'a> Benchmark<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    pub async fn run(&self, input: Value) -> Result<Value> {
        self.client.post("/v1/sdk/benchmark/run", input).await
    }
    pub async fn estimate(&self, input: Value) -> Result<Value> {
        self.client.post("/v1/sdk/benchmark/estimate", input).await
    }
}
impl OpenMates {
    pub fn benchmark(&self) -> Benchmark<'_> {
        Benchmark::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ClientOptions, Error, SdkCredentials, SdkOptions};
    #[tokio::test]
    async fn anonymous_never_reaches_transport() {
        let anon = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic-bench-anon".into(),
            },
            device_id: "synthetic-bench-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert_eq!(
            anon.benchmark().run(serde_json::json!({})).await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anon.benchmark().estimate(serde_json::json!({})).await,
            Err(Error::Authentication)
        );
    }
}
