//! Single-request loopback recorder for wire vectors: captures the request line,
//! Authorization header and JSON body, then answers `{"ok":true}`. No network
//! beyond 127.0.0.1 and no real backend is ever contacted.
use serde_json::Value;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread::JoinHandle;

/// What the SDK actually sent for one vector.
pub struct Seen {
    pub method: String,
    pub path: String,
    pub authorization: Option<String>,
    pub body: Value,
}

fn read_request(listener: &TcpListener) -> Result<Seen, String> {
    let (mut stream, _) = listener.accept().map_err(|_| "accept")?;
    let (mut bytes, mut buffer) = (Vec::new(), [0u8; 4096]);
    let (end, length) = loop {
        let read = stream.read(&mut buffer).map_err(|_| "read")?;
        if read == 0 {
            return Err("request closed early".into());
        }
        bytes.extend_from_slice(&buffer[..read]);
        if let Some(end) = bytes.windows(4).position(|window| window == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&bytes[..end]).to_string();
            let length = head
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().ok())?
                })
                .unwrap_or(0);
            break (end + 4, length);
        }
    };
    while bytes.len() < end + length {
        let read = stream.read(&mut buffer).map_err(|_| "read body")?;
        if read == 0 {
            return Err("body closed early".into());
        }
        bytes.extend_from_slice(&buffer[..read]);
    }
    let head = String::from_utf8_lossy(&bytes[..end - 4]).to_string();
    let mut line = head.lines().next().unwrap_or_default().split(' ');
    let (method, path) = (
        line.next().unwrap_or_default().to_owned(),
        line.next().unwrap_or_default().to_owned(),
    );
    let authorization = head.lines().skip(1).find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("authorization")
            .then(|| value.trim().to_owned())
    });
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).map_err(|_| "JSON body")?
    };
    let reply = br#"{"ok":true}"#;
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        reply.len()
    );
    stream.write_all(head.as_bytes()).map_err(|_| "write")?;
    stream.write_all(reply).map_err(|_| "write")?;
    Ok(Seen {
        method,
        path,
        authorization,
        body,
    })
}

/// Bind an ephemeral loopback port and serve exactly one request.
pub fn serve_once() -> Result<(String, JoinHandle<Result<Seen, String>>), String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|_| "bind")?;
    let url = format!("http://{}", listener.local_addr().map_err(|_| "address")?);
    Ok((url, std::thread::spawn(move || read_request(&listener))))
}
