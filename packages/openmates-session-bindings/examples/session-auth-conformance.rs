//! Positive auth through the actual bridge, using synthetic loopback transcripts.
use _native::{BindingError, SessionBridge};
use futures_util::future::join_all;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};

const CAPABILITY: &str = "session.password-totp-rotation.v1";
type Check<T> = Result<T, &'static str>;
macro_rules! require {
    ($condition:expr, $message:literal) => {
        if !$condition {
            return Err($message);
        }
    };
}
fn text(value: &Value) -> Check<&str> {
    value.as_str().ok_or("fixture string missing")
}
fn matching(
    actual: &Value,
    expected: &Value,
    captures: &mut BTreeMap<String, String>,
) -> Check<()> {
    if let Some(name) = expected.get("$capture_uuid") {
        let value = text(actual)?;
        let parsed = uuid::Uuid::parse_str(value).map_err(|_| "session id invalid")?;
        require!(
            parsed.get_version_num() == 4 && parsed.to_string() == value,
            "session id not UUID4"
        );
        require!(!captures.values().any(|v| v == value), "session id reused");
        captures.insert(text(name)?.to_owned(), value.to_owned());
    } else if let Some(name) = expected.get("$ref") {
        require!(
            captures.get(text(name)?).map(String::as_str) == actual.as_str(),
            "session id reference mismatch"
        );
    } else if let Some(object) = expected.as_object() {
        let actual = actual.as_object().ok_or("request object missing")?;
        require!(actual.len() == object.len(), "request keys mismatch");
        for (key, value) in object {
            matching(
                actual.get(key).ok_or("request key missing")?,
                value,
                captures,
            )?;
        }
    } else {
        require!(actual == expected, "request value mismatch");
    }
    Ok(())
}
async fn request(socket: &mut TcpStream) -> Check<(String, BTreeMap<String, String>, String)> {
    let mut bytes = Vec::new();
    let end = loop {
        require!(bytes.len() < 65536, "request too large");
        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            break end + 4;
        }
        let mut part = [0; 4096];
        let n = socket.read(&mut part).await.map_err(|_| "request read")?;
        require!(n > 0, "request incomplete");
        bytes.extend_from_slice(&part[..n]);
    };
    let headers = std::str::from_utf8(&bytes[..end]).map_err(|_| "request header encoding")?;
    let mut lines = headers.split("\r\n");
    let first = lines.next().ok_or("request line missing")?.to_owned();
    let headers: BTreeMap<String, String> = lines
        .filter_map(|line| {
            line.split_once(':')
                .map(|(key, value)| (key.to_ascii_lowercase(), value.trim().to_owned()))
        })
        .collect();
    let length = headers
        .get("content-length")
        .ok_or("request length missing")?
        .parse::<usize>()
        .map_err(|_| "request length invalid")?;
    require!(length < 65536, "request body too large");
    while bytes.len() < end + length {
        let mut part = [0; 4096];
        let n = socket
            .read(&mut part)
            .await
            .map_err(|_| "request body read")?;
        require!(n > 0, "request body incomplete");
        bytes.extend_from_slice(&part[..n]);
    }
    let body = String::from_utf8(bytes[end..end + length].to_vec())
        .map_err(|_| "request body encoding")?;
    Ok((first, headers, body))
}
async fn serve(listener: TcpListener, vector: Value) -> Check<usize> {
    let mut captures = BTreeMap::new();
    let steps = vector["steps"].as_array().ok_or("fixture steps missing")?;
    for step in steps {
        let (mut socket, _) = tokio::time::timeout(Duration::from_secs(60), listener.accept())
            .await
            .map_err(|_| "request timeout")?
            .map_err(|_| "request accept")?;
        let (first, headers, body) = request(&mut socket).await?;
        require!(
            first
                == format!(
                    "{} {} HTTP/1.1",
                    text(&step["method"])?,
                    text(&step["path"])?
                ),
            "request route mismatch"
        );
        require!(
            headers.get("x-openmates-sdk").map(String::as_str) == Some("rust"),
            "SDK identity mismatch"
        );
        require!(
            headers.get("origin").map(String::as_str) == vector["app_origin"].as_str(),
            "request origin mismatch"
        );
        require!(
            headers.get("cookie").map(String::as_str) == step["cookie"].as_str(),
            "cookie chain mismatch"
        );
        require!(headers.get("x-openmates-expected-principal").map(String::as_str)==step["expected_principal"].as_str(),"expected principal assertion mismatch");
        if !step["blocked_effect"].is_null(){require!(step["expected_principal"]!=step["authenticated_principal"]&&step["response"]["status"]==403,"unbound protected effect fixture");}
        require!(
            !headers.contains_key("authorization"),
            "unexpected bearer credential"
        );
        for field in ["password", "master_key", "email"] {
            require!(
                !body.contains(text(&vector["account"][field])?),
                "plaintext secret on auth wire"
            );
        }
        let body: Value = serde_json::from_str(&body).map_err(|_| "request JSON invalid")?;
        matching(&body, &step["body"], &mut captures)?;
        let response = &step["response"];
        let body = response["raw"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| response["json"].to_string());
        let mut raw = format!(
            "HTTP/1.1 {} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n",
            response["status"]
                .as_u64()
                .ok_or("response status missing")?,
            body.len()
        );
        for header in response["headers"]
            .as_array()
            .ok_or("response headers missing")?
        {
            raw.push_str(&format!("{}: {}\r\n", text(&header[0])?, text(&header[1])?));
        }
        raw.push_str("\r\n");
        raw.push_str(&body);
        socket
            .write_all(raw.as_bytes())
            .await
            .map_err(|_| "response write")?;
    }
    Ok(steps.len())
}
fn outcome(result: Result<(), BindingError>, expected: Option<&str>) -> Check<()> {
    match (result, expected) {
        (Ok(()), None) => Ok(()),
        (Err(error), Some(code))
            if error.code == code
                && !error
                    .message
                    .contains("synthetic-private-server-diagnostic") =>
        {
            Ok(())
        }
        _ => Err("native outcome mismatch"),
    }
}
async fn exercise(bridge: &SessionBridge, endpoint: &str, vector: &Value) -> Check<()> {
    let mut revision = 0;
    for action in vector["actions"]
        .as_array()
        .ok_or("fixture actions missing")?
    {
        let result = match text(&action["kind"])? {
            "login" => {
                let email=text(&vector["account"]["input_email"])?.to_owned();
                let password=text(&vector["account"]["password"])?.to_owned();
                let tfa=action["tfa"].as_str().map(str::to_owned);
                let login=if let Some(stay_logged_in)=action["stay_logged_in"].as_bool() {
                    bridge.login_password_with_options(email,password,tfa,
                        openmates_sdk::PasswordLoginOptions { stay_logged_in }).await
                } else {
                    bridge.login_password(email,password,tfa).await
                };
                match login {
                    Ok(user) => {
                        let user: Value =
                            serde_json::from_str(&user).map_err(|_| "user response invalid")?;
                        require!(
                            user["id"] == vector["account"]["owner_id"],
                            "login user mismatch"
                        );
                        Ok(())
                    }
                    Err(error) => Err(error),
                }
            }
            "validate" => bridge.validate_session().await,
            "validate_concurrently" => {
                let count = action["count"].as_u64().ok_or("refresh count missing")?;
                let results = join_all((0..count).map(|_| bridge.validate_session())).await;
                for result in results {
                    outcome(result, None)?;
                }
                Ok(())
            }
            "logout" => bridge.logout().await,
            _ => return Err("unsupported transcript action"),
        };
        outcome(result, action["error"].as_str())?;
        if action["snapshot"].is_null() {
            outcome(
                bridge.export_session(true).await.map(|_| ()),
                Some("authentication"),
            )?;
        } else {
            let raw = bridge
                .export_session(true)
                .await
                .map_err(|_| "export failed")?;
            let snapshot: Value = serde_json::from_str(&raw).map_err(|_| "export JSON invalid")?;
            let next = snapshot["revision"].as_u64().ok_or("revision missing")?;
            require!(next > revision, "credential revision did not advance");
            revision = next;
            let session = &snapshot["session"];
            require!(session["api_url"] == endpoint, "endpoint mismatch");
            require!(
                session["master_key"] == vector["account"]["master_key"],
                "unwrapped master key mismatch"
            );
            require!(
                session["cookies"] == json!({"auth_refresh_token":action["snapshot"]["token"]}),
                "exported cookie mismatch"
            );
            require!(
                session["ws_token"] == action["snapshot"]["ws_token"],
                "WS token mismatch"
            );
            require!(
                session["hashed_email"] == vector["account"]["hashed_email"]
                    && session["email_encryption_key"] == vector["account"]["email_key"],
                "email derivation mismatch"
            );
        }
    }
    outcome(bridge.validate_session().await, Some("authentication"))
}
async fn run_vector(vector: &Value) -> Check<Value> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|_| "listener bind")?;
    let endpoint = format!(
        "http://{}",
        listener.local_addr().map_err(|_| "listener address")?
    );
    let bridge = SessionBridge::new(&json!({"api_url":endpoint,"app_url":vector["app_origin"],"enhanced_privacy":false,"allow_private_operations":false}).to_string()).map_err(|_| "bridge construction")?;
    let server = tokio::spawn(serve(listener, vector.clone()));
    let checked = exercise(&bridge, &endpoint, vector).await;
    let closed = bridge.close().await.map_err(|_| "bridge close");
    if checked.is_err() {
        server.abort();
    }
    checked?;
    closed?;
    let consumed = server.await.map_err(|_| "mock task failed")??;
    require!(
        consumed
            == vector["steps"]
                .as_array()
                .ok_or("fixture steps missing")?
                .len(),
        "transcript not consumed"
    );
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
async fn run() -> Check<Value> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|index| args.get(index + 1))
            .ok_or("conformance option missing")
    };
    require!(
        option("--capability")? == CAPABILITY,
        "unsupported conformance capability"
    );
    let raw = std::fs::read(option("--fixture")?).map_err(|_| "fixture read")?;
    let fixture: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON invalid")?;
    let vectors = fixture["capabilities"][CAPABILITY]["vectors"]
        .as_array()
        .ok_or("fixture vectors missing")?;
    require!(!vectors.is_empty(), "fixture suite empty");
    let mut results = Vec::new();
    for vector in vectors {
        results.push(run_vector(vector).await?);
    }
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results}),
    )
}
#[tokio::main]
async fn main() {
    match tokio::time::timeout(Duration::from_secs(240), run()).await {
        Ok(Ok(result)) => println!("{result}"),
        _ => {
            eprintln!("Rust positive session auth conformance failed");
            std::process::exit(1);
        }
    }
}
