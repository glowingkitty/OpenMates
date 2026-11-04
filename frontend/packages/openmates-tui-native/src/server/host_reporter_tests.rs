//! Unit tests for `host_reporter.rs` (kept separate to respect the file size limit).
use super::super::fake;
use super::*;

// RFC 5737 / RFC 1918 / RFC 4193 documentation-style placeholders only.
const URL: &str = "https://172.16.50.10:8443/v1/host-report";

#[test]
fn collector_url_requires_https_private_literal_and_fixed_path() {
    assert_eq!(
        collector_address(URL).unwrap(),
        "172.16.50.10".parse::<IpAddr>().unwrap()
    );
    for ok in [
        "https://172.16.0.1/v1/host-report",
        "https://172.31.255.254:1/v1/host-report",
        "https://192.168.1.2:65535/v1/host-report",
        "https://[fd00::1]:8443/v1/host-report",
        "https://[fc00::2]/v1/host-report",
    ] {
        assert!(collector_address(ok).is_ok(), "{ok}");
    }
    for bad in [
        "http://172.16.50.10:8443/v1/host-report",
        "https://172.16.50.10:8443/v1/host-report/",
        "https://172.16.50.10:8443/v1/host-report?x=1",
        "https://172.16.50.10:8443/other",
        "https://172.16.50.10:8443",
        "https://user@172.16.50.10/v1/host-report",
        "https://collector.example/v1/host-report",
        "https://192.0.2.10/v1/host-report",
        "https://198.51.100.7:8443/v1/host-report",
        "https://203.0.113.9/v1/host-report",
        "https://127.0.0.1/v1/host-report",
        "https://169.254.1.1/v1/host-report",
        "https://172.32.0.1/v1/host-report",
        "https://0192.168.100.10/v1/host-report",
        "https://0xac.16.50.10/v1/host-report",
        "https://172.16.50.10:0/v1/host-report",
        "https://172.16.50.10:99999/v1/host-report",
        "https://172.16.50.10:/v1/host-report",
        "https://[2001:db8::1]/v1/host-report",
        "https://[fe80::1]/v1/host-report",
        "https://[::ffff:172.16.50.10]/v1/host-report",
        "https://[fd00::1%eth0]/v1/host-report",
        "https://172.16.50.10\n/v1/host-report",
    ] {
        assert!(collector_address(bad).is_err(), "{bad}");
    }
}

#[test]
fn rendered_conf_and_dropin_match_install_sh_contract() {
    let conf = render_conf("upload", URL);
    assert!(conf.contains("\nROLE=upload\n"));
    assert!(conf.contains(&format!("\nCOLLECTOR_URL={URL}\n")));
    assert!(conf.contains("\nDEPLOYED_IMAGES_FILE=/var/lib/openmates/deployed-images.json\n"));
    let parsed = parse_conf(&conf);
    assert_eq!(parsed["ROLE"], "upload");
    assert_eq!(parsed["COLLECTOR_URL"], URL);
    assert_eq!(
        render_dropin("172.16.50.10".parse().unwrap())
            .lines()
            .last(),
        Some("IPAddressAllow=172.16.50.10/32")
    );
    assert!(
        render_dropin("fd00::1".parse().unwrap())
            .contains("[Service]\nIPAddressAllow=fd00::1/128\n")
    );
    // install.sh stays the manual path; keep its paths and keys in step.
    // Extracted Cargo packages have no deployment tree (see catalog tests).
    let install_sh =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../deployment/host_reporter/install.sh");
    let Ok(script) = std::fs::read_to_string(install_sh) else {
        return;
    };
    for needle in [
        LIB_DIR,
        CONF_DIR,
        CONF_FILE,
        IMAGES_FILE,
        "collector-address.conf",
        "99openmates-host-report",
        "host_ed25519",
        "ROLE=",
        "COLLECTOR_URL=",
        "DEPLOYED_IMAGES_FILE=",
    ] {
        assert!(
            script.contains(needle),
            "install.sh no longer contains {needle}"
        );
    }
}

#[test]
fn embedded_units_keep_the_unprivileged_reporter_contract() {
    assert!(REPORTER_UNIT.contains("DynamicUser=yes"));
    assert!(REPORTER_UNIT.contains("IPAddressDeny=any"));
    assert!(REPORTER_UNIT.contains(&format!("--conf {CONF_FILE}")));
    assert!(REPORTER_UNIT.contains(&format!("signing-key:{KEY_FILE}")));
    assert!(FACTS_UNIT.contains(&format!(
        "{LIB_DIR}/openmates-host-reporter collect-privileged"
    )));
    assert!(TIMER_UNIT.contains("Unit=openmates-host-reporter.service"));
    assert!(APT_HOOK.contains("openmates-host-reporter.service"));
    assert!(SCRIPT.contains("def validate_collector_url"));
    let names = payload(&Layout::system())
        .into_iter()
        .map(|(path, _, mode)| (path, mode))
        .collect::<Vec<_>>();
    assert_eq!(
        names[0],
        (
            PathBuf::from("/usr/local/lib/openmates/host-reporter/openmates-host-reporter"),
            0o755
        )
    );
    assert_eq!(names.len(), 6);
}

