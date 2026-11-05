//! Actual production keyless coalescer tests, authored UNRUN. No Session,
//! socket/auth/foreground/physical-store/completion authority is simulated.
use super::*;
fn id(n:u32)->String{format!("{n:08x}-1111-4111-8111-111111111111")}
fn offer(kind:&str,jobs:Vec<(u32,u32)>)->(String,Value){(kind.into(),json!({"jobs":jobs.into_iter().map(|(job,chat)|json!({"job_id":id(job),"chat_id":id(chat)})).collect::<Vec<_>>()}))}
fn send(changes:&Changes,kind:&str,jobs:Vec<(u32,u32)>)->Result<()>{let(k,v)=offer(kind,jobs);record_change(changes,&k,&v)}
fn manifest(changes:&Changes)->RecoveryHintManifest{let pending=changes.pending.lock().unwrap();pending.recovery_jobs.snapshot(&pending.recovery)}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn actual_coalescer_preserves_each_original_main_and_metadata_job_not_just_one_chat(){
    let changes=Changes::default();send(&changes,"recovery_jobs_available",vec![(1,100),(2,100)]).unwrap();send(&changes,"metadata_jobs_available",vec![(1,100)]).unwrap();
    let read=manifest(&changes);assert_eq!(read.len(),3);assert!(!read.needs_rescan());assert_eq!(changes.pending.lock().unwrap().recovery.len(),1);
    assert_eq!(read.identities().filter(|(_,_,chat)|*chat==id(100)).count(),3);
    // Namespaces remain distinct even if independent backend job tables share
    // a UUID. A hint itself is still never a claim/lease or execution grant.
    assert_eq!(read.identities().filter(|(kind,_,_)|*kind==RecoveryHintKind::Metadata).count(),1);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn actual_bounded_job_overflow_requires_rescan_instead_of_silent_full_completion(){
    let changes=Changes::default();send(&changes,"recovery_jobs_available",(1..=MAX_HINTS as u32).map(|n|(n,1000)).collect()).unwrap();send(&changes,"metadata_jobs_available",vec![((MAX_HINTS+1)as u32,1000)]).unwrap();
    let read=manifest(&changes);assert_eq!(read.len(),MAX_HINTS);assert!(read.needs_rescan());
    send(&changes,"recovery_jobs_available",vec![(1,1000)]).unwrap();assert!(manifest(&changes).needs_rescan());assert_eq!(manifest(&changes).len(),MAX_HINTS);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn conflicting_original_kind_job_to_chat_binding_refuses_and_keeps_rescan_barrier(){
    let changes=Changes::default();send(&changes,"recovery_jobs_available",vec![(1,100)]).unwrap();assert!(matches!(send(&changes,"recovery_jobs_available",vec![(1,101)]),Err(Error::Protocol)));
    assert!(manifest(&changes).needs_rescan());let read=manifest(&changes);assert_eq!(read.len(),1);assert_eq!(read.identities().next().unwrap().2,id(100));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn actual_pending_take_and_requeue_merge_retains_later_job_without_acknowledging_originals(){
    let changes=Changes::default();send(&changes,"recovery_jobs_available",vec![(1,100)]).unwrap();let original=std::mem::take(&mut *changes.pending.lock().unwrap());
    send(&changes,"metadata_jobs_available",vec![(2,101)]).unwrap();{let mut pending=changes.pending.lock().unwrap();merge_pending(&mut pending,original).unwrap();}
    let read=manifest(&changes);assert_eq!(read.len(),2);assert!(!read.needs_rescan());assert_eq!(changes.pending.lock().unwrap().recovery.len(),2);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn old_or_incomplete_chat_only_hint_coverage_cannot_become_completed_job_manifest(){
    let changes=Changes::default();changes.pending.lock().unwrap().recovery.insert(id(100));let read=manifest(&changes);assert_eq!(read.len(),0);assert!(read.needs_rescan());
    let mut malformed=RecoveryHintJobs::default();assert!(malformed.record(RecoveryHintKind::Main,"not-a-job",&id(100)).is_err());assert!(malformed.snapshot(&BTreeSet::new()).needs_rescan());
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn complete_original_notification_offers_retain_actual_task_stage_and_never_infer_from_keyless_ids(){
    let changes=Changes::default();send(&changes,"metadata_jobs_available",vec![(1,100)]).unwrap();
    let read=manifest(&changes);assert_eq!(read.len(),1);assert_eq!(read.offered_for_chat(&id(100)).count(),0);
    let row=json!({"job_id":id(1),"chat_id":id(100),"chat_key_version":1,"task_id":id(2),"stage":"initial"});
    record_change(&changes,"metadata_jobs_available",&json!({"jobs":[row]})).unwrap();
    let read=manifest(&changes);let actual=read.offered_for_chat(&id(100)).next().unwrap().clone();
    assert_eq!(actual.task_id.as_deref(),Some(id(2).as_str()));assert_eq!(actual.stage.as_deref(),Some("initial"));assert!(read.contains(&actual));
    let mut wrong=actual.clone();wrong.task_id=Some(id(3));assert!(!read.contains(&wrong));
    assert_eq!(read.offered_for_chat(&id(101)).count(),0);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn full_offer_conflicts_refuse_and_take_requeue_preserves_exact_original_offer(){
    let changes=Changes::default();let offer=|task:u32|json!({"jobs":[{"job_id":id(1),"chat_id":id(100),"chat_key_version":1,"task_id":id(task),"stage":"initial"}]});
    record_change(&changes,"metadata_jobs_available",&offer(2)).unwrap();let original=std::mem::take(&mut *changes.pending.lock().unwrap());
    record_change(&changes,"metadata_jobs_available",&offer(2)).unwrap();merge_pending(&mut changes.pending.lock().unwrap(),original).unwrap();
    let read=manifest(&changes);assert_eq!(read.offered_for_chat(&id(100)).next().unwrap().task_id.as_deref(),Some(id(2).as_str()));
    assert!(record_change(&changes,"metadata_jobs_available",&offer(3)).is_err());assert!(manifest(&changes).needs_rescan());
    let malformed=json!({"jobs":[{"job_id":id(4),"chat_id":id(100),"chat_key_version":1,"stage":"initial"}]});
    assert!(record_change(&changes,"metadata_jobs_available",&malformed).is_err());assert!(manifest(&changes).offered_for_chat(&id(100)).all(|job|job.job_id!=id(4)));
}
