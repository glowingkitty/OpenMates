//! Poll-driven driver of the source side of the remote-command job protocol.
//!
//! Owned by the serve loop of `source_host/runner.rs`; it does no socket IO.
//! Each loop iteration the runner feeds admitted server frames to
//! [`JobDriver::handle_frame`], calls [`JobDriver::tick`] and sends
//! [`JobDriver::take_outbox`]. Port of the controller half of
//! `remoteCommandSource.ts` (discover, claim, recover, stop, heartbeat) with
//! the launch from `launch.rs` and the event queue of `events.rs`.
//!
//! Flow per job: discover/available -> claim -> decrypt + verify the portable
//! request and the approval -> `authorizing` event -> two `revalidate`
//! checks -> launch -> stream output as sequenced events -> terminal
//! completion. A refusal at any step is reported as a terminal `failed`
//! event whose job object carries `error_code` / `error_message`.
//!
//! Deviations from the npm host: only `foreground` jobs run (a background job
//! needs a detached lifetime that outlives this serve loop; it is refused with
//! `invalid_request`), preset approvals are refused by `approval.rs`, and
//! terminal error/stop details travel inside the sealed `job` object instead
//! of the top level of the event plaintext.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::approval::{runtime_approval, validate_approval};
use super::driver_job::{Job, Step};
use super::events::ExecutionEvents;
use super::launch;
use super::portable::{Mode, PortableRequest, SourceAccess, open_claimed_request};
use super::transport::{JobTransport, RequestFailure, RequestId, RequestOutcome, ServerFrame};
use super::wire::{
    ClaimBinding, ClaimedRequest, CommandSummary, EventStatus, LeaseIdentity, LeaseResponse,
    RemoteCommandErrorCode, claim_payload, discover_payload, recover_payload, revalidate_payload,
    validate_authority_reply, validate_claimed_request, validate_lease_response,
};
use crate::client::now_ms;
use crate::crypto::Key;
use crate::source_host::dispatch::{HostedSource, request_root};
use crate::source_host::reads::HostRoot;
use serde_json::{Value, json};
use std::collections::VecDeque;

/// Most stop requests buffered for jobs not claimed yet.
const MAX_PENDING_STOPS: usize = 1024;
/// Delay before a failed discovery is retried.
const DISCOVERY_RETRY_MS: u64 = 5_000;

/// One served source with the facts the driver needs.
pub(crate) struct DriverSource {
    /// Project id of the binding.
    pub(crate) project_id: String,
    /// Source id of the binding.
    pub(crate) source_id: String,
    /// Team id for team bindings.
    pub(crate) team_id: Option<String>,
    /// Key epoch of the Project key.
    pub(crate) key_epoch: i64,
    /// Project key: opens requests and seals events (memory only, zeroized).
    pub(crate) key: Key,
    /// Approved local root of the source; a job runs in its chat's worktree
    /// inside it when the source is a Git repository.
    pub(crate) host: HostRoot,
    /// Target branch for chat worktrees (`None`: the root's checked-out branch).
    pub(crate) target_branch: Option<String>,
}

struct Claim {
    source: usize,
    summary: CommandSummary,
    allow_launch: bool,
    id: RequestId,
}

/// Job protocol state machine for the sources of one host session.
pub(crate) struct JobDriver {
    session_id: String,
    sources: Vec<DriverSource>,
    transport: JobTransport,
    jobs: Vec<Job>,
    claims: Vec<Claim>,
    discovering: Option<RequestId>,
    discover_queue: VecDeque<usize>,
    need_discovery: bool,
    retry_at: Option<u64>,
    pending_stops: Vec<(String, String, String)>,
    notes: Vec<String>,
    now_ms: u64,
}

fn unix_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64)
}

impl JobDriver {
    /// Driver for `sources` under the host session `session_id`.
    pub(crate) fn new(session_id: &str, sources: Vec<DriverSource>) -> Self {
        Self {
            session_id: session_id.to_owned(),
            sources,
            transport: JobTransport::new(),
            jobs: Vec::new(),
            claims: Vec::new(),
            discovering: None,
            discover_queue: VecDeque::new(),
            need_discovery: true,
            retry_at: None,
            pending_stops: Vec::new(),
            notes: Vec::new(),
            now_ms: 0,
        }
    }

