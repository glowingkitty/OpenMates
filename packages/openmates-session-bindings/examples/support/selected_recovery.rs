//! Authored direct SessionBridge selected discovery; loopback execution CI-only.
use super::*;
pub(super) async fn run(bridge:&SessionBridge,suite:&Value,vector:&Value,peer:&Peer,directory:&Directory)->R<()> {
    let chat=field(vector,"chat_id")?;
    let mode=field(vector,"mode")?;
    refused(bridge.completion_recovery_jobs_for_chat(chat.into()).await,&["unavailable"])?;
    bridge.completion_recovery_enable(true).await.map_err(|_|"explicit foreground")?;
    let preserved=b"synthetic opaque encrypted unrelated checkpoint\n";
    let mut journal_file=write_selected(directory,"unrelated-journal",preserved)?;
    if mode=="selected_partial_failure" {
        refused(bridge.completion_recovery_jobs_for_chat(chat.into()).await,&["protocol"])?;
    } else if mode=="selected_cancel" {
        let worker=bridge.clone();let chat=chat.to_owned();
        let pending=tokio::spawn(async move{worker.completion_recovery_jobs_for_chat(chat).await});
        peer.wait(|s|s["selected_discovery_waiting"].as_u64().unwrap_or(0)>=1).await?;
        bridge.cancel().map_err(|_|"cancel")?;
        refused(pending.await.map_err(|_|"selected discovery join")?,&["cancelled"])?;
    } else {
        let found=decode(bridge.completion_recovery_jobs_for_chat(chat.into())).await?;
        let jobs=found.as_array().ok_or("typed jobs")?;
        need(jobs.iter().all(|entry|entry["job"]["chat_id"]==chat && entry.as_object().is_some_and(|o|o.len()==2 && o.contains_key("id") && o.contains_key("job"))))?;
        if matches!(mode,"selected_empty"|"selected_pending") {need(jobs.is_empty())?;} else {
            need(jobs.len()==1)?;
            let other=decode(bridge.completion_recovery_jobs_for_chat(field(vector,"unrelated_chat_id")?.into())).await?;
            need(other.as_array().is_some_and(|rows|rows.len()==1) && other[0]["job"]["chat_id"]==vector["unrelated_chat_id"])?;
            let stage=decode(bridge.completion_recovery_stage(field(&jobs[0],"id")?.into())).await?;
            need(stage["kind"]=="ready")?;
            let expected=field(&stage,"checkpoint_json")?.as_bytes();
            let mut checkpoint_file=write_selected(directory,"checkpoint",expected)?;
            need(peer.get("/__test/status")?["persists"]==0)?;
            let bytes=read_selected(directory,"checkpoint",expected,&mut checkpoint_file)?;
            let receipt=decode(bridge.completion_recovery_commit(field(&stage,"id")?.into(),json!({"checkpoint_sha256":hash(&bytes)}).to_string())).await?;
            need(receipt["state"]=="TERMINAL" && receipt["assistant_message_id"]==suite["protocol"]["assistant_id"])?;
        }
    }
    need(read_selected(directory,"unrelated-journal",preserved,&mut journal_file)?.as_slice()==preserved.as_slice())?;
    if mode!="selected_main" {need(!directory.0.join("checkpoint").exists())?;}
    let status=peer.get("/__test/status")?;
    need(status["failure"].is_null() && status["admissions"]==0)?;
    need(status["claims"]==if mode=="selected_main"{1}else{0})?;
    need(status["checks"].as_array().is_some_and(|checks|checks.iter().any(|c|c=="selected-startup-without-phased-sync")))?;
    Ok(())
}

