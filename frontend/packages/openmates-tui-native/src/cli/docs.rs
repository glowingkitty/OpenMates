//! Public Docs presentation/downloads and session-authenticated Wikipedia CLI.
//! HTTP and response decoding belong to the headless SDK.
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::client::{DocsFile, DocsFolder, DocsTree, validate_doc_slug};
use serde_json::json;
use std::{io::Write, path::Path};
use tokio_util::sync::CancellationToken;

const DOCS_HELP: &str = "Docs commands:\n  openmates docs list [--json]                   List all documentation\n  openmates docs search <query> [--json]         Search docs by keyword\n  openmates docs show <slug>                     Display a doc in the terminal\n  openmates docs download <slug> [--output <p>]  Download a doc as .md file\n  openmates docs download --all [--output <dir>] Download all docs\n\nNo login required — docs are public.\n\nExamples:\n  openmates docs list\n  openmates docs search \"encryption\"\n  openmates docs show user-guide/getting-started\n  openmates docs download architecture/core/security\n  openmates docs download --all --output ./docs\n\nNative downloads refuse existing files and symlinked directories. Choose a new --output path.";
const WIKI_HELP: &str = "Wikipedia commands:\n  openmates wiki search <query> [--language en] [--json]\n  openmates wiki show <canonical-title> [--language en] [--json]";
pub fn is_public(i: &Invocation) -> bool {
    i.path.first().is_some_and(|name| name == "docs")
        || wiki_help(i)
        // Informational settings answers (web-only notices) need no account.
        || super::account::is_info(i)
        // Device-local privacy model controls need no account either.
        || privacy_cmd::supported(i)
        // Revolut consent-url/exchange --dry-run are pure developer fallbacks.
        || super::account::connected_accounts::is_public(i)
}
#[path = "privacy_cmd.rs"]
mod privacy_cmd;
fn wiki_help(i: &Invocation) -> bool {
    i.path.first().is_some_and(|name| name == "wiki")
        && (i.path.len() == 1
            && (i.positionals.is_empty()
                || i.positionals.first().is_some_and(|value| value == "help"))
            || i.path.get(1).is_some_and(|value| value == "help"))
}
pub fn public_help(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if wiki_help(i) {
        return Some(Ok(CliOutput::text(WIKI_HELP)));
    }
    if i.path.first().is_some_and(|name| name == "wiki")
        && (i.path.len() == 1 || i.positionals.is_empty())
    {
        return Some(Err(argument(
            "Use openmates wiki search <query> or openmates wiki show <canonical-title>.",
        )));
    }
    if i.path.first().is_some_and(|name| name == "docs")
        && (i.path.len() == 1 && i.positionals.is_empty()
            || i.path.get(1).is_some_and(|value| value == "help"))
    {
        return Some(Ok(CliOutput::text(DOCS_HELP)));
    }
    None
}
fn argument(message: &str) -> CliError {
    CliError::Contract {
        code: "invalid_argument",
        message: message.into(),
    }
}
fn optional_text(text: String) -> CliOutput {
    if text.is_empty() {
        CliOutput {
            stdout: String::new(),
            stderr: String::new(),
            exit_code: 0,
        }
    } else {
        CliOutput::text(text)
    }
}
fn first<'a>(i: &'a Invocation, label: &str) -> Result<&'a str, CliError> {
    i.positionals
        .first()
        .map(String::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| argument(label))
}
fn tree_text(tree: &DocsTree) -> Result<String, CliError> {
    fn add(
        folders: &[DocsFolder],
        files: &[DocsFile],
        depth: usize,
        out: &mut String,
    ) -> Result<(), CliError> {
        if depth > 64 {
            return Err(Error::Protocol.into());
        }
        let prefix = "  ".repeat(depth);
        for folder in folders {
            out.push_str(&format!("{prefix}{}/\n", folder.title));
            add(&folder.folders, &folder.files, depth + 1, out)?;
        }
        for file in files {
            out.push_str(&format!("{prefix}  {} ({})\n", file.title, file.slug));
        }
        Ok(())
    }
    let mut text = String::new();
    add(&tree.folders, &tree.files, 0, &mut text)?;
    Ok(text)
}
fn slugs(tree: &DocsTree) -> Result<Vec<String>, CliError> {
    fn add(
        folders: &[DocsFolder],
        files: &[DocsFile],
        depth: usize,
        out: &mut Vec<String>,
    ) -> Result<(), CliError> {
        if depth > 64 || out.len().saturating_add(files.len()) > 10000 {
            return Err(Error::Protocol.into());
        }
        for file in files {
            validate_doc_slug(&file.slug)?;
            out.push(file.slug.clone());
        }
        for folder in folders {
            add(&folder.folders, &folder.files, depth + 1, out)?;
        }
        Ok(())
    }
    let mut out = vec![];
    add(&tree.folders, &tree.files, 0, &mut out)?;
    let mut unique = std::collections::BTreeSet::new();
    if out.iter().any(|slug| !unique.insert(slug)) {
        return Err(Error::Protocol.into());
    }
    Ok(out)
}
/// Root calls public Docs before credential access; Wiki network calls follow
/// ordinary session validation, trusted-account checks and credential persistence.
pub async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if let Some(help) = public_help(i) {
        return help;
    }
    if privacy_cmd::supported(i) {
        return privacy_cmd::execute(i);
    }
    if super::account::connected_accounts::is_public(i) {
        return super::account::connected_accounts::execute_public(i);
    }
    if let Some(notice) = super::account::web_only(i, &client.application_url()) {
        return notice;
    }
    client.set_operation_cancel(cancel.clone());
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    match i.command_path().as_str() {
        "docs list" => {
            super::handlers::flags(i, &[])?;
            let tree = client.list_docs().await?;
            if i.boolean("json") {
                CliOutput::json(&serde_json::to_value(tree).map_err(|_| Error::Protocol)?)
            } else {
                Ok(optional_text(tree_text(&tree)?))
            }
        }
        "docs search" => {
            super::handlers::flags(i, &[])?;
            let query = i.positionals.join(" ");
            let query = query.trim();
            if query.is_empty() {
                return Err(argument(
                    "Error: provide a search query. Usage: openmates docs search <query>",
                ));
            }
            let results = client.search_docs(query).await?;
            if i.boolean("json") {
                return CliOutput::json(
                    &serde_json::to_value(results).map_err(|_| Error::Protocol)?,
                );
            }
            if results.is_empty() {
                return Ok(CliOutput::text(format!("No results for \"{query}\".")));
            }
            let mut text = format!("Found {} result(s) for \"{query}\":\n\n", results.len());
            for result in results {
                text.push_str(&format!(
                    "  {}\n  {}\n  {}\n\n",
                    result.title, result.slug, result.snippet
                ));
            }
            Ok(CliOutput::text(text))
        }
        "docs show" => {
            super::handlers::flags(i, &[])?;
            let slug = first(
                i,
                "Error: provide a doc slug. Usage: openmates docs show <slug>",
            )?;
            // Legacy console.log(content) is raw Markdown even under --json.
            Ok(CliOutput::text(format!(
                "{}\n",
                client.get_doc(slug).await?
            )))
        }
        "docs download" => {
            super::handlers::flags(i, &["all", "output"])?;
            let output = super::task_input::text(i, "output")?;
            if i.boolean("all") {
                let tree = client.list_docs().await?;
                let slugs = slugs(&tree)?;
                let destination = output.unwrap_or("./openmates-docs");
                let mut bytes = 0usize;
                for (index, slug) in slugs.iter().enumerate() {
                    if cancel.is_cancelled() {
                        return Err(Error::Cancelled.into());
                    }
                    let content = client.get_doc(slug).await?;
                    bytes = bytes.saturating_add(content.len());
                    if bytes > 256 * 1024 * 1024 {
                        return Err(argument(
                            "Documentation batch exceeds the native 256 MiB limit; download individual documents.",
                        ));
                    }
                    write_download(
                        &Path::new(destination).join(format!("{slug}.md")),
                        content.as_bytes(),
                        true,
                    )?;
                    // Progress is stderr-only and carries no document content.
                    let _ = write!(
                        std::io::stderr(),
                        "\r  Downloaded {}/{}",
                        index + 1,
                        slugs.len()
                    );
                    let _ = std::io::stderr().flush();
                }
                if slugs.is_empty() {
                    create_download_directory(Path::new(destination))?;
                }
                let _ = writeln!(std::io::stderr());
                Ok(CliOutput::text(format!(
                    "Downloaded {} docs to {destination}/",
                    slugs.len()
                )))
            } else {
                let slug = first(
                    i,
                    "Error: provide a doc slug or --all to download everything.",
                )?;
                let content = client.get_doc(slug).await?;
                let default = format!("{}.md", slug.rsplit('/').next().unwrap_or(slug));
                let destination = output.unwrap_or(&default);
                write_download(Path::new(destination), content.as_bytes(), false)?;
                Ok(CliOutput::text(format!("Saved to {destination}")))
            }
        }
        "wiki search" | "wiki show" => wiki(i, client).await,
        _ => Err(argument(
            "Use openmates docs list/search/show/download or wiki search/show. Run the command with --help for usage.",
        )),
    }
}
async fn wiki(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    super::handlers::flags(i, &["language"])?;
    if i.has("api-key") {
        return Err(CliError::Unsupported{command:i.command_path(),reason:"API-key Wikipedia transport is not ported; use a session-authenticated CLI profile.".into()});
    }
    let topic = i.positionals.join(" ");
    if topic.is_empty() {
        return Err(argument(
            "Use openmates wiki search <query> or openmates wiki show <canonical-title>.",
        ));
    }
    let language = super::task_input::text(i, "language")?.unwrap_or("en");
    if i.path[1] == "search" {
        let results = client.search_wikipedia_titles(&topic, language).await?;
        if i.boolean("json") {
            return CliOutput::json(&json!({"results":results}));
        }
        let text = results
            .iter()
            .map(|result| {
                format!(
                    "{}{}{}",
                    result.title,
                    if result.disambiguation {
                        " (choose a specific article)"
                    } else {
                        ""
                    },
                    result
                        .description
                        .as_deref()
                        .filter(|value| !value.is_empty())
                        .map(|description| format!(" — {description}"))
                        .unwrap_or_default()
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        return Ok(optional_text(text));
    }
    let mut summary = client.wikipedia_summary(&topic, language).await?;
    let canonical = summary["title"]
        .as_str()
        .filter(|value| !value.is_empty())
        .unwrap_or(&topic)
        .to_owned();
    let suggestions = match client.wikipedia_learning(&canonical, language).await {
        Ok(value) => Some(value),
        Err(Error::Cancelled) => return Err(Error::Cancelled.into()),
        Err(_) => None,
    };
    let guide_value = suggestions.as_ref().map(serde_json::to_value).transpose().map_err(Error::from)?;
    summary = openmates_sdk::client::compose_wikipedia_article(summary, guide_value.as_ref())?;
    if i.boolean("json") {
        return CliOutput::json(&summary);
    }
    let mut text = format!(
        "{}\n{}\n\n{}\n\n{}\n",
        summary["title"].as_str().unwrap_or(""),
        summary["description"].as_str().unwrap_or(""),
        summary["extract"].as_str().unwrap_or(""),
        summary["source_url"].as_str().unwrap_or("")
    );
    if let Some(suggestions) = suggestions {
        text.push_str("\nRelated articles:\n");
        for article in suggestions.related_articles {
            text.push_str(&format!("- {}\n", article.title));
        }
        text.push_str("\nFollow-up questions:\n");
        for (index, question) in suggestions.questions.iter().enumerate() {
            text.push_str(&format!("{}. {question}\n", index + 1));
        }
    } else {
        text.push_str("\nArticle suggestions are temporarily unavailable. Try again shortly.\n");
    }
    Ok(CliOutput::text(text))
}

#[cfg(unix)]
fn directory(path: &Path, create: bool) -> Result<std::fs::File, CliError> {
    use rustix::fs::{Mode, OFlags};
    use std::path::Component;
    let mut directory =
        std::fs::File::open(if path.is_absolute() { "/" } else { "." }).map_err(|_| Error::Io)?;
    for component in path.components() {
        let name = match component {
            Component::RootDir | Component::CurDir => continue,
            Component::Normal(name) => name,
            Component::ParentDir => std::ffi::OsStr::new(".."),
            Component::Prefix(_) => return Err(Error::Forbidden.into()),
        };
        if create {
            match rustix::fs::mkdirat(&directory, name, Mode::RWXU) {
                Ok(()) => {}
                Err(rustix::io::Errno::EXIST) => {}
                Err(_) => return Err(Error::Io.into()),
            }
        }
        directory=std::fs::File::from(rustix::fs::openat(&directory,name,OFlags::RDONLY|OFlags::DIRECTORY|OFlags::NOFOLLOW|OFlags::CLOEXEC,Mode::empty()).map_err(|_|argument("Download directory is unavailable or contains a symlink; choose a real directory."))?);
    }
    Ok(directory)
}
#[cfg(unix)]
fn create_download_directory(path: &Path) -> Result<(), CliError> {
    directory(path, true)?
        .sync_all()
        .map_err(|_| Error::Io.into())
}
#[cfg(unix)]
fn write_download(path: &Path, bytes: &[u8], create_parents: bool) -> Result<(), CliError> {
    use rustix::fs::{Mode, OFlags};
    let name = path
        .file_name()
        .ok_or_else(|| argument("Provide a document filename for --output."))?;
    let parent = directory(
        path.parent().unwrap_or_else(|| Path::new(".")),
        create_parents,
    )?;
    let descriptor=rustix::fs::openat(&parent,name,OFlags::WRONLY|OFlags::CREATE|OFlags::EXCL|OFlags::NOFOLLOW|OFlags::CLOEXEC,Mode::RUSR|Mode::WUSR).map_err(|error|if error==rustix::io::Errno::EXIST {argument("Download destination exists. Native downloads do not overwrite files; choose a new --output path.")}else{CliError::Client(Error::Io)})?;
    let mut file = std::fs::File::from(descriptor);
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .and_then(|()| parent.sync_all())
        .map_err(|_| Error::Io.into())
}
#[cfg(not(unix))]
fn create_download_directory(_: &Path) -> Result<(), CliError> {
    Err(argument(
        "Secure native documentation downloads are not implemented on this platform.",
    ))
}
#[cfg(not(unix))]
fn write_download(_: &Path, _: &[u8], _: bool) -> Result<(), CliError> {
    Err(argument(
        "Secure native documentation downloads are not implemented on this platform.",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    fn invocation(path: &[&str], args: &[&str], flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: path.iter().map(|value| value.to_string()).collect(),
            positionals: args.iter().map(|value| value.to_string()).collect(),
            flags: flags
                .iter()
                .map(|(key, value)| (key.to_string(), value.clone()))
                .collect(),
        }
    }
    async fn mock(responses: Vec<(u16, String)>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let mut requests = vec![];
            for (status, body) in responses {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                while !bytes.windows(4).any(|part| part == b"\r\n\r\n") {
                    let mut part = [0; 4096];
                    let n = socket.read(&mut part).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&part[..n]);
                }
                requests.push(String::from_utf8(bytes).unwrap());
                socket.write_all(format!("HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            }
            requests
        });
        (api, server)
    }
    #[tokio::test]
    async fn public_show_and_download_preserve_raw_text_even_under_json() {
        let markdown = "# Native public document\nUnicode 界\n";
        let (api, server) = mock(vec![(200, markdown.into()), (200, markdown.into())]).await;
        let mut client = Client::new(&api, None).unwrap();
        let shown = execute(
            &invocation(
                &["docs", "show"],
                &["guide/start"],
                &[("json", json!(true))],
            ),
            &mut client,
            CancellationToken::new(),
        )
        .await
        .unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(shown.stdout, format!("{markdown}\n"));
        assert!(serde_json::from_str::<Value>(&shown.stdout).is_err());
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("chosen.md");
        let path = path.to_str().unwrap();
        let saved = execute(
            &invocation(
                &["docs", "download"],
                &["guide/start"],
                &[("json", json!(true)), ("output", json!(path))],
            ),
            &mut client,
            CancellationToken::new(),
        )
        .await
        .unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(saved.stdout, format!("Saved to {path}\n"));
        assert_eq!(std::fs::read_to_string(path).unwrap(), markdown);
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 2);
        assert!(
            requests
                .iter()
                .all(|header| !header.to_lowercase().contains("cookie:"))
        );
    }
    #[tokio::test]
    async fn wiki_show_keeps_summary_when_learning_is_unavailable_and_uses_session() {
        let(api,server)=mock(vec![(200,json!({"title":"Canonical topic","extract":"Public article","source_url":"https://example.org/article"}).to_string()),(503,"{}".into())]).await;
        let session = openmates_sdk::Session {
            api_url: api.clone(),
            session_id: "synthetic".into(),
            cookies: [("session".into(), "synthetic-cookie".into())]
                .into_iter()
                .collect(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let mut client = Client::new(&api, Some(session)).unwrap();
        let output = execute(
            &invocation(
                &["wiki", "show"],
                &["Requested", "topic"],
                &[("json", json!(true)), ("language", json!("en"))],
            ),
            &mut client,
            CancellationToken::new(),
        )
        .await
        .unwrap_or_else(|e| panic!("{e}"));
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["title"], "Canonical topic");
        assert_eq!(value["questions"], json!([]));
        assert_eq!(value["related_articles"], json!([]));
        assert_eq!(value["suggestions_unavailable"], true);
        let requests = server.await.unwrap();
        assert!(
            requests[0].starts_with(
                "GET /v1/wikipedia/summary?title=Requested+topic&language=en HTTP/1.1"
            )
        );
        assert!(
            requests[1].starts_with(
                "GET /v1/wikipedia/learning?title=Canonical+topic&language=en HTTP/1.1"
            )
        );
        assert!(requests.iter().all(|request| {
            request
                .to_lowercase()
                .contains("cookie: session=synthetic-cookie")
        }));
    }
    #[test]
    fn only_docs_and_wiki_help_are_public_and_help_is_text_even_with_json() {
        for path in [
            &["docs"][..],
            &["docs", "help"],
            &["wiki"],
            &["wiki", "help"],
        ] {
            let i = invocation(path, &[], &[("json", json!(true))]);
            assert!(is_public(&i));
            let output = public_help(&i)
                .unwrap()
                .unwrap_or_else(|error| panic!("{error}"));
            assert!(output.stdout.contains("commands:"));
            assert!(serde_json::from_str::<Value>(&output.stdout).is_err());
        }
        for action in ["search", "show"] {
            assert!(!is_public(&invocation(&["wiki", action], &["Topic"], &[])));
        }
        assert!(is_public(&invocation(
            &["docs", "show"],
            &["guide/start"],
            &[]
        )));
    }
    #[test]
    fn tree_display_and_download_order_follow_legacy_different_traversals() {
        let tree:DocsTree=serde_json::from_value(json!({"folders":[{"path":"folder","title":"Folder","folders":[],"files":[{"slug":"folder/nested","title":"Nested","filename":"nested.md","wordCount":2}]}],"files":[{"slug":"root","title":"Root","filename":"root.md","wordCount":1}]})).unwrap();
        assert_eq!(
            tree_text(&tree).unwrap_or_else(|e| panic!("{e}")),
            "Folder/\n    Nested (folder/nested)\n  Root (root)\n"
        );
        assert_eq!(
            slugs(&tree).unwrap_or_else(|e| panic!("{e}")),
            vec!["root", "folder/nested"]
        );
        let unsafe_tree:DocsTree=serde_json::from_value(json!({"folders":[],"files":[{"slug":"../escape","title":"x","filename":"x","wordCount":0}]})).unwrap();
        assert!(slugs(&unsafe_tree).is_err());
    }
    #[cfg(unix)]
    #[test]
    fn downloads_create_private_files_refuse_overwrite_and_never_follow_symlinks() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("new/sub/doc.md");
        write_download(&path, b"# Public\n", true).unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(std::fs::read(&path).unwrap(), b"# Public\n");
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert!(write_download(&path, b"changed", true).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"# Public\n");
        let outside = temp.path().join("outside");
        std::fs::create_dir(&outside).unwrap();
        let linked = temp.path().join("linked");
        symlink(&outside, &linked).unwrap();
        assert!(write_download(&linked.join("escape.md"), b"bad", true).is_err());
        assert!(!outside.join("escape.md").exists());
        let target = temp.path().join("target.md");
        std::fs::write(&target, "unchanged").unwrap();
        let link = temp.path().join("link.md");
        symlink(&target, &link).unwrap();
        assert!(write_download(&link, b"bad", false).is_err());
        assert_eq!(std::fs::read_to_string(&target).unwrap(), "unchanged");
    }
    #[tokio::test]
    async fn invalid_arguments_preserve_exit_one_and_do_not_use_an_authenticated_transport() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        for path in [
            &["docs", "search"][..],
            &["docs", "show"],
            &["docs", "download"],
            &["wiki", "search"],
        ] {
            let error = execute(
                &invocation(path, &[], &[]),
                &mut client,
                CancellationToken::new(),
            )
            .await
            .err()
            .unwrap();
            assert_eq!(error.exit_code(), 1);
        }
    }
}