    /// The socket (re)attached: drop every open request, lose leases and
    /// rediscover. Running processes keep running and are recovered.
    pub(crate) fn on_connected(&mut self) {
        self.transport = JobTransport::new();
        self.claims.clear();
        self.discovering = None;
        self.discover_queue.clear();
        self.need_discovery = true;
        self.retry_at = None;
        for job in &mut self.jobs {
            job.inflight = None;
            job.events.clear_lease();
            if matches!(job.step, Step::Recovering(_)) {
                job.step = Step::Running;
            } else if let Step::Revalidating { id, .. } = &mut job.step {
                *id = None;
            }
        }
    }

    /// Replace the served sources after a rebind. Returns `true` when the set
    /// changed (the caller then treats it as a fresh registration and calls
    /// [`Self::on_connected`]). Jobs of vanished sources are stopped and dropped.
    pub(crate) fn sync_sources(&mut self, sources: Vec<DriverSource>) -> bool {
        let ident = |s: &DriverSource| {
            (
                s.project_id.clone(),
                s.source_id.clone(),
                s.team_id.clone(),
                s.key_epoch,
            )
        };
        let old: Vec<_> = self.sources.iter().map(ident).collect();
        let new: Vec<_> = sources.iter().map(ident).collect();
        if old == new {
            return false;
        }
        for job in &mut self.jobs {
            let moved = old
                .get(job.source)
                .and_then(|o| new.iter().position(|n| n == o));
            match moved {
                Some(at) => job.source = at,
                None => job.source = usize::MAX,
            }
        }
        self.jobs.retain(|j| j.source != usize::MAX);
        self.sources = sources;
        true
    }

    /// Feed one admitted server frame; matching is done on the next tick.
    pub(crate) fn handle_frame(&mut self, frame: ServerFrame) {
        self.transport.accept(frame);
    }

    /// Frames to send now, in order.
    pub(crate) fn take_outbox(&mut self) -> Vec<(&'static str, Value)> {
        self.transport.take_outbox()
    }

    /// Short local diagnostics (`"remote_command <what>"`) since the last call.
    pub(crate) fn take_notes(&mut self) -> Vec<String> {
        std::mem::take(&mut self.notes)
    }

    /// Jobs that are not finished yet.
    pub(crate) fn active_len(&self) -> usize {
        self.jobs.len()
    }

    /// Advance everything once. Never blocks.
    pub(crate) fn tick(&mut self, now_ms: u64) {
        self.now_ms = now_ms;
        self.transport.expire(now_ms);
        for frame in self.transport.take_unsolicited() {
            match frame {
                ServerFrame::Available(summary) => self.on_available(summary),
                ServerFrame::StopRequested(summary) => self.on_stop(&summary),
                _ => {}
            }
        }
        self.drive_discovery(now_ms);
        let claims = std::mem::take(&mut self.claims);
        for claim in claims {
            match self.transport.take_outcome(claim.id) {
                Some(outcome) => self.finish_claim(claim, outcome, now_ms),
                None => self.claims.push(claim),
            }
        }
        for index in 0..self.jobs.len() {
            self.drive_job(index, now_ms);
        }
        self.jobs
            .retain(|j| !(j.events.is_completed() && j.process.is_none()));
    }

    fn source_index(&self, project_id: &str, source_id: &str) -> Option<usize> {
        self.sources
            .iter()
            .position(|s| s.project_id == project_id && s.source_id == source_id)
    }

    fn lease_identity(
        &self,
        source: usize,
        execution_id: &str,
        lease: &LeaseResponse,
    ) -> LeaseIdentity {
        self.identity(
            source,
            execution_id,
            &lease.lease_token,
            lease.lease_generation,
        )
    }

    fn identity(
        &self,
        source: usize,
        execution_id: &str,
        token: &str,
        generation: i64,
    ) -> LeaseIdentity {
        let s = &self.sources[source];
        LeaseIdentity {
            execution_id: execution_id.to_owned(),
            project_id: s.project_id.clone(),
            source_id: s.source_id.clone(),
            source_session_id: self.session_id.clone(),
            team_id: s.team_id.clone(),
            lease_token: token.to_owned(),
            lease_generation: generation,
        }
    }

