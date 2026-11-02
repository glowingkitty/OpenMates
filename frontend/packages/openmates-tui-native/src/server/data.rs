//! Explicit data deletion is limited to volumes declared by this installation.
use super::*;
fn planned_volumes(c: &Configuration, cache_only: bool) -> Result<Vec<String>> {
    if c.server_role != "core" {
        return Err(Error::Invalid(
            "Selective user-data/cache reset requires a core installation.",
        ));
    }
    let raw = docker(c, ["config".into(), "--format".into(), "json".into()])?;
    let mut config: Value = serde_json::from_slice(&raw)?;
    let result = (|| {
        let volumes = config["volumes"].as_object().ok_or(Error::Protocol)?;
        let mut selected = vec![];
        for (key, volume) in volumes {
            let cache = key == "cache-data";
            let database = matches!(
                key.as_str(),
                "openmates-postgres-data" | "postgres-data" | "cms-database-data"
            );
            if !cache && (!database || cache_only) {
                continue;
            }
            if volume["external"].as_bool() == Some(true) {
                return Err(Error::Invalid(
                    "Selective reset refuses externally managed data volumes.",
                ));
            }
            let name = volume["name"]
                .as_str()
                .filter(|s| {
                    !s.is_empty()
                        && s.len() <= 255
                        && s.as_bytes()[0].is_ascii_alphanumeric()
                        && s.bytes()
                            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.'))
                })
                .ok_or(Error::Protocol)?;
            selected.push(name.to_owned());
        }
        if selected.is_empty() {
            return Err(Error::Invalid(
                "This installation declares no supported reset data volumes.",
            ));
        }
        let existing = run(
            "docker",
            &[
                "volume".into(),
                "ls".into(),
                "--format".into(),
                "{{.Name}}".into(),
            ],
            &c.install_path,
            None,
        )?;
        let existing = std::str::from_utf8(&existing)
            .map_err(|_| Error::Protocol)?
            .lines()
            .collect::<std::collections::BTreeSet<_>>();
        selected.retain(|s| existing.contains(s.as_str()));
        selected.sort();
        selected.dedup();
        Ok(selected)
    })();
    local_models::erase(&mut config);
    result
}
fn remove(c: &Configuration, volumes: Vec<String>) -> Result<()> {
    if volumes.is_empty() {
        return Ok(());
    }
    let mut args = vec!["volume".into(), "rm".into()];
    args.extend(volumes);
    run("docker", &args, &c.install_path, None)?;
    Ok(())
}
fn launch(c: &Configuration, selected: Vec<String>) -> Result<()> {
    docker(c, ["up".into(), "-d".into()].into_iter().chain(selected))?;
    Ok(())
}
fn stopped_change(
    c: &Configuration,
    volumes: Vec<String>,
    build: bool,
    selected: Vec<String>,
) -> Result<()> {
    let _critical = operation::critical()?;
    if docker(c, ["down".into()]).is_err() {
        let _ = launch(c, selected);
        return Err(Error::Invalid(
            "Could not stop the runtime for reset; a restart was attempted.",
        ));
    }
    let changed = (|| {
        remove(c, volumes)?;
        if build {
            docker(c, std::iter::once("build".into()).chain(selected.clone()))?;
        }
        launch(c, selected.clone())
    })();
    if changed.is_err() {
        let _ = launch(c, selected);
        return Err(Error::Invalid(
            "Reset or rebuild failed; a runtime restart was attempted. Inspect server status before retrying.",
        ));
    }
    Ok(())
}
pub(super) fn reset(c: &Configuration, user_only: bool) -> Result<()> {
    if !user_only {
        let _critical = operation::critical()?;
        docker(c, ["down".into(), "--volumes".into()])?;
        return Ok(());
    }
    let volumes = planned_volumes(c, false)?;
    let selected = services(c, &Flags::new())?;
    stopped_change(c, volumes, c.install_mode == "source", selected)
}
pub(super) fn rebuild(c: &Configuration, flags: &Flags) -> Result<()> {
    if c.install_mode != "source" {
        return Err(Error::Invalid("--rebuild applies only to source installs."));
    }
    let volumes = if boolean(flags, "reset-cache") {
        planned_volumes(c, true)?
    } else {
        vec![]
    };
    stopped_change(c, volumes, true, services(c, flags)?)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn call(c: &Configuration, tail: Vec<&str>, out: Value) -> fake::Call {
        let mut args = compose(c);
        args.extend(tail.into_iter().map(str::to_owned));
        fake::Call {
            program: "docker",
            args,
            output: Ok(serde_json::to_vec(&out).unwrap()),
        }
    }
    #[test]
    fn full_reset_stops_without_implicitly_restarting_or_deleting_source_files() {
        let c = super::super::tests::c();
        fake::with(
            vec![call(&c, vec!["down", "--volumes"], Value::Null)],
            || reset(&c, false).unwrap(),
        );
    }
    #[test]
    fn selective_reset_deletes_only_declared_existing_data_volumes_then_restarts() {
        let c = super::super::tests::c();
        let config = json!({"volumes":{"cache-data":{"name":"fixture-cache"},"openmates-postgres-data":{"name":"fixture-db"},"vault-data":{"name":"fixture-vault"}}});
        let mut up = compose(&c);
        up.extend(
            ["up".to_owned(), "-d".to_owned()]
                .into_iter()
                .chain(services(&c, &Flags::new()).unwrap()),
        );
        fake::with(
            vec![
                call(&c, vec!["config", "--format", "json"], config),
                fake::Call {
                    program: "docker",
                    args: vec!["volume", "ls", "--format", "{{.Name}}"]
                        .into_iter()
                        .map(str::to_owned)
                        .collect(),
                    output: Ok(b"fixture-cache\nfixture-db\nfixture-vault\nunrelated-db\n".to_vec()),
                },
                call(&c, vec!["down"], Value::Null),
                fake::Call {
                    program: "docker",
                    args: vec!["volume", "rm", "fixture-cache", "fixture-db"]
                        .into_iter()
                        .map(str::to_owned)
                        .collect(),
                    output: Ok(vec![]),
                },
                fake::Call {
                    program: "docker",
                    args: up,
                    output: Ok(vec![]),
                },
            ],
            || reset(&c, true).unwrap(),
        );
    }
    #[test]
    fn external_data_volume_is_rejected_before_stopping() {
        let c = super::super::tests::c();
        fake::with(
            vec![call(
                &c,
                vec!["config", "--format", "json"],
                json!({"volumes":{"cache-data":{"name":"external-cache","external":true}}}),
            )],
            || assert!(reset(&c, true).is_err()),
        );
    }
}
