//! Endpoint logic of the sandbox host daemon (`docs/plans/hosted-project-sandbox/contracts.md`
//! section 2). Pure `(method, path, body) -> (status, json)`, so it is testable
//! without sockets. Errors never carry file contents or key material: details
//! are fixed strings or stable codes.
use super::owner::RunUser;
use crate::Error;
use crate::work::sandbox_key::{
    CODE_BINDING_MISMATCH, CODE_EXPIRED, CODE_OPEN_FAILED, SandboxBinding, SandboxKeyPair,
};
use super::super::{ProjectTree, Revision};
use serde_json::{Value, json};
use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use zeroize::Zeroizing;

/// Identity and settings the daemon starts with (from `OMSH_*` env).
pub struct HostConfig {
    /// Bearer token every request must carry.
    pub token: Zeroizing<String>,
    /// Sandbox id the grant must be bound to.
    pub sandbox_id: String,
    /// Job id the grant must be bound to.
    pub job_id: String,
    /// Project id the grant must be bound to.
    pub project_id: String,
    /// Chat the proposals belong to.
    pub chat_id: String,
    /// Team of the Project, if any.
    pub team_id: Option<String>,
    /// Where the Project files live.
    pub project_dir: PathBuf,
    /// User that runs model commands; files are handed to it.
    pub run_user: Option<RunUser>,
}

struct State {
    keypair: Option<SandboxKeyPair>,
    tree: Option<ProjectTree>,
}

/// The daemon: configuration, the key pair until the grant arrives, then the tree.
pub struct Host {
    cfg: HostConfig,
    public_key: String,
    state: Mutex<State>,
}

type Reply = Result<Value, Fail>;

struct Fail {
    status: u16,
    code: String,
    detail: &'static str,
}

fn fail(status: u16, code: &str, detail: &'static str) -> Fail {
    Fail { status, code: code.to_owned(), detail }
}

fn now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_secs()).unwrap_or(i64::MAX))
}

impl Host {
    /// Creates the daemon with a fresh key pair (memory only).
    pub fn new(cfg: HostConfig) -> Self {
        let keypair = SandboxKeyPair::generate();
        Self {
            public_key: keypair.public_key_b64(),
            state: Mutex::new(State { keypair: Some(keypair), tree: None }),
            cfg,
        }
    }

    /// Constant-time bearer check.
    pub fn authorized(&self, presented: Option<&str>) -> bool {
        use sha2::{Digest, Sha256};
        let a = Sha256::digest(presented.unwrap_or("").as_bytes());
        let b = Sha256::digest(self.cfg.token.as_bytes());
        let diff = a.iter().zip(b.iter()).fold(0u8, |acc, (x, y)| acc | (x ^ y));
        diff == 0 && presented.is_some()
    }

    /// Runs one endpoint (bearer already checked).
    pub fn handle(&self, method: &str, path: &str, body: &[u8]) -> (u16, Value) {
        let result = self.route(method, path, body);
        match result {
            Ok(value) => (200, value),
            Err(f) => (f.status, json!({"error": f.code, "detail": f.detail})),
        }
    }

    fn route(&self, method: &str, path: &str, body: &[u8]) -> Reply {
        let known = [
            ("GET", "/v1/hello"),
            ("POST", "/v1/key"),
            ("POST", "/v1/file-ids"),
            ("POST", "/v1/sync-in"),
            ("POST", "/v1/baseline"),
            ("POST", "/v1/op"),
            ("POST", "/v1/scan"),
            ("POST", "/v1/committed"),
            ("POST", "/v1/merge"),
        ];
        if !known.iter().any(|(_, p)| *p == path) {
            return Err(fail(404, "not_found", "unknown endpoint"));
        }
        if !known.contains(&(method, path)) {
            return Err(fail(405, "method_not_allowed", "wrong method"));
        }
        let args: Value = if method == "POST" {
            serde_json::from_slice(body).map_err(|_| fail(400, "invalid_json", "body is not JSON"))?
        } else {
            Value::Null
        };
        let mut state = self
            .state
            .lock()
            .map_err(|_| fail(500, "state_poisoned", "daemon state unavailable"))?;
        match path {
            "/v1/hello" => Ok(json!({
                "sandbox_public_key": self.public_key,
                "sandbox_id": self.cfg.sandbox_id,
                "job_id": self.cfg.job_id,
                "project_id": self.cfg.project_id,
                "has_key": state.tree.is_some(),
                "files": state.tree.as_ref().map_or(0, |t| t.paths().len()),
            })),
            "/v1/key" => self.key(&mut state, &args),
            _ => {
                let tree = state
                    .tree
                    .as_mut()
                    .ok_or_else(|| fail(409, "no_key", "the Project key was not handed over"))?;
                self.tree_endpoint(tree, path, &args)
            }
        }
    }