    fn on_available(&mut self, summary: CommandSummary) {
        if summary.state != "WAITING_FOR_EXECUTOR" {
            return;
        }
        if let Some(source) = self.source_index(&summary.project_id, &summary.source_id) {
            self.start_claim(source, summary, true);
        }
    }

    fn on_stop(&mut self, summary: &CommandSummary) {
        if let Some(job) = self
            .jobs
            .iter_mut()
            .find(|j| j.execution_id == summary.execution_id)
        {
            job.stop();
        } else if self.pending_stops.len() < MAX_PENDING_STOPS {
            self.pending_stops.push((
                summary.execution_id.clone(),
                summary.project_id.clone(),
                summary.source_id.clone(),
            ));
        }
    }

    /// Mark stopped: terminate a running process (its exit becomes the
    /// terminal `stopped` event) or end an unlaunched job right away.

    fn start_claim(&mut self, source: usize, summary: CommandSummary, allow_launch: bool) {
        if self
            .claims
            .iter()
            .any(|c| c.summary.execution_id == summary.execution_id)
        {
            return;
        }
        let s = &self.sources[source];
        let payload = claim_payload(&summary, &self.session_id, s.team_id.as_deref());
        match self.transport.submit(
            "remote_command_claim",
            payload,
            &summary.execution_id,
            self.now_ms,
        ) {
            Ok(id) => self.claims.push(Claim {
                source,
                summary,
                allow_launch,
                id,
            }),
            Err(error) => self
                .notes
                .push(format!("remote_command claim refused {error:?}")),
        }
    }

    fn drive_discovery(&mut self, now_ms: u64) {
        if let Some(id) = self.discovering {
            let Some(outcome) = self.transport.take_outcome(id) else {
                return;
            };
            self.discovering = None;
            let source = self.discover_queue.pop_front();
            match (source, outcome) {
                (Some(source), Ok(ServerFrame::Jobs(jobs))) => {
                    self.apply_jobs(source, jobs, now_ms)
                }
                _ => {
                    self.notes
                        .push("remote_command discovery failed".to_owned());
                    self.discover_queue.clear();
                    self.retry_at = Some(now_ms + DISCOVERY_RETRY_MS);
                }
            }
        }
        if self.discovering.is_some() {
            return;
        }
        if self.retry_at.is_some_and(|at| at > now_ms) {
            return;
        }
        if self.need_discovery && self.discover_queue.is_empty() {
            self.need_discovery = false;
            self.retry_at = None;
            self.discover_queue = (0..self.sources.len()).collect();
        }
        let Some(&source) = self.discover_queue.front() else {
            return;
        };
        let s = &self.sources[source];
        let payload = discover_payload(
            &s.project_id,
            &s.source_id,
            &self.session_id,
            s.team_id.as_deref(),
        );
        match self
            .transport
            .submit("remote_command_discover", payload, "", now_ms)
        {
            Ok(id) => self.discovering = Some(id),
            Err(_) => {
                self.discover_queue.clear();
                self.retry_at = Some(now_ms + DISCOVERY_RETRY_MS);
            }
        }
    }

    fn apply_jobs(&mut self, source: usize, jobs: Vec<CommandSummary>, now_ms: u64) {
        let (project, source_id) = {
            let s = &self.sources[source];
            (s.project_id.clone(), s.source_id.clone())
        };
        for summary in jobs {
            if summary.project_id != project || summary.source_id != source_id {
                continue;
            }
            let position = self
                .jobs
                .iter()
                .position(|j| j.execution_id == summary.execution_id);
            let server_done = matches!(
                summary.state.as_str(),
                "AWAITING_ORIGIN_COMPLETION" | "TERMINAL"
            );
            match position {
                Some(at) if server_done && self.jobs[at].events.terminal_queued() => {
                    // The server already has the outcome: drop what is pending.
                    let job = &mut self.jobs[at];
                    job.process = None;
                    job.events.clear_lease();
                    self.jobs.remove(at);
                }
                _ if summary.state == "WAITING_FOR_EXECUTOR" => {
                    self.start_claim(source, summary, true)
                }
                Some(at) => {
                    if summary.lease_expires_at > unix_secs() {
                        self.start_claim(source, summary, false);
                    } else {
                        self.start_recover(at, &summary, now_ms);
                    }
                }
                None => {}
            }
        }
    }

