//! Read-only source facets. Raw LIST requires no Project key. The separate name
//! facet uses the existing resolver/key policy and never decrypts metadata or
//! confers host/filesystem authority.
use super::*;
/// Canonical ID plus complete raw rows with only display_name decoded.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectSourcesDecodedNames {
    pub project_id: String,
    pub sources: Vec<Value>,
}
fn source_list_path(project: &str, filters: &ProjectFilters) -> Result<String> {
    if filters.personal && filters.team_id.is_some() {
        return Err(Error::Invalid("Choose Personal or a Team, not both."));
    }
    if let Some(team) = &filters.team_id {
        uuid(team)?;
    }
    if project.is_empty()
        || project.len() > 512
        || project.chars().any(char::is_control)
        || matches!(project, "." | "..")
    {
        return Err(Error::Invalid("Supply an exact Project ID."));
    }
    let encoded = url::form_urlencoded::byte_serialize(project.as_bytes())
        .collect::<String>()
        .replace('+', "%20");
    Ok(path(
        &format!("/v1/projects/{encoded}/sources"),
        filters.team_id.as_deref(),
        &[],
    ))
}
fn source_list_rows(response: Value) -> Result<Vec<Value>> {
    match response.get("sources") {
        None | Some(Value::Null) => Ok(vec![]),
        Some(Value::Array(_)) => match response {
            Value::Object(mut object) => match object.remove("sources") {
                Some(Value::Array(rows)) => Ok(rows),
                _ => Err(Error::Protocol),
            },
            _ => Err(Error::Protocol),
        },
        _ => Err(Error::Protocol),
    }
}
// Private scratch is wiped on any failed row or final original-scope check.
// Public output types keep their existing movable/serializable ownership.
struct DecodedSourceNames(Vec<Value>);
impl Drop for DecodedSourceNames {
    fn drop(&mut self) {
        for row in &mut self.0 {
            crate::model::zeroize_json(row);
        }
    }
}
impl std::ops::Deref for DecodedSourceNames {
    type Target = [Value];
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}
impl DecodedSourceNames {
    fn into_rows(mut self) -> Vec<Value> {
        std::mem::take(&mut self.0)
    }
}
fn decode_names(rows: Vec<Value>, key: &[u8; 32]) -> Result<DecodedSourceNames> {
    let mut rows = DecodedSourceNames(rows);
    for row in &mut rows.0 {
        let object = row.as_object_mut().ok_or(Error::Protocol)?;
        // TS decryptOptionalProjectField maps absent/empty or failed AES to "".
        // Invalid metadata remains entirely opaque.
        let name = match object.get("encrypted_display_name") {
            Some(Value::String(cipher)) => {
                crypto::decrypt_combined(cipher, key).unwrap_or_default()
            }
            // TS AES decoder catches malformed nonstring input and returns null.
            _ => String::new(),
        };
        object.insert("display_name".into(), Value::String(name));
    }
    Ok(rows)
}
impl Projects<'_> {
    /// Exact raw LIST; no Project resolution, Master key or metadata decrypt.
    pub async fn list_sources_raw(&mut self, project: &str) -> Result<Vec<Value>> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let route = source_list_path(project, &self.filters)?;
        let response = self.backend.request(Method::GET, &route, None, None).await;
        // Observe cancellation only after actual transport/header completion.
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        source_list_rows(response?)
    }
    /// Resolve once and decode names only, retaining complete raw source rows.
    pub async fn list_sources_decoded_names(
        &mut self,
        selector: &str,
    ) -> Result<ProjectSourcesDecodedNames> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let scope = match &self.backend {
            Backend::Cookie(client) => Some(client.begin_project_source_name_read()?),
            Backend::ApiKey(_) => None,
        };
        let project = self.resolve(selector).await?;
        if let (Some(scope), Backend::Cookie(client)) = (&scope, &self.backend) {
            scope.check(client)?;
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let rows = self.list_sources_raw(&project_id).await?;
        if let (Some(scope), Backend::Cookie(client)) = (&scope, &self.backend) {
            scope.check(client)?;
        }
        let sources = decode_names(rows, &project.key)?;
        if let (Some(scope), Backend::Cookie(client)) = (&scope, &self.backend) {
            scope.check(client)?;
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(ProjectSourcesDecodedNames {
            project_id,
            sources: sources.into_rows(),
        })
    }
}
impl OpenMates {
    /// Immutable explicit API-key raw LIST for the original foreign call driver.
    /// No CLI state, session setup or Master key is read.
    pub async fn list_project_sources_raw(
        &self,
        project: &str,
        filters: ProjectFilters,
    ) -> Result<Vec<Value>> {
        let cancel = self.operation_cancel_token();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let route = source_list_path(project, &filters)?;
        let response = self
            .task_request(Method::GET, &route, None, false, None)
            .await;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        source_list_rows(response?)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn raw_retains_unknown_fields_and_invalid_metadata_byte_values() {
        let rows = json!([{"source_id":"synthetic","encrypted_metadata":"not AES","a/b.c":{"__proto__":[true,1,null]}}]);
        assert_eq!(
            source_list_rows(json!({"sources":rows})).unwrap(),
            rows.as_array().unwrap().clone()
        );
        assert!(source_list_rows(json!({})).unwrap().is_empty());
        assert!(
            source_list_rows(json!({"sources":null}))
                .unwrap()
                .is_empty()
        );
        assert!(source_list_rows(json!({"sources":{}})).is_err());
    }
    #[test]
    fn names_never_decrypt_metadata_and_preserve_order_and_all_raw_fields() {
        let key = [9; 32];
        let cipher = crypto::server_fields::encrypt_text("Source 界", &key, &[]).unwrap();
        let rows = vec![
            json!({"encrypted_display_name":cipher,"encrypted_metadata":"invalid","status":"","extension":{"x":false}}),
            json!({"encrypted_display_name":"bad"}),
            json!({}),
        ];
        let result = decode_names(rows.clone(), &key).unwrap();
        for (before, after) in rows.iter().zip(result.iter()) {
            for (k, v) in before.as_object().unwrap() {
                assert_eq!(&after[k], v);
            }
        }
        assert_eq!(result[0]["display_name"], "Source 界");
        assert_eq!(result[1]["display_name"], "");
        assert_eq!(result[2]["display_name"], "");
        assert_eq!(
            decode_names(rows, &[42; 32]).unwrap()[0]["display_name"],
            ""
        );
        let malformed = vec![
            json!({"encrypted_display_name":true}),
            json!({"encrypted_display_name":7}),
            json!({"encrypted_display_name":[1,2]}),
            json!({"encrypted_display_name":{"bad":true}}),
        ];
        for row in decode_names(malformed, &key).unwrap().iter() {
            assert_eq!(row["display_name"], "");
        }
    }
    #[test]
    fn fixed_route_encodes_path_and_keeps_team_scope_without_query_injection() {
        let personal = ProjectFilters {
            personal: true,
            ..Default::default()
        };
        assert_eq!(
            source_list_path("a +?#/界", &personal).unwrap(),
            "/v1/projects/a%20%2B%3F%23%2F%E7%95%8C/sources"
        );
        assert!(source_list_path("..", &personal).is_err());
        assert!(
            source_list_path(
                "x",
                &ProjectFilters {
                    personal: true,
                    team_id: Some("11111111-1111-4111-8111-111111111111".into()),
                    ..Default::default()
                }
            )
            .is_err()
        );
    }
}