// Selected-only fixture persistence. Directory::new creates the unique owned
// 0700 root; a newly created file must have the same creator UID as that root.
// This avoids exporting or inventing any SDK durability receipt.
#[cfg(unix)]
fn current_parent(directory:&Directory,original:&std::fs::Metadata)->R<()> {
    use std::os::unix::fs::MetadataExt;
    let named=std::fs::symlink_metadata(&directory.0).map_err(|_|"selected parent metadata")?;
    need(named.is_dir() && !named.file_type().is_symlink())?;
    need((named.dev(),named.ino(),named.uid())==(original.dev(),original.ino(),original.uid()) && named.mode()&0o7777==0o700)
}
#[cfg(unix)]
fn selected_parent(directory:&Directory)->R<(std::fs::File,std::fs::Metadata)> {
    let named=std::fs::symlink_metadata(&directory.0).map_err(|_|"selected parent metadata")?;
    need(named.is_dir() && !named.file_type().is_symlink())?;
    let handle=std::fs::File::open(&directory.0).map_err(|_|"selected parent open")?;
    let original=handle.metadata().map_err(|_|"selected parent metadata")?;
    current_parent(directory,&original)?;
    Ok((handle,original))
}
#[cfg(unix)]
fn selected_file(directory:&Directory,name:&str,file:&std::fs::File,parent:&std::fs::Metadata,size:usize)->R<()> {
    use std::os::unix::fs::MetadataExt;
    need(matches!(name,"checkpoint"|"unrelated-journal"))?;
    let actual=file.metadata().map_err(|_|"selected file metadata")?;
    let named=std::fs::symlink_metadata(directory.0.join(name)).map_err(|_|"selected file metadata")?;
    need(actual.is_file() && named.is_file() && !named.file_type().is_symlink())?;
    need((actual.dev(),actual.ino(),actual.uid(),actual.mode(),actual.nlink(),actual.len())==(named.dev(),named.ino(),named.uid(),named.mode(),named.nlink(),named.len()) && actual.uid()==parent.uid() && actual.mode()&0o7777==0o600 && actual.nlink()==1 && actual.len()==size as u64)?;
    current_parent(directory,parent)
}
struct SelectedFile {
    file:std::fs::File,
    parent:std::fs::File,
    original:std::fs::Metadata,
    physical:std::fs::Metadata,
    directory:PathBuf,
    name:String,
}
// File ownership is the lease: original writer and parent anchors stay open
// across status/commit awaits. Automatic File Drop handles every return/cancel.
#[cfg(unix)]
fn read_selected(directory:&Directory,name:&str,expected:&[u8],lease:&mut SelectedFile)->R<Vec<u8>> {
    use std::io::{Read,Seek,SeekFrom};
    use std::os::unix::fs::MetadataExt;
    need(lease.directory==directory.0 && lease.name==name)?;
    let parent=lease.parent.metadata().map_err(|_|"selected parent metadata")?;
    need((parent.dev(),parent.ino())==(lease.original.dev(),lease.original.ino()))?;
    selected_file(directory,name,&lease.file,&lease.original,expected.len())?;
    let actual=lease.file.metadata().map_err(|_|"selected file metadata")?;
    need((actual.dev(),actual.ino())==(lease.physical.dev(),lease.physical.ino()))?;
    lease.file.seek(SeekFrom::Start(0)).map_err(|_|"selected readback")?;
    let mut bytes=vec![0;expected.len()];
    lease.file.read_exact(&mut bytes).map_err(|_|"selected readback")?;
    let mut extra=[0;1];need(lease.file.read(&mut extra).map_err(|_|"selected readback")?==0)?;
    selected_file(directory,name,&lease.file,&lease.original,expected.len())?;
    need(bytes.as_slice()==expected)?;Ok(bytes)
}
#[cfg(unix)]
fn write_selected(directory:&Directory,name:&str,raw:&[u8])->R<SelectedFile> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let (parent,original)=selected_parent(directory)?;
    need(matches!(name,"checkpoint"|"unrelated-journal"))?;
    let mut file=std::fs::OpenOptions::new().read(true).write(true).create_new(true).mode(0o600)
        .open(directory.0.join(name)).map_err(|_|"selected file create")?;
    selected_file(directory,name,&file,&original,0)?;
    file.write_all(raw).map_err(|_|"selected file write")?;
    selected_file(directory,name,&file,&original,raw.len())?;
    file.sync_all().map_err(|_|"selected file fsync")?;
    parent.sync_all().map_err(|_|"selected parent fsync")?;
    selected_file(directory,name,&file,&original,raw.len())?;
    let physical=file.metadata().map_err(|_|"selected file metadata")?;
    let mut lease=SelectedFile{file,parent,original,physical,directory:directory.0.clone(),name:name.into()};
    read_selected(directory,name,raw,&mut lease)?;
    Ok(lease)
}
#[cfg(not(unix))]
fn read_selected(_directory:&Directory,_name:&str,_expected:&[u8],_lease:&mut SelectedFile)->R<Vec<u8>> {Err("selected Unix fixture required")}
#[cfg(not(unix))]
fn write_selected(_directory:&Directory,_name:&str,_raw:&[u8])->R<SelectedFile> {Err("selected Unix fixture required")}
#[cfg(all(test,unix))]
mod durability_tests {
    use super::*;
    #[test]
    fn selected_fixture_readback_requires_private_regular_owned_file() {
        use std::os::unix::fs::PermissionsExt;
        let directory=Directory::new().unwrap();let raw=b"synthetic exact checkpoint";
        let mut lease=write_selected(&directory,"checkpoint",raw).unwrap();
        assert!(lease.file.metadata().is_ok() && lease.parent.metadata().is_ok());
        assert_eq!(read_selected(&directory,"checkpoint",raw,&mut lease).unwrap().as_slice(),raw.as_slice());
        assert!(write_selected(&directory,"checkpoint",raw).is_err());
        std::fs::set_permissions(directory.0.join("checkpoint"),std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(read_selected(&directory,"checkpoint",raw,&mut lease).is_err());
        std::fs::remove_file(directory.0.join("checkpoint")).unwrap();
        directory.write("checkpoint",raw).unwrap();
        assert!(read_selected(&directory,"checkpoint",raw,&mut lease).is_err());
    }
}