    fn start_recover(&mut self, at: usize, summary: &CommandSummary, now_ms: u64) {
        let job = &self.jobs[at];
        let status = if job.events.terminal_queued() {
            "terminal_pending"
        } else if job.stopped {
            "stopping"
        } else {
            "running"
        };
        let identity = self.identity(job.source, &job.execution_id, "", 0);
        let payload = recover_payload(&identity, summary.last_sequence, status);
        let execution_id = job.execution_id.clone();
        match self
            .transport
            .submit("remote_command_recover", payload, &execution_id, now_ms)
        {
            Ok(id) => self.jobs[at].step = Step::Recovering(id),
            Err(error) => self
                .notes
                .push(format!("remote_command recover refused {error:?}")),
        }
    }

    fn finish_claim(&mut self, claim: Claim, outcome: RequestOutcome, now_ms: u64) {
        let payload = match outcome {
            Ok(ServerFrame::Request { payload, .. }) => payload,
            Err(RequestFailure::Server { raw_code, .. }) => {
                self.notes.push(format!("remote_command claim {raw_code}"));
                return;
            }
            _ => {
                self.need_discovery = true;
                self.retry_at = Some(now_ms + DISCOVERY_RETRY_MS);
                return;
            }
        };
        let s = &self.sources[claim.source];
        let binding = ClaimBinding {
            project_id: s.project_id.clone(),
            source_id: s.source_id.clone(),
            team_id: s.team_id.clone(),
            key_epoch: s.key_epoch,
        };
        let claimed =
            match validate_claimed_request(&payload, &claim.summary, &binding, &self.session_id) {
                Ok(claimed) => claimed,
                Err(error) => {
                    self.notes
                        .push(format!("remote_command claim invalid: {error}"));
                    return;
                }
            };
        let lease = self.lease_identity(claim.source, &claimed.execution_id, &claimed.lease);
        if let Some(job) = self
            .jobs
            .iter_mut()
            .find(|j| j.execution_id == claimed.execution_id)
        {
            if job.outer_digest != claimed.request_digest || job.approval != claimed.approval {
                job.fail(
                    RemoteCommandErrorCode::AuthorityRevoked,
                    "Reconnected command identity changed",
                );
                return;
            }
            job.lease_expires_at = claimed.lease.lease_expires_at;
            job.events.apply_lease(lease, claimed.lease.last_sequence);
            return;
        }
        if claim.allow_launch && claimed.lease.launch_allowed {
            self.admit_new_job(claim.source, claimed, lease, now_ms);
        }
    }

    /// Create the job for a fresh claim and run the pre-launch checks.
    fn admit_new_job(
        &mut self,
        source: usize,
        claimed: ClaimedRequest,
        lease: LeaseIdentity,
        now_ms: u64,
    ) {
        let mut job = Job {
            source,
            execution_id: claimed.execution_id.clone(),
            events: ExecutionEvents::new(
                &claimed.execution_id,
                claimed.lease.last_sequence,
                now_ms,
            ),
            step: Step::Ending,
            process: None,
            request: None,
            outer_digest: claimed.request_digest.clone(),
            approval: claimed.approval.clone(),
            stopped: false,
            runtime_sequence: 0,
            inflight: None,
            lease_expires_at: claimed.lease.lease_expires_at,
        };
        job.events.apply_lease(lease, claimed.lease.last_sequence);
        let buffered = self
            .pending_stops
            .iter()
            .position(|(e, _, _)| *e == claimed.execution_id);
        if let Some(at) = buffered {
            let (_, project, source_id) = self.pending_stops.remove(at);
            if project != claimed.project_id || source_id != claimed.source_id {
                job.fail(
                    RemoteCommandErrorCode::AuthorityRevoked,
                    "Pending stop binding changed",
                );
            } else {
                job.stop();
            }
            self.jobs.push(job);
            return;
        }
        match self.check_request(source, &claimed) {
            Ok(request) => {
                job.request = Some(request);
                job.events.push_status(
                    EventStatus::Authorizing,
                    json!({"execution_id": job.execution_id, "status": "authorizing"}),
                );
                job.step = Step::Revalidating { round: 1, id: None };
            }
            Err((code, message)) => job.fail(code, &message),
        }
        self.jobs.push(job);
    }

