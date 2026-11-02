//! Bounded native YAML/file I/O. Portable policy remains in the SDK.
use super::*;
use openmates_sdk::work::{WORKFLOW_FILE_MAX_BYTES, WorkflowFileDocument, validate_workflow_file};
use std::{
    io::{Read, Write},
    path::Path,
};
fn extension(path: &str) -> Result<(), CliError> {
    if !path.ends_with(".workflow.yml") {
        return Err(CliError::Invalid(
            "Workflow files must use the .workflow.yml extension.".into(),
        ));
    }
    Ok(())
}
pub(super) fn read(path: &str, portable: bool) -> Result<String, CliError> {
    if portable {
        extension(path)?
    }
    let file = std::fs::File::open(path).map_err(|_| CliError::Client(Error::Io))?;
    let metadata = file.metadata().map_err(|_| CliError::Client(Error::Io))?;
    if !metadata.is_file() || metadata.len() > WORKFLOW_FILE_MAX_BYTES as u64 {
        return Err(CliError::Invalid(
            "Workflow source must be a regular file within the size limit.".into(),
        ));
    }
    let mut source = String::new();
    file.take(WORKFLOW_FILE_MAX_BYTES as u64 + 1)
        .read_to_string(&mut source)
        .map_err(|_| CliError::Invalid("Workflow source must contain UTF-8 text.".into()))?;
    if source.len() > WORKFLOW_FILE_MAX_BYTES {
        return Err(CliError::Invalid(
            "Workflow file exceeds the file size limit.".into(),
        ));
    }
    Ok(source)
}
pub(super) fn parse(source: &str) -> Result<WorkflowFileDocument, CliError> {
    if source.len() > WORKFLOW_FILE_MAX_BYTES {
        return Err(CliError::Invalid(
            "Workflow file exceeds the file size limit.".into(),
        ));
    }
    let value = super::yaml::parse(source)?;
    let graph = &value["workflow"]["graph"];
    if !graph["nodes"].is_array()
        || !graph["edges"].is_array()
        || graph.get("trigger_node_id").is_none()
        || graph["version"].as_u64().is_none_or(|version| version == 0)
        || graph["nodes"]
            .as_array()
            .is_some_and(|nodes| nodes.iter().any(|node| !node["config"].is_object()))
    {
        return Err(CliError::Invalid("Portable Workflow graph requires explicit nodes, edges, version, trigger and step configurations.".into()));
    }
    let document: WorkflowFileDocument = serde_json::from_value(value)
        .map_err(|_| CliError::Invalid("Invalid or unsupported portable Workflow YAML.".into()))?;
    validate_workflow_file(&document)?;
    Ok(document)
}
pub(super) fn filename(title:&str)->String{openmates_sdk::work::workflow_file_name(title)}
pub(super) fn write(path: &str, document: &WorkflowFileDocument) -> Result<(), CliError> {
    extension(path)?;
    let (_,source)=openmates_sdk::work::serialize_workflow_file(document).map_err(|error|match error{
        Error::Invalid("Workflow export exceeds the file size limit.")=>CliError::Invalid("Workflow export exceeds the file size limit.".into()),
        other=>CliError::Client(other),
    })?;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(Path::new(path))
        .map_err(|_| CliError::Client(Error::Io))?;
    file.write_all(source.as_bytes())
        .and_then(|()| file.sync_all())
        .map_err(|_| CliError::Client(Error::Io))
}
#[cfg(test)]
mod tests {
    use super::*;
    fn source() -> String {
        "format: openmates-workflow\nformat_version: 1\nworkflow:\n  title: Native\n  run_content_retention: last_5\n  graph:\n    version: 1\n    trigger_node_id: null\n    nodes: []\n    edges: []\nbinding_requirements: []\n".into()
    }
    #[test]
    fn portable_yaml_rejects_duplicates_private_fields_and_unknown_runtime_metadata() {
        let yaml = source();
        assert!(parse(&yaml).is_ok());
        assert!(parse(&yaml.replace("    trigger_node_id: null\n", "")).is_err());
        assert!(
            super::super::yaml::parse(&format!("value: {}end{}", "[".repeat(70), "]".repeat(70)))
                .is_err()
        );
        let expanded = format!(
            "first: &large {}\nsecond: *large\n",
            "a".repeat(WORKFLOW_FILE_MAX_BYTES / 2 + 1)
        );
        assert!(super::super::yaml::parse(&expanded).is_err());
        assert!(
            parse(&yaml.replace("  title: Native", "  title: Native\n  title: Replacement"))
                .is_err()
        );
        assert!(parse(&(yaml.clone() + "account_id: private\n")).is_err());
        assert!(
            parse(&yaml.replace(
                "nodes: []",
                "nodes: [{id: x, type: manual_trigger, config: {api_key: private}}]"
            ))
            .is_err()
        );
    }
    #[test]
    fn file_roundtrip_is_bounded_and_never_overwrites_an_existing_export() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory
            .path()
            .join(filename("../Native export"))
            .to_string_lossy()
            .to_string();
        let document = parse(&source()).ok().unwrap();
        write(&path, &document).ok().unwrap();
        assert!(write(&path, &document).is_err());
        let yaml = read(&path, true).ok().unwrap();
        assert_eq!(parse(&yaml).ok().unwrap().workflow.title, "Native");
        assert!(read(directory.path().to_str().unwrap(), false).is_err());
        assert!(read("anything.yml", true).is_err());
    }
}
