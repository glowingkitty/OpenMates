//! Thin explicit-key CLI adapter. The SDK owns requests, owner checks and polling.
//! Cookie/profile historical keys and sharing parity remain required gaps.
use super::{CliError, CliOutput, Invocation};
use crate::error::Error;
use openmates_sdk::{
    sdk::OpenMates,
    sdk_embeds::{PreviewStartError, PreviewStartOptions},
};
use serde_json::Value;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

pub fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "embeds versions list"
            | "embeds versions show"
            | "embeds test-result"
            | "embeds versions restore"
            | "embeds preview start"
            | "embeds preview status"
            | "embeds preview open"
            | "embeds preview stop"
    )
}
fn argument(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
fn first(i: &Invocation) -> Result<&str, CliError> {
    i.positionals
        .first()
        .map(String::as_str)
        .filter(|id| !id.is_empty())
        .ok_or_else(|| {
            argument(format!(
                "Missing embed or session ID for {}.",
                i.command_path()
            ))
        })
}
// Existing versions uses parseInt(value, 10): preserve its decimal prefix,
// including '+2' and '2suffix', rather than silently replacing its grammar.
fn version(i: &Invocation) -> Result<i64, CliError> {
    let value = i.text("version").unwrap_or("").trim_start();
    let signed = value.strip_prefix('+').unwrap_or(value);
    let digits = signed.bytes().take_while(u8::is_ascii_digit).count();
    signed
        .get(..digits)
        .and_then(|n| n.parse::<i64>().ok())
        .filter(|n| *n > 0)
        .ok_or_else(|| argument("Missing or invalid --version <n>."))
}
fn options(i: &Invocation) -> Result<PreviewStartOptions, CliError> {
    let timeout = if i.boolean("wait") {
        match i.flags.get("timeout-seconds") {
            None => None,
            Some(value) => {
                let raw = value.as_str().ok_or_else(|| {
                    argument("--timeout-seconds requires a positive integer value")
                })?;
                let n = raw
                    .parse::<u64>()
                    .ok()
                    .filter(|n| *n > 0 && n.to_string() == raw)
                    .ok_or_else(|| argument("--timeout-seconds must be a positive integer"))?;
                Some(Duration::from_secs(n))
            }
        }
    } else {
        None
    };
    Ok(PreviewStartOptions {
        wait: i.boolean("wait"),
        timeout,
        shared_context: i.text("shared-context").map(str::to_owned),
        requested_runtime: i.text("runtime").map(str::to_owned),
        source_message_id: i.text("source-message-id").map(str::to_owned),
    })
}
fn preview_output(i: &Invocation, value: Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&value);
    }
    let mut out = format!(
        "Session: {}\nStatus: {}\n",
        value["session_id"].as_str().unwrap_or(""),
        value["status"].as_str().unwrap_or("unknown")
    );
    if let Some(url) = value["preview_url"].as_str() {
        out.push_str(&format!("Preview URL: {url}\n"));
    }
    if value["charged_credits"].is_number() {
        out.push_str(&format!("Charged credits: {}\n", value["charged_credits"]));
    }
    if let Some(error) = value["error"].as_str().filter(|v| !v.is_empty()) {
        out.push_str(&format!("Error: {error}\n"));
    }
    Ok(CliOutput::text(out))
}
fn versions_output(i: &Invocation, value: Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&value);
    }
    let id = value["embed_id"].as_str().ok_or(Error::Protocol)?;
    let rows = value["versions"].as_array().ok_or(Error::Protocol)?;
    let mut out = format!("\n\x1b[1mEmbed versions\x1b[0m {id}\n");
    for row in rows {
        let number = row["version_number"].as_i64().ok_or(Error::Protocol)?;
        let marker = if row["version_number"] == value["current_version"] {
            " (current)"
        } else {
            ""
        };
        let seconds = row["created_at"]
            .as_f64()
            .filter(|v| v.is_finite())
            .ok_or(Error::Protocol)?;
        let date =
            time::OffsetDateTime::from_unix_timestamp_nanos((seconds * 1_000_000_000.0) as i128)
                .map_err(|_| Error::Protocol)?;
        let date = format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
            date.year(),
            u8::from(date.month()),
            date.day(),
            date.hour(),
            date.minute(),
            date.second(),
            date.millisecond()
        );
        out.push_str(&format!("  v{number}{marker}  {date}\n"));
    }
    if value["readonly"] == true {
        out.push_str("\x1b[2mRead-only shared history\x1b[0m\n");
    }
    Ok(CliOutput::text(out))
}
pub async fn execute_sdk_embeds(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    execute_sdk_embeds_with_gate(i, client, cancel, &|| Ok(())).await
}
/// Application adapter supplies its live profile privacy gate. The SDK owns
/// network/crypto; this callback only restricts final local publication.
pub async fn execute_sdk_embeds_with_gate(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
    private_gate: &(dyn Fn() -> Result<(), Error> + Send + Sync),
) -> Result<CliOutput, CliError> {
    let path = i.command_path();
    match path.as_str(){
        "embeds versions list"=>super::handlers::flags(i,&[])?,
        "embeds versions show"=>super::handlers::flags(i,&["version","output"])?,
        "embeds test-result"=>super::handlers::flags(i,&["version"])?,
        "embeds versions restore"=>super::handlers::flags(i,&["version","yes"])?,
        "embeds preview start"=>super::handlers::flags(i,&["chat-id","chat","shared-context","runtime","source-message-id","wait","timeout-seconds"])?,
        "embeds preview status"|"embeds preview open"|"embeds preview stop"=>super::handlers::flags(i,&[])?,
        _=>return Err(CliError::Unsupported{command:path,reason:"This embed command is not ported; Cookie, content reconstruction and share parity remain required.".into()}),
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    private_gate()?;
    let id = first(i)?;
    client.set_operation_cancel(cancel.clone());
    let result=async { match path.as_str(){
        "embeds versions list"=>versions_output(i,client.embeds().versions(id).await?),
        "embeds versions show"=>{
            let number=version(i)?;
            let value=client.embeds().version_content(id,number).await?;
            version_content_output(i,value,&cancel,private_gate)
        },
        "embeds test-result"=>{
            let number=version(i)?;
            let value=client.embeds().version_content(id,number).await?;
            super::test_result_cmd::output(i.boolean("json"),&value)
        },
        "embeds versions restore"=>{
            let number=version(i)?;
            if !i.boolean("yes"){return Err(argument("Restoring an embed version requires --yes; interactive confirmation is not ported."));}
            let value=client.embeds().restore_version(id,number,true).await?;
            if i.boolean("json"){CliOutput::json(&value)}else{
                Ok(CliOutput::text(format!("Restored v{} as new v{} for {}.",value["restored_from_version"],value["version_number"],value["embed_id"].as_str().ok_or(Error::Protocol)?)))
            }
        }
        "embeds preview start"=>{
            let chat=i.text("chat-id").or_else(||i.text("chat")).filter(|v|!v.is_empty()).ok_or_else(||argument("Usage: openmates embeds preview start <embed-id> --chat-id <chat-id> [--wait] [--json]"))?;
            let options=options(i)?;
            let value=client.embeds().preview().start(id,chat,options).await.map_err(|e|match e{
                PreviewStartError::ClientError(error)=>CliError::Client(error),
                PreviewStartError::LocalDeadline=>argument("Application preview did not reach running state before timeout."),
            })?;
            preview_output(i,value)
        }
        "embeds preview status"=>preview_output(i,client.embeds().preview().status(id).await?),
        "embeds preview open"=>preview_output(i,client.embeds().preview().open(id).await?),
        "embeds preview stop"=>preview_output(i,client.embeds().preview().stop(id).await?),
        _=>unreachable!(),
    }}.await;
    let denied = if cancel.is_cancelled() {
        Some(Error::Cancelled)
    } else if result.is_ok() {
        private_gate().err()
    } else {
        None
    };
    if let Some(error) = denied {
        if let Ok(mut output) = result {
            use zeroize::Zeroize;
            output.stdout.zeroize();
            output.stderr.zeroize();
        }
        return Err(error.into());
    }
    result
}
fn wipe_json(value: &mut Value) {
    use zeroize::Zeroize;
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(v) => v.iter_mut().for_each(wipe_json),
        Value::Object(v) => {
            for (mut key, mut value) in std::mem::take(v) {
                key.zeroize();
                wipe_json(&mut value);
            }
        }
        _ => {}
    }
}
struct PendingVersion(Value);
impl Drop for PendingVersion {
    fn drop(&mut self) {
        wipe_json(&mut self.0);
    }
}
fn version_content_output(
    i: &Invocation,
    value: Value,
    cancel: &CancellationToken,
    gate: &(dyn Fn() -> Result<(), Error> + Send + Sync),
) -> Result<CliOutput, CliError> {
    let mut value = PendingVersion(value);
    let content = value.0["content"].as_str().ok_or_else(|| {
        argument("Embed version content was not available after local reconstruction.")
    })?;
    if let Some(path) = i.text("output") {
        write_version_output(std::path::Path::new(path), content.as_bytes(), cancel, gate)?;
        value.0["output"] = Value::String(path.into());
        if i.boolean("json") {
            return CliOutput::json(&value.0);
        }
        return Ok(CliOutput::text(format!(
            "Wrote {} v{} to {path}",
            value.0["embed_id"].as_str().ok_or(Error::Protocol)?,
            value.0["version_number"]
        )));
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    gate()?;
    if i.boolean("json") {
        return CliOutput::json(&value.0);
    }
    // Sanitize each untrusted field before adding the fixed local styling.
    // CliOutput::text would also escape the trusted heading's ANSI sequences.
    let id = super::terminal_text(value.0["embed_id"].as_str().ok_or(Error::Protocol)?);
    let number = super::terminal_text(&value.0["version_number"].to_string());
    let content = super::terminal_text(content);
    Ok(CliOutput {
        stdout: format!("\n\x1b[1m{id} v{number}\x1b[0m\n{content}\n"),
        stderr: String::new(),
        exit_code: 0,
    })
}
#[cfg(unix)]
fn write_version_output(
    path: &std::path::Path,
    bytes: &[u8],
    cancel: &CancellationToken,
    gate: &(dyn Fn() -> Result<(), Error> + Send + Sync),
) -> Result<(), CliError> {
    use rustix::fs::{AtFlags, Mode, OFlags};
    use std::{io::Write, path::Component};
    let name = path
        .file_name()
        .ok_or_else(|| argument("Provide a filename for --output."))?;
    let mut parent =
        std::fs::File::open(if path.is_absolute() { "/" } else { "." }).map_err(|_| Error::Io)?;
    for component in path
        .parent()
        .unwrap_or_else(|| std::path::Path::new("."))
        .components()
    {
        let part = match component {
            Component::RootDir | Component::CurDir => continue,
            Component::Normal(p) => p,
            Component::ParentDir => std::ffi::OsStr::new(".."),
            Component::Prefix(_) => return Err(Error::Forbidden.into()),
        };
        parent = std::fs::File::from(
            rustix::fs::openat(
                &parent,
                part,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| Error::Forbidden)?,
        );
    }
    // The held directory descriptor prevents parent-symlink traversal. Replace
    // a regular destination atomically, never open/truncate it or follow links.
    let temp = format!(".openmates-version-{}.tmp", uuid::Uuid::new_v4());
    let descriptor = rustix::fs::openat(
        &parent,
        temp.as_str(),
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::RUSR | Mode::WUSR,
    )
    .map_err(|_| Error::Io)?;
    let result = (|| {
        let mut file = std::fs::File::from(descriptor);
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| Error::Io)?;
        gate()?;
        if cancel.is_cancelled() {
            return Err(CliError::Client(Error::Cancelled));
        }
        match rustix::fs::statat(&parent, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(stat) if (stat.st_mode & 0o170000) != 0o100000 => {
                return Err(Error::Forbidden.into());
            }
            Ok(_) => {}
            Err(rustix::io::Errno::NOENT) => {}
            Err(_) => return Err(Error::Io.into()),
        }
        rustix::fs::renameat(&parent, temp.as_str(), &parent, name).map_err(|_| Error::Io)?;
        parent.sync_all().map_err(|_| Error::Io)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = rustix::fs::unlinkat(&parent, temp.as_str(), AtFlags::empty());
    }
    result
}
#[cfg(not(unix))]
fn write_version_output(
    _: &std::path::Path,
    _: &[u8],
    _: &CancellationToken,
    _: &(dyn Fn() -> Result<(), Error> + Send + Sync),
) -> Result<(), CliError> {
    Err(argument(
        "Secure version output files are unavailable on this platform.",
    ))
}

#[cfg(test)]
#[path = "embed_commands_tests.rs"]
mod tests;

/// Personal Cookie facade: shared Client owns auth/key/read/reconstruction;
/// preserve the exact same JSON/human/atomic fsync output implementation.
pub(super) async fn execute_cookie_version(
    i:&Invocation,client:&mut openmates_sdk::Client,cancel:CancellationToken,
)->Result<CliOutput,CliError>{
    let test_result=i.command_path()=="embeds test-result";
    super::handlers::flags(i,if test_result{&["version"][..]}else{&["version","output"][..]})?;
    let id=first(i)?;let number=version(i)?;
    if cancel.is_cancelled(){return Err(Error::Cancelled.into());}
    client.set_operation_cancel(cancel.clone());
    let(value,admission)=client.embed_version_content_with_admission(id,number).await?;
    let mut value=PendingVersion(value);
    let result=if test_result{super::test_result_cmd::output(i.boolean("json"),&value.0)}else{version_content_output(i,std::mem::take(&mut value.0),&cancel,&||admission.check(client))};
    if let Err(error)=admission.check(client) {
        if let Ok(mut output)=result {use zeroize::Zeroize;output.stdout.zeroize();output.stderr.zeroize();}
        return Err(error.into());
    }
    result
}