    /// Decrypt, verify digest and approval, and refuse what this host cannot run.
    fn check_request(
        &self,
        source: usize,
        claimed: &ClaimedRequest,
    ) -> Result<PortableRequest, (RemoteCommandErrorCode, String)> {
        let request = open_claimed_request(claimed, &self.sources[source].key)
            .map_err(|e| (RemoteCommandErrorCode::InvalidRequest, e.to_string()))?;
        let approval = runtime_approval(
            &request.approval,
            &request.execution_id,
            &claimed.request_digest,
            false,
        )
        .ok_or_else(|| {
            (
                RemoteCommandErrorCode::ApprovalRequired,
                "approval required".to_owned(),
            )
        })?;
        validate_approval(&approval, &request.execution_id, &claimed.request_digest)
            .map_err(|r| (r.code, r.message.to_owned()))?;
        if request.policy.mode == Mode::Background {
            return Err((
                RemoteCommandErrorCode::InvalidRequest,
                "Background commands are not supported by this host yet".to_owned(),
            ));
        }
        launch::check_supported(&request).map_err(|e| (e.code, e.message))?;
        Ok(request)
    }

    fn drive_job(&mut self, index: usize, now_ms: u64) {
        self.drive_step(index, now_ms);
        let job = &mut self.jobs[index];
        job.drain_process();
        if job.process.is_some() && job.events.heartbeat_due(now_ms) {
            job.events.push_status(
                EventStatus::Running,
                json!({"execution_id": job.execution_id, "status": "running"}),
            );
        }
        if job.events.lease().is_some() && job.lease_expires_at <= unix_secs() {
            job.events.clear_lease();
            job.inflight = None;
            self.need_discovery = true;
        }
        self.flush(index, now_ms);
    }

    fn drive_step(&mut self, index: usize, now_ms: u64) {
        let step = std::mem::replace(&mut self.jobs[index].step, Step::Running);
        let next = match step {
            Step::Revalidating { round, id: None } => self.send_revalidate(index, round, now_ms),
            Step::Revalidating {
                round,
                id: Some(id),
            } => match self.transport.take_outcome(id) {
                None => Step::Revalidating {
                    round,
                    id: Some(id),
                },
                Some(outcome) => self.finish_revalidate(index, round, outcome),
            },
            Step::Recovering(id) => match self.transport.take_outcome(id) {
                None => Step::Recovering(id),
                Some(outcome) => self.finish_recover(index, outcome),
            },
            other => other,
        };
        self.jobs[index].step = next;
    }

    fn send_revalidate(&mut self, index: usize, round: u8, now_ms: u64) -> Step {
        let job = &self.jobs[index];
        let Some(lease) = job.events.lease() else {
            return Step::Revalidating { round, id: None };
        };
        let payload = revalidate_payload(lease);
        let execution_id = job.execution_id.clone();
        match self
            .transport
            .submit("remote_command_revalidate", payload, &execution_id, now_ms)
        {
            Ok(id) => Step::Revalidating {
                round,
                id: Some(id),
            },
            Err(_) => Step::Revalidating { round, id: None },
        }
    }

    fn finish_revalidate(&mut self, index: usize, round: u8, outcome: RequestOutcome) -> Step {
        let job = &mut self.jobs[index];
        let verdict = match outcome {
            Ok(ServerFrame::Authority { payload, .. }) => {
                validate_authority_reply(&payload, &job.execution_id, &job.outer_digest).ok()
            }
            _ => None,
        };
        match verdict {
            Some(reply) if reply.permits_launch() => {}
            Some(reply) if reply.stop_requested => {
                job.stop();
                return Step::Ending;
            }
            _ => {
                job.fail(
                    RemoteCommandErrorCode::AuthorityRevoked,
                    "Command authority was revoked",
                );
                return Step::Ending;
            }
        }
        if round < 2 {
            return Step::Revalidating {
                round: round + 1,
                id: None,
            };
        }
        self.launch_job(index)
    }