#[test]
fn journal_outcome_is_classified_without_raw_text() {
    assert_eq!(
        push_outcome("a\nhost report delivered\n")["outcome"],
        "delivered"
    );
    let failed = push_outcome(
        "host report delivered\nopenmates-host-reporter: collector delivery failed (curl exit 7)\n",
    );
    assert_eq!(failed, json!({"outcome":"delivery_failed","curlExit":7}));
    assert_eq!(
        push_outcome("openmates-host-reporter: missing systemd credential x")["outcome"],
        "reporter_error"
    );
    assert_eq!(push_outcome("")["outcome"], "unknown");
}

#[test]
fn image_digests_prefer_matching_repository_and_fall_back_to_id() {
    let d = format!("sha256:{}", "a".repeat(64));
    let id = format!("sha256:{}", "b".repeat(64));
    let inspect = format!(
        "[\"ghcr.io/example/other@sha256:{}\",\"ghcr.io/example/api@{d}\"]|{id}",
        "c".repeat(64)
    );
    assert_eq!(
        image_digest("ghcr.io/example/api:tag", &inspect).unwrap(),
        d
    );
    assert_eq!(
        image_digest("local-build", &format!("null|{id}\n")).unwrap(),
        id
    );
    assert_eq!(
        repository("registry.example:5000/api:tag"),
        "registry.example:5000/api"
    );
    assert_eq!(
        repository("registry.example:5000/api"),
        "registry.example:5000/api"
    );
    assert!(image_digest("x", "[]|not-a-digest").is_err());
    let rows = compose_rows(b"{\"Image\":\"a\"}\n{\"Image\":\"b\"}\n").unwrap();
    assert_eq!(rows.len(), 2);
}

#[test]
fn install_writes_mirrored_layout_and_refresh_keeps_key_and_config() {
    let dir = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap();
    let layout = Layout {
        root: dir.path().into(),
    };
    ensure_dir(&layout.path(CONF_DIR), 0o700).unwrap();
    fs::write(&layout.path(KEY_FILE), b"fixture-private-key", 0o644).unwrap();
    let cert = b"-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n".to_vec();
    let install = Install {
        role: "core",
        url: URL,
        address: collector_address(URL).unwrap(),
        collector_cert: cert.clone(),
        collector_tls_cert: cert,
        enable: true,
    };
    let call = |program: &'static str, args: &[&str], output: &[u8]| fake::Call {
        program,
        args: args.iter().map(|a| (*a).to_owned()).collect(),
        output: Ok(output.to_vec()),
    };
    let key = layout.path(KEY_FILE);
    let key = key.to_str().unwrap();
    let output = fake::with(
        vec![
            call("openssl", &["x509", "-noout"], b""),
            call("openssl", &["x509", "-noout"], b""),
            call("systemctl", &["daemon-reload"], b""),
            call("systemctl", &["enable", "--now", TIMER], b""),
            call(
                "ssh-keygen",
                &["-y", "-f", key],
                b"ssh-ed25519 AAAAfixture openmates-host-report-core\n",
            ),
        ],
        || apply(&layout, &install).unwrap(),
    );
    assert_eq!(output["signingKeyGenerated"], false);
    assert!(
        output["registerCommand"].as_str().unwrap().ends_with(
            "--role core --pubkey \"ssh-ed25519 AAAAfixture openmates-host-report-core\""
        )
    );
    let mode = |p: &str| {
        std::fs::metadata(layout.path(p))
            .unwrap()
            .permissions()
            .mode()
            & 0o777
    };
    assert_eq!(mode(CONF_DIR), 0o700);
    assert_eq!(mode(KEY_FILE), 0o600);
    assert_eq!(mode(&format!("{LIB_DIR}/openmates-host-reporter")), 0o755);
    assert_eq!(mode(LIB_DIR), 0o755);
    let dropin =
        std::fs::read_to_string(layout.path(&format!("{DROPIN_DIR}/{DROPIN_FILE}"))).unwrap();
    assert!(dropin.ends_with("IPAddressAllow=172.16.50.10/32\n"));
    assert_eq!(read_conf(&layout).unwrap(), ("core".into(), URL.into()));
    std::fs::write(layout.path(&format!("{UNIT_DIR}/{TIMER}")), b"stale").unwrap();
    fake::with(vec![call("systemctl", &["daemon-reload"], b"")], || {
        refresh(&layout).unwrap()
    });
    assert_eq!(
        std::fs::read_to_string(layout.path(&format!("{UNIT_DIR}/{TIMER}"))).unwrap(),
        TIMER_UNIT
    );
    assert_eq!(
        std::fs::read(layout.path(KEY_FILE)).unwrap(),
        b"fixture-private-key"
    );
    fake::with(
        vec![
            call("systemctl", &["disable", "--now", TIMER], b""),
            call("systemctl", &["daemon-reload"], b""),
        ],
        || uninstall(&layout).unwrap(),
    );
    assert!(!layout.installed().unwrap());
    assert!(!layout.path(CONF_DIR).exists() && !layout.path(LIB_DIR).exists());
}
