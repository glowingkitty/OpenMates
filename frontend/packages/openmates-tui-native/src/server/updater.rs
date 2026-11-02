//! Native continuous-updater unit planning; the application owns its async loop.
use super::*;
pub fn update_window_allows(window: &str, utc_minutes: u16) -> Result<bool> {
    let range = window
        .strip_suffix(" UTC")
        .ok_or(Error::Invalid("Update window must use HH:MM-HH:MM UTC."))?;
    let (a, b) = range
        .split_once('-')
        .ok_or(Error::Invalid("Update window must use HH:MM-HH:MM UTC."))?;
    fn minute(raw: &str) -> Result<u16> {
        let (h, m) = raw
            .split_once(':')
            .filter(|(h, m)| h.len() == 2 && m.len() == 2)
            .ok_or(Error::Invalid("Update window must use HH:MM-HH:MM UTC."))?;
        let h = h
            .parse::<u16>()
            .map_err(|_| Error::Invalid("Update window hour is invalid."))?;
        let m = m
            .parse::<u16>()
            .map_err(|_| Error::Invalid("Update window minute is invalid."))?;
        if h >= 24 || m >= 60 {
            return Err(Error::Invalid("Update window time is invalid."));
        }
        Ok(h * 60 + m)
    }
    let (a, b) = (minute(a)?, minute(b)?);
    if a == b || utc_minutes >= 24 * 60 {
        return Err(Error::Invalid(
            "Update window requires distinct UTC start and end times.",
        ));
    }
    Ok(if a < b {
        utc_minutes >= a && utc_minutes < b
    } else {
        utc_minutes >= a || utc_minutes < b
    })
}
fn plan(c: &Configuration, flags: &Flags, state: &Path, executable: &Path) -> Result<Value> {
    use std::os::unix::fs::MetadataExt;
    if !boolean(flags, "continuous") {
        return Err(Error::Invalid(
            "Use server update install-service --continuous.",
        ));
    }
    let channel = text(flags, "channel")
        .or(c.image_channel.as_deref())
        .unwrap_or("stable");
    if !matches!(channel, "stable" | "main" | "dev") {
        return Err(Error::Invalid("Image channel must be stable, main or dev."));
    }
    if c.install_mode == "source" && text(flags, "channel").is_some() {
        return Err(Error::Invalid(
            "--channel only applies to image-mode installs.",
        ));
    }
    let window = text(flags, "window").unwrap_or("02:00-04:00 UTC");
    update_window_allows(window, 0)?;
    let interval = text(flags, "interval")
        .map(|s| {
            s.parse::<u64>()
                .map_err(|_| Error::Invalid("Update interval must be at least 5 minutes."))
        })
        .transpose()?
        .unwrap_or(30);
    if !(5..=10080).contains(&interval) {
        return Err(Error::Invalid(
            "Update interval must be between 5 and 10080 minutes.",
        ));
    }
    let owner = std::fs::metadata(&c.install_path)?.uid();
    let exe = monitoring::systemd_quote(executable)?;
    let working = monitoring::systemd_quote(&c.install_path)?;
    let state = monitoring::systemd_quote(state)?;
    let service = format!("openmates-{}-continuous-update.service", c.server_role);
    let timer = format!("openmates-{}-continuous-update.timer", c.server_role);
    let unit = format!(
        "[Unit]\nDescription=OpenMates {} continuous updater\nAfter=docker.service network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nUser={owner}\nWorkingDirectory={working}\nExecStart={exe} --state-dir {state} server update --path {working} --role {} --continuous --interval {interval}{}\nEnvironment=\"OPENMATES_UPDATE_WINDOW={window}\"\nRestart=on-failure\nRestartSec=60\n",
        c.server_role,
        c.server_role,
        if c.install_mode == "image" {
            format!(" --channel {channel}")
        } else {
            String::new()
        }
    );
    let timer_unit = format!(
        "[Unit]\nDescription=Schedule OpenMates {} continuous updater\n\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec=30min\nPersistent=true\nUnit={service}\n\n[Install]\nWantedBy=timers.target\n",
        c.server_role
    );
    Ok(
        json!({"command":"update install-service","status":"planned","role":c.server_role,"serviceName":service,"timerName":timer,"servicePath":format!("/etc/systemd/system/{service}"),"timerPath":format!("/etc/systemd/system/{timer}"),"unit":unit,"timer":timer_unit,"window":window,"intervalMinutes":interval}),
    )
}
pub(super) fn install_service(c: &Configuration, flags: &Flags, state: &Path) -> Result<Value> {
    let executable = std::env::current_exe()?;
    let mut out = plan(c, flags, state, &executable)?;
    if boolean(flags, "dry-run") || boolean(flags, "json") {
        return Ok(out);
    }
    if !cfg!(target_os = "linux") {
        return Err(Error::Invalid(
            "Continuous updater service installation requires Linux systemd.",
        ));
    }
    let _strict = fs::strict_scope();
    fs::snapshot(&executable, 512 * 1024 * 1024)?;
    fs::directory(state, false)?;
    let service = PathBuf::from(out["servicePath"].as_str().ok_or(Error::Protocol)?);
    let timer = PathBuf::from(out["timerPath"].as_str().ok_or(Error::Protocol)?);
    let _lock = fs::HostLock::acquire(&service)?;
    let _critical = operation::critical()?;
    for (path, key) in [(&service, "unit"), (&timer, "timer")] {
        let before = if path.try_exists()? {
            Some(fs::host_snapshot(path, 1024 * 1024)?)
        } else {
            None
        };
        fs::write_identity(
            path,
            out[key].as_str().ok_or(Error::Protocol)?.as_bytes(),
            before.as_ref(),
        )?;
    }
    run_timeout(
        "systemctl",
        &["daemon-reload".into()],
        &c.install_path,
        None,
        std::time::Duration::from_secs(15),
    )?;
    let name = out["timerName"].as_str().ok_or(Error::Protocol)?;
    run_timeout(
        "systemctl",
        &["enable".into(), "--now".into(), name.into()],
        &c.install_path,
        None,
        std::time::Duration::from_secs(15),
    )?;
    run_timeout(
        "systemctl",
        &["is-active".into(), "--quiet".into(), name.into()],
        &c.install_path,
        None,
        std::time::Duration::from_secs(15),
    )?;
    out["status"] = json!("installed");
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn windows_handle_utc_boundaries_and_reject_injected_unit_text() {
        assert!(update_window_allows("02:00-04:00 UTC", 120).unwrap());
        assert!(!update_window_allows("02:00-04:00 UTC", 240).unwrap());
        assert!(update_window_allows("23:00-01:00 UTC", 30).unwrap());
        assert!(!update_window_allows("23:00-01:00 UTC", 700).unwrap());
        for invalid in [
            "2:00-4:00 UTC",
            "02:00-04:00 local",
            "24:00-04:00 UTC",
            "02:00-02:00 UTC",
            "02:00-04:00 UTC\nUser=root",
        ] {
            assert!(update_window_allows(invalid, 0).is_err())
        }
    }
    #[test]
    fn updater_plan_pins_binary_install_native_state_and_owner() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().join("source $x %work");
        fs::directory(&c.install_path, true).unwrap();
        let flags = Flags::from([("continuous".into(), json!(true))]);
        let planned = plan(
            &c,
            &flags,
            &dir.path().join("native-state"),
            Path::new("/trusted/openmates"),
        )
        .unwrap();
        let unit = planned["unit"].as_str().unwrap();
        assert!(unit.contains("/trusted/openmates"));
        assert!(unit.contains("--state-dir"));
        assert!(unit.contains("$$x %%work"));
        assert!(unit.contains("--channel stable"));
        assert!(!unit.contains("node"));
        c.install_mode = "source".into();
        assert!(
            !plan(&c, &flags, dir.path(), Path::new("/trusted/openmates")).unwrap()["unit"]
                .as_str()
                .unwrap()
                .contains("--channel")
        );
        assert!(
            plan(
                &c,
                &Flags::from([
                    ("continuous".into(), json!(true)),
                    ("interval".into(), json!("1"))
                ]),
                dir.path(),
                Path::new("/trusted/openmates")
            )
            .is_err()
        );
    }
}
