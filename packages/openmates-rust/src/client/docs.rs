//! Public documentation reads and authenticated Wikipedia proxy operations.
//! No filesystem, CLI profile, environment discovery or browser-origin bypass.
use super::*;
use serde::{Deserialize, Serialize};

const MAX_DOC_BYTES: usize = 16 * 1024 * 1024;
#[derive(Clone, Serialize, Deserialize)]
pub struct DocsTree {
    pub folders: Vec<DocsFolder>,
    pub files: Vec<DocsFile>,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct DocsFolder {
    pub path: String,
    pub title: String,
    pub folders: Vec<DocsFolder>,
    pub files: Vec<DocsFile>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocsFile {
    pub slug: String,
    pub title: String,
    pub filename: String,
    pub word_count: u64,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct DocsSearchResult {
    pub slug: String,
    pub title: String,
    pub snippet: String,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct WikipediaSearchResult {
    pub page_id: u64,
    pub key: String,
    pub title: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub disambiguation: bool,
    pub language: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct WikipediaRelatedArticle {
    pub title: String,
    pub canonical_title: String,
    pub language: String,
    pub description: String,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct WikipediaLearningBundle {
    pub canonical_title: String,
    pub language: String,
    pub source_url: String,
    pub questions: Vec<String>,
    pub related_articles: Vec<WikipediaRelatedArticle>,
    pub expires_in_seconds: u64,
}

/// Shared article projection for SDK and CLI adapters. No IO or inference.
/// Preserve summary extension fields and the exact canonical suggestion payload.
pub fn compose_wikipedia_article(mut summary:Value,guide:Option<&Value>)->Result<Value>{
 let article=summary.as_object_mut().ok_or(Error::Protocol)?;
 let (questions,related)=if let Some(guide)=guide{
  (guide.get("questions").ok_or(Error::Protocol)?.clone(),guide.get("related_articles").ok_or(Error::Protocol)?.clone())
 }else{(serde_json::json!([]),serde_json::json!([]))};
 article.insert("questions".into(),questions);article.insert("related_articles".into(),related);
 article.insert("suggestions_unavailable".into(),Value::Bool(guide.is_none()));Ok(summary)
}

/// Validate a server doc identifier before transport or local path projection.
pub fn validate_doc_slug(slug: &str) -> Result<()> {
    if slug.is_empty()
        || slug.len() > 4096
        || slug.contains("..")
        || slug.contains(['\\', ':', '\0'])
        || slug.starts_with('/')
        || slug.ends_with('/')
        || slug.chars().any(char::is_control)
        || slug.split('/').any(|part| part.is_empty() || part == ".")
    {
        return Err(Error::Invalid("Invalid document slug."));
    }
    Ok(())
}
impl Client {
    /// Public read: deliberately attaches no Cookie, bearer credential or Origin.
    pub async fn list_docs(&self) -> Result<DocsTree> {
        serde_json::from_str(&self.public_doc("/v1/docs").await?).map_err(|_| Error::Protocol)
    }
    pub async fn search_docs(&self, query: &str) -> Result<Vec<DocsSearchResult>> {
        if query.trim().is_empty() || query.chars().count() > 200 {
            return Err(Error::Invalid(
                "Documentation search requires 1–200 characters.",
            ));
        }
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("q", query)
            .finish();
        serde_json::from_str(&self.public_doc(&format!("/v1/docs/search?{query}")).await?)
            .map_err(|_| Error::Protocol)
    }
    /// Return Markdown bytes as UTF-8 text, not a JSON-quoted string.
    pub async fn get_doc(&self, slug: &str) -> Result<String> {
        validate_doc_slug(slug)?;
        // Form encoding uses '+' for spaces, which is literal in a URL path.
        let encoded = segment(slug).replace('+', "%20");
        self.public_doc(&format!("/v1/docs/{encoded}")).await
    }
    async fn public_doc(&self, path: &str) -> Result<String> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let request = self
            .http
            .get(self.url(path)?)
            .header("Accept", "text/markdown, application/json")
            .send();
        let mut response = tokio::select! {biased;_=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),response=request=>response.map_err(|_|Error::Offline)?};
        if !response.status().is_success() {
            return Err(match response.status().as_u16() {
                404 => Error::Invalid("Document not found."),
                400 | 422 => Error::Invalid("Invalid documentation request."),
                429 | 500..=599 => Error::Offline,
                _ => Error::Forbidden,
            });
        }
        if response
            .content_length()
            .is_some_and(|length| length > MAX_DOC_BYTES as u64)
        {
            return Err(Error::Protocol);
        }
        let mut bytes = Vec::new();
        loop {
            let chunk = tokio::select! {biased;_=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),chunk=response.chunk()=>chunk.map_err(|_|Error::Offline)?};
            let Some(chunk) = chunk else {
                break;
            };
            if bytes.len().saturating_add(chunk.len()) > MAX_DOC_BYTES {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        String::from_utf8(bytes).map_err(|_| Error::Protocol)
    }
    pub async fn search_wikipedia_titles(
        &mut self,
        query: &str,
        language: &str,
    ) -> Result<Vec<WikipediaSearchResult>> {
        self.require_session()?;
        let mut params = wikipedia_query("query", query, language)?;
        params.push_str("&limit=5");
        let response = self
            .request(Method::GET, &format!("/v1/wikipedia/search?{params}"), None)
            .await?;
        match response.get("results") {
            Some(Value::Array(_)) => {
                serde_json::from_value(response["results"].clone()).map_err(|_| Error::Protocol)
            }
            _ => Ok(vec![]),
        }
    }
    pub async fn wikipedia_summary(&mut self, title: &str, language: &str) -> Result<Value> {
        self.require_session()?;
        let params = wikipedia_query("title", title, language)?;
        let value = self
            .request(
                Method::GET,
                &format!("/v1/wikipedia/summary?{params}"),
                None,
            )
            .await?;
        if !value.is_object() {
            return Err(Error::Protocol);
        }
        Ok(value)
    }
    /// Canonical backend Learning Mode, with ordinary automatic model routing.
    pub async fn wikipedia_learning(
        &mut self,
        title: &str,
        language: &str,
    ) -> Result<WikipediaLearningBundle> {
        self.require_session()?;
        self.verify_private_operation()?;
        let params = wikipedia_query("title", title, language)?;
        serde_json::from_value(
            self.request(
                Method::GET,
                &format!("/v1/wikipedia/learning?{params}"),
                None,
            )
            .await?,
        )
        .map_err(|_| Error::Protocol)
    }
}
fn wikipedia_query(key: &str, topic: &str, language: &str) -> Result<String> {
    if topic.trim().is_empty()
        || topic.chars().count() > 300
        || !(2..=10).contains(&language.chars().count())
    {
        return Err(Error::Invalid(
            "Wikipedia requires a topic up to 300 characters and a valid language code.",
        ));
    }
    Ok(url::form_urlencoded::Serializer::new(String::new())
        .append_pair(key, topic)
        .append_pair("language", language)
        .finish())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    async fn mock(responses: Vec<(u16, String)>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let mut headers = vec![];
            for (status, body) in responses {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                while !bytes.windows(4).any(|part| part == b"\r\n\r\n") {
                    let mut chunk = [0; 4096];
                    let n = socket.read(&mut chunk).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&chunk[..n]);
                }
                headers.push(String::from_utf8(bytes).unwrap());
                socket.write_all(format!("HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            }
            headers
        });
        (base, server)
    }
    fn session(api: &str) -> Session {
        Session {
            api_url: api.into(),
            session_id: "private-session".into(),
            cookies: [("session".into(), "private-cookie".into())]
                .into_iter()
                .collect(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }
    }
    #[tokio::test]
    async fn public_docs_do_not_attach_stored_credentials_and_preserve_routes_and_text() {
        let(api,server)=mock(vec![(200,r#"{"folders":[],"files":[{"slug":"guide/start","title":"Guide","filename":"start.md","wordCount":4}]}"#.into()),(200,r#"[{"slug":"guide/start","title":"Guide","snippet":"private? public documentation"}]"#.into()),(200,"# Guide\nUnicode 界\n".into())]).await;
        let client = Client::new(&api, Some(session(&api))).unwrap();
        assert_eq!(client.list_docs().await.unwrap().files[0].word_count, 4);
        assert_eq!(client.search_docs("a & 界").await.unwrap().len(), 1);
        assert_eq!(
            client.get_doc("guide/my doc").await.unwrap(),
            "# Guide\nUnicode 界\n"
        );
        let headers = server.await.unwrap();
        assert!(headers[0].starts_with("GET /v1/docs HTTP/1.1"));
        assert!(headers[1].starts_with("GET /v1/docs/search?q=a+%26+%E7%95%8C HTTP/1.1"));
        assert!(headers[2].starts_with("GET /v1/docs/guide%2Fmy%20doc HTTP/1.1"));
        for header in headers {
            let header = header.to_lowercase();
            assert!(
                !header.contains("cookie:")
                    && !header.contains("authorization:")
                    && !header.contains("origin:")
                    && !header.contains("private-session")
            );
        }
    }
    #[tokio::test]
    async fn invalid_paths_and_unauthenticated_wiki_never_start_transport() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        // The canonical backend accepts UI locales, including underscores, and
        // normalizes unsupported values; the SDK does not invent a new allowlist.
        assert!(
            wikipedia_query("query", "Topic", "en_US")
                .unwrap()
                .contains("language=en_US")
        );
        for slug in [
            "../secret",
            "/absolute",
            "a/../b",
            "a\\b",
            "a//b",
            "x:y",
            "a\0b",
        ] {
            assert!(matches!(client.get_doc(slug).await, Err(Error::Invalid(_))));
        }
        assert!(matches!(
            client.search_docs("").await,
            Err(Error::Invalid(_))
        ));
        assert!(matches!(
            client.search_wikipedia_titles("Topic", "en").await,
            Err(Error::Authentication)
        ));
        assert!(matches!(
            client.wikipedia_summary("Topic", "en").await,
            Err(Error::Authentication)
        ));
        assert!(matches!(
            client.wikipedia_learning("Topic", "en").await,
            Err(Error::Authentication)
        ));
        client.set_operation_cancel({
            let token = CancellationToken::new();
            token.cancel();
            token
        });
        assert!(matches!(client.list_docs().await, Err(Error::Cancelled)));
    }
    #[tokio::test]
    async fn missing_and_oversized_docs_are_errors_not_markdown_or_partial_success() {
        let (api, server) = mock(vec![(404, "not found".into())]).await;
        let client = Client::new(&api, None).unwrap();
        assert!(matches!(
            client.get_doc("missing").await,
            Err(Error::Invalid(_))
        ));
        server.await.unwrap();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut b = [0; 4096];
            assert!(socket.read(&mut b).await.unwrap() > 0);
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        MAX_DOC_BYTES + 1
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
        });
        assert!(matches!(
            Client::new(&api, None).unwrap().get_doc("large").await,
            Err(Error::Protocol)
        ));
        server.await.unwrap();
    }
}
