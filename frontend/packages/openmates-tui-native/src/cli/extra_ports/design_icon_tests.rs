// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use openmates_sdk::Session;
use std::collections::BTreeMap;

fn test_session(api: &str) -> Session {
    Session {
        api_url: api.into(),
        session_id: "synthetic-design".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: "c2FsdA==".into(),
        email_encryption_key: None,
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}

const ICON: &str = r#"<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>"#;

fn plain(args: &[&str]) -> Invocation {
    let mut full = vec!["openmates", "apps", "design", "export-icon"];
    full.extend_from_slice(args);
    super::super::super::parse_from(full)
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}

#[test]
fn svg_path_resolution_matches_npm_validation() {
    assert_eq!(
        svg_path(None, Some("lucide"), Some("home")).ok().unwrap(),
        "/v1/apps/design/icons/iconify/lucide/home.svg"
    );
    assert_eq!(
        svg_path(Some(" /v1/apps/design/icons/iconify/a/b.svg "), None, None)
            .ok()
            .unwrap(),
        "/v1/apps/design/icons/iconify/a/b.svg"
    );
    for bad in [
        "/v1/other/a/b.svg",
        "/v1/apps/design/icons/iconify/a/../b.svg",
    ] {
        let error = svg_path(Some(bad), None, None).err().unwrap();
        assert_eq!(
            error.to_string(),
            "svgPath must be an OpenMates Design Iconify SVG path"
        );
    }
    assert_eq!(
        svg_path(None, Some("lucide"), None)
            .err()
            .unwrap()
            .to_string(),
        "Provide either svgPath or both prefix and name"
    );
    assert_eq!(
        svg_path(None, Some("lu/cide"), Some("home"))
            .err()
            .unwrap()
            .to_string(),
        "Icon prefix and name may contain only letters, numbers, dots, underscores, and dashes"
    );
}

#[test]
fn colors_are_validated_and_applied_like_npm() {
    assert_eq!(normalize_color(None).ok().unwrap(), None);
    assert_eq!(
        normalize_color(Some(" #111827 ")).ok().unwrap().as_deref(),
        Some("#111827")
    );
    assert_eq!(
        normalize_color(Some("red")).err().unwrap().to_string(),
        "Icon color must be a hex color such as #111827"
    );
    let colored = apply_color(ICON, Some("#ff0000")).ok().unwrap();
    assert!(colored.contains(r##"stroke="#ff0000""##));
    assert!(colored.contains(r##"<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ff0000" stroke-width="2" color="#ff0000">"##));
    let with_attr = r##"<svg color="blue" fill='currentColor'></svg>"##;
    assert_eq!(
        apply_color(with_attr, Some("#abc")).ok().unwrap(),
        r##"<svg color="#abc" fill='#abc'></svg>"##
    );
    assert_eq!(apply_color(ICON, None).ok().unwrap(), ICON);
}

#[test]
fn format_defaults_follow_the_output_extension() {
    assert_eq!(resolve_format(None, "a/home.PNG"), Format::Png);
    assert_eq!(resolve_format(None, "home.svg"), Format::Svg);
    assert_eq!(resolve_format(None, "home"), Format::Svg);
    assert_eq!(resolve_format(Some(Format::Svg), "home.png"), Format::Svg);
    assert!(parse_format(Some("gif")).is_err());
    assert_eq!(parse_format(Some("png")).ok().unwrap(), Some(Format::Png));
}

#[test]
fn png_rendering_honors_size_width_height_and_the_limit() {
    let default = render_png(ICON, None, None, None).ok().unwrap();
    assert_eq!(&default[..8], b"\x89PNG\r\n\x1a\n");
    let dimensions = |png: &[u8]| {
        (
            u32::from_be_bytes(png[16..20].try_into().unwrap()),
            u32::from_be_bytes(png[20..24].try_into().unwrap()),
        )
    };
    assert_eq!(dimensions(&default), (256, 256));
    assert_eq!(
        dimensions(&render_png(ICON, Some(64), None, None).ok().unwrap()),
        (64, 64)
    );
    assert_eq!(
        dimensions(&render_png(ICON, Some(64), Some(32), None).ok().unwrap()),
        (32, 32)
    );
    assert_eq!(
        dimensions(&render_png(ICON, None, None, Some(48)).ok().unwrap()),
        (48, 48)
    );
    assert_eq!(
        render_png(ICON, Some(5000), None, None)
            .err()
            .unwrap()
            .to_string(),
        "PNG size must be an integer from 1 to 4096"
    );
    assert!(render_png("<not svg", None, None, None).is_err());
}

#[test]
fn reference_parsing_and_flags_follow_npm() {
    let i = plain(&["lucide:home", "--output", "x.svg"]);
    assert_eq!(
        reference(&i).ok().unwrap(),
        (None, Some("lucide".into()), Some("home".into()))
    );
    let i = plain(&["--prefix", "lucide", "--name", "home", "--output", "x.svg"]);
    assert_eq!(
        reference(&i).ok().unwrap(),
        (None, Some("lucide".into()), Some("home".into()))
    );
    let i = plain(&["a:b:c", "--output", "x.svg"]);
    assert_eq!(
        reference(&i).err().unwrap().to_string(),
        "Icon reference must use prefix:name, such as lucide:home"
    );
    let i = plain(&[
        "--svg-path",
        "/v1/apps/design/icons/iconify/a/b.svg",
        "--output",
        "x",
    ]);
    assert_eq!(
        reference(&i).ok().unwrap().0.as_deref(),
        Some("/v1/apps/design/icons/iconify/a/b.svg")
    );
    assert_eq!(
        positive(&plain(&["--size", "64"]), "size").ok().unwrap(),
        Some(64)
    );
    for bad in ["0", "-1", "6.5", "07", "x"] {
        assert_eq!(
            positive(&plain(&["--size", bad]), "size")
                .err()
                .unwrap()
                .to_string(),
            "--size must be a positive integer",
            "{bad}"
        );
    }
}

#[tokio::test]
async fn export_fetches_the_svg_recolors_and_writes_png_and_svg() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let mut requests = vec![];
        for status in [200, 200, 404] {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = [0; 8192];
            let n = socket.read(&mut buffer).await.unwrap();
            requests.push(String::from_utf8_lossy(&buffer[..n]).into_owned());
            let body = if status == 200 { ICON } else { "" };
            socket.write_all(format!("HTTP/1.1 {status} X\r\nContent-Type: image/svg+xml\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    let directory = tempfile::tempdir().unwrap();
    let svg_out = directory.path().join("nested/home.svg");
    let png_out = directory.path().join("home.png");
    let mut client = Client::new(&api, Some(test_session(&api))).unwrap();
    let svg = export(
        SvgSource::Session(&mut client),
        svg_out.to_str().unwrap(),
        None,
        Some("#ff0000"),
        false,
        false,
        (None, None, None),
        (None, Some("lucide"), Some("home")),
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(svg.format, Format::Svg);
    assert!(
        std::fs::read_to_string(&svg_out)
            .unwrap()
            .contains(r##"stroke="#ff0000""##)
    );
    let png = export(
        SvgSource::Session(&mut client),
        png_out.to_str().unwrap(),
        None,
        None,
        false,
        false,
        (Some(32), None, None),
        (None, Some("lucide"), Some("home")),
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(png.format, Format::Png);
    assert_eq!(&std::fs::read(&png_out).unwrap()[..4], b"\x89PNG");
    let missing = export(
        SvgSource::Session(&mut client),
        directory.path().join("none.svg").to_str().unwrap(),
        None,
        None,
        false,
        false,
        (None, None, None),
        (None, Some("lucide"), Some("nope")),
    )
    .await;
    assert_eq!(
        missing.err().unwrap().to_string(),
        "Raw resource request failed with HTTP 404"
    );
    assert!(!directory.path().join("none.svg").exists());
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/apps/design/icons/iconify/lucide/home.svg "));
    assert!(
        requests[0]
            .to_ascii_lowercase()
            .contains("accept: image/svg+xml,application/octet-stream")
    );
    let palette = export(
        SvgSource::Session(&mut client),
        directory.path().join("p.svg").to_str().unwrap(),
        None,
        Some("#fff"),
        true,
        false,
        (None, None, None),
        (None, Some("a"), Some("b")),
    )
    .await;
    assert_eq!(
        palette.err().unwrap().to_string(),
        "Palette icons cannot be recolored unless allowPaletteRecolor is true"
    );
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn api_key_export_uses_the_sdk_route_with_bearer_and_rasterizes_png_locally() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut buffer = [0; 8192];
        let n = socket.read(&mut buffer).await.unwrap();
        socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: image/svg+xml\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{ICON}", ICON.len()).as_bytes()).await.unwrap();
        String::from_utf8_lossy(&buffer[..n]).into_owned()
    });
    let sdk = openmates_sdk::sdk::OpenMates::new(openmates_sdk::SdkOptions {
        api_url: api,
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let png_out = directory.path().join("home.png");
    let png = export(
        SvgSource::ApiKey(&sdk),
        png_out.to_str().unwrap(),
        None,
        Some("#ff0000"),
        false,
        false,
        (Some(16), None, None),
        (None, Some("lucide"), Some("home")),
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(png.format, Format::Png);
    assert_eq!(&std::fs::read(&png_out).unwrap()[..4], b"\x89PNG");
    let request = server.await.unwrap();
    assert!(request.starts_with("GET /v1/apps/design/icons/iconify/lucide/home.svg "));
    assert!(request.to_ascii_lowercase().contains("authorization: bearer sk-api-synthetic"));
    assert!(!request.to_ascii_lowercase().contains("cookie:"));
}