    fn launch_job(&mut self, index: usize) -> Step {
        let job = &mut self.jobs[index];
        let Some(request) = job.request.as_ref() else {
            job.fail(RemoteCommandErrorCode::InvalidRequest, "request missing");
            return Step::Ending;
        };
        // Same root rule as file operations (`projects.sources.chat-worktrees`):
        // the assistant's edits live in the chat worktree, so its commands
        // must run there. Only a read_write command may create the worktree.
        let source = &self.sources[job.source];
        let hosted = HostedSource {
            project_id: source.project_id.clone(),
            source_id: source.source_id.clone(),
            team_id: source.team_id.clone(),
            root: source.host.clone(),
            target_branch: source.target_branch.clone(),
        };
        let write = request.policy.source_access == SourceAccess::ReadWrite;
        let root = match request_root(&hosted, Some(&request.chat_id), write, now_ms()) {
            Ok(root) => root,
            Err(error) => {
                job.fail(
                    RemoteCommandErrorCode::LaunchFailed,
                    &format!("Chat worktree unavailable: {}", error.code),
                );
                return Step::Ending;
            }
        };
        let in_worktree = root.policy_source.is_some();
        match launch::launch(&root, request, in_worktree) {
            Ok(process) => {
                job.process = Some(process);
                job.events.push_status(
                    EventStatus::Running,
                    json!({"execution_id": job.execution_id, "status": "running"}),
                );
                Step::Running
            }
            Err(error) => {
                job.fail(error.code, &error.message);
                Step::Ending
            }
        }
    }

    fn finish_recover(&mut self, index: usize, outcome: RequestOutcome) -> Step {
        let job = &mut self.jobs[index];
        let lease = match outcome {
            Ok(ServerFrame::Recovered { payload, .. }) => {
                validate_lease_response(&payload, &job.execution_id).ok()
            }
            _ => None,
        };
        let Some(lease) = lease.filter(|l| !l.launch_allowed) else {
            self.need_discovery = true;
            return Step::Running;
        };
        let id = {
            let s = &self.sources[job.source];
            LeaseIdentity {
                execution_id: job.execution_id.clone(),
                project_id: s.project_id.clone(),
                source_id: s.source_id.clone(),
                source_session_id: self.session_id.clone(),
                team_id: s.team_id.clone(),
                lease_token: lease.lease_token.clone(),
                lease_generation: lease.lease_generation,
            }
        };
        job.lease_expires_at = lease.lease_expires_at;
        job.events.apply_lease(id, lease.last_sequence);
        if lease.stop_requested {
            job.stop();
        }
        if job.events.terminal_queued() {
            Step::Ending
        } else {
            Step::Running
        }
    }

    /// Move stream events of a running process into the event queue.

    /// Send the head event and apply its acknowledgement, one at a time.
    fn flush(&mut self, index: usize, now_ms: u64) {
        let key = self.sources[self.jobs[index].source].key.clone();
        let job = &mut self.jobs[index];
        if let Some((id, _)) = job.inflight {
            let Some(outcome) = self.transport.take_outcome(id) else {
                return;
            };
            job.inflight = None;
            match outcome {
                Ok(ServerFrame::EventAck(ack) | ServerFrame::CompletionAck(ack))
                    if job.events.acknowledge(ack.last_sequence, now_ms).is_ok() =>
                {
                    if ack.lease_expires_at > 0 && !job.events.is_completed() {
                        job.lease_expires_at = ack.lease_expires_at;
                    }
                }
                _ => {
                    // Lost lease or failed ack: rediscover and recover (TS drops the lease).
                    job.events.clear_lease();
                    self.need_discovery = true;
                    return;
                }
            }
        }
        if job.inflight.is_some() {
            return;
        }
        let frame = match job.events.next_frame(&key) {
            Ok(Some(frame)) => frame,
            Ok(None) => return,
            Err(error) => {
                self.notes
                    .push(format!("remote_command event refused {error:?}"));
                return;
            }
        };
        let execution_id = job.execution_id.clone();
        if let Ok(id) = self
            .transport
            .submit(frame.frame, frame.payload, &execution_id, now_ms)
        {
            job.inflight = Some((id, frame.sequence));
        }
    }
}