    fn key(&self, state: &mut State, args: &Value) -> Reply {
        if state.tree.is_some() {
            return Err(fail(409, "already_set", "key already set"));
        }
        let sealed = args["sealed_grant"]
            .as_str()
            .ok_or_else(|| fail(400, CODE_OPEN_FAILED, "grant missing"))?;
        let keypair = state
            .keypair
            .as_ref()
            .ok_or_else(|| fail(409, "already_set", "key already set"))?;
        let binding = SandboxBinding {
            sandbox_id: self.cfg.sandbox_id.clone(),
            job_id: self.cfg.job_id.clone(),
            project_id: self.cfg.project_id.clone(),
        };
        let key = keypair
            .open_grant(sealed, &binding, now_secs())
            .map_err(|e| match e {
                Error::Invalid(CODE_BINDING_MISMATCH) => {
                    fail(409, CODE_BINDING_MISMATCH, "grant is bound to another sandbox")
                }
                Error::Invalid(CODE_EXPIRED) => fail(409, CODE_EXPIRED, "grant expired"),
                _ => fail(400, CODE_OPEN_FAILED, "grant could not be opened"),
            })?;
        std::fs::create_dir_all(&self.cfg.project_dir)
            .map_err(|_| fail(500, "project_dir_failed", "cannot create the Project directory"))?;
        if let Some(user) = &self.cfg.run_user {
            user.chown(&self.cfg.project_dir);
        }
        let mut tree = ProjectTree::new(self.cfg.project_dir.clone(), key)
            .map_err(|_| fail(400, CODE_OPEN_FAILED, "grant could not be opened"))?;
        tree.set_project(&self.cfg.project_id, self.cfg.team_id.as_deref());
        // No chat key lives in the sandbox: new files are wrapped for the Project only.
        tree.set_chat(&self.cfg.chat_id, None);
        state.tree = Some(tree);
        // Drop the key pair: the grant cannot be opened a second time.
        state.keypair = None;
        Ok(json!({"ok": true}))
    }

    fn own(&self, paths: &[PathBuf]) {
        if let Some(user) = &self.cfg.run_user {
            for path in paths {
                user.chown_with_parents(&self.cfg.project_dir, path);
            }
        }
    }

    fn own_revisions(&self, tree: &ProjectTree, revisions: &[Revision]) {
        let paths: Vec<PathBuf> = revisions
            .iter()
            .filter_map(|r| tree.resolve(&r.path).ok())
            .collect();
        self.own(&paths);
    }

    fn tree_endpoint(&self, tree: &mut ProjectTree, path: &str, args: &Value) -> Reply {
        match path {
            "/v1/file-ids" => {
                let ids = tree
                    .register_links(&args["items"])
                    .map_err(|_| fail(400, "invalid_items", "item rows could not be read"))?;
                Ok(json!({"embed_ids": ids}))
            }
            "/v1/sync-in" => {
                let heads = args["heads"]
                    .as_array()
                    .ok_or_else(|| fail(400, "invalid_heads", "heads must be a list"))?;
                let report = tree.apply_linked_heads(heads);
                let paths: Vec<PathBuf> = tree
                    .paths()
                    .iter()
                    .filter_map(|p| tree.resolve(p).ok())
                    .collect();
                self.own(&paths);
                let failed: Vec<Value> = report
                    .failed
                    .iter()
                    .map(|(id, reason)| json!({"embed_id": id, "reason": reason}))
                    .collect();
                Ok(json!({"written": report.written, "bytes": report.bytes, "failed": failed}))
            }
            "/v1/baseline" => self.baseline(tree),
            "/v1/op" => {
                let operation = args["operation"]
                    .as_str()
                    .ok_or_else(|| fail(400, "invalid_operation", "operation missing"))?;
                let arguments = if args["arguments"].is_null() {
                    json!({})
                } else {
                    args["arguments"].clone()
                };
                match tree.run_op(operation, &arguments) {
                    Ok(outcome) => {
                        self.own_revisions(tree, &outcome.revisions);
                        Ok(json!({"result": outcome.result, "revisions": outcome.revisions}))
                    }
                    // A refusal is a model-facing result (same as the device executor).
                    Err(e) => Ok(json!({
                        "result": {"status": e.status(), "code": e.code(), "reason": e.code()},
                        "revisions": [],
                    })),
                }
            }
            "/v1/scan" => {
                let revisions = tree.scan_changes();
                Ok(json!({"revisions": revisions}))
            }
            "/v1/committed" => {
                let file = args["path"].as_str().unwrap_or_default();
                let embed_id = args["embed_id"].as_str().unwrap_or_default();
                let version = args["version_number"]
                    .as_i64()
                    .ok_or_else(|| fail(400, "invalid_version", "version_number missing"))?;
                tree.mark_committed(file, embed_id, version)
                    .map_err(|_| fail(404, "file_not_found", "file does not match"))?;
                Ok(json!({"ok": true}))
            }
            _ => {
                let file = args["path"]
                    .as_str()
                    .ok_or_else(|| fail(400, "invalid_path", "path missing"))?;
                let outcome = tree
                    .merge_with_head(file, &args["head"])
                    .map_err(|e| fail(400, "merge_failed", leak_free_code(e.code())))?;
                if let Ok(target) = tree.resolve(file) {
                    self.own(&[target]);
                }
                Ok(serde_json::to_value(outcome)
                    .map_err(|_| fail(500, "encode_failed", "cannot encode result"))?)
            }
        }
    }

    /// `git init` and one commit of the synced files, so commands see a clean tree.
    fn baseline(&self, tree: &ProjectTree) -> Reply {
        let dir = &self.cfg.project_dir;
        let git = |args: &[&str]| -> bool {
            Command::new("git")
                .current_dir(dir)
                .args(["-c", "user.name=OpenMates", "-c", "user.email=sandbox@localhost"])
                .args(["-c", "safe.directory=*"])
                .args(args)
                .output()
                .is_ok_and(|o| o.status.success())
        };
        let ok = (dir.join(".git").exists() || git(&["init", "-q"]))
            && git(&["add", "-A"])
            && git(&["commit", "-q", "--allow-empty", "-m", "baseline"]);
        if let Some(user) = &self.cfg.run_user {
            user.chown_tree(dir);
        }
        if !ok {
            return Err(fail(500, "baseline_failed", "git baseline failed"));
        }
        Ok(json!({"files": tree.paths().len(), "revision_map": tree.revision_map()}))
    }
}

/// Executor codes are stable identifiers; anything else is hidden.
fn leak_free_code(code: &str) -> &'static str {
    match code {
        "file_not_found" => "file_not_found",
        "merge_unavailable" => "merge_unavailable",
        _ => "merge_failed",
    }
}
