//! Durable delivery for the Task mutations beyond create/edit/done/delete/
//! Activity-add: block, unblock, skip, start, reorder, history restore,
//! project membership, dependency add/remove and Activity deletion.
//! Shared core (`openmates-sdk::work`); the CLI journal persists the exact
//! prepared `TaskDelivery` and replays it through `Tasks::execute_delivery`.
//! Mirrors npm `cli.ts handleTasks` payloads (blockUserTask, reorderUserTasks,
//! restoreObjectHistory, addTaskDependency, deleteUserTaskActivity);
//! spec: specifications/surfaces/cli tasks durable delivery.
//!
//! Invariant: the stored intent holds only ciphertext and safe metadata. Start
//! re-derives its transient plaintext from the current decrypted Task at
//! dispatch, so the private title never enters the journal. After an uncertain
//! transport the server state is read first; an already-applied mutation is
//! acknowledged, an untouched expected version is resent, and anything else is
//! a conflict that retains the original intent instead of overwriting newer work.
use super::*;

const BLOCKED_REASONS: [&str; 8] = [
    "needs_user_input",
    "waiting_for_approval",
    "missing_credentials",
    "ambiguous_requirement",
    "external_dependency",
    "environment_unavailable",
    "verification_failed",
    "other",
];

impl TaskMutationKind {
    /// Kinds executed and reconciled by this module rather than the original
    /// create/update/complete/delete/Activity delivery path.
    pub fn is_action(self) -> bool {
        matches!(
            self,
            Self::Block
                | Self::Unblock
                | Self::Skip
                | Self::Start
                | Self::Reorder
                | Self::Restore
                | Self::DependencyAdd
                | Self::DependencyRemove
                | Self::ActivityDelete
        )
    }
}

/// Normalize a blocked reason exactly like npm (`snake_case`, closed set).
pub(super) fn blocked_reason(reason: &str) -> Result<String> {
    let reason = reason.trim().to_lowercase().replace([' ', '-'], "_");
    if BLOCKED_REASONS.contains(&reason.as_str()) {
        Ok(reason)
    } else {
        Err(Error::Invalid("Invalid Task blocked reason code."))
    }
}
/// Block body without version/team; the optional reason text is encrypted
/// with the Task key so only ciphertext is sent or journaled.
pub(super) fn block_payload(task: &Resolved, reason: &str, text: Option<&str>) -> Result<Value> {
    let mut payload = json!({"blocked_reason_code":reason});
    if let Some(text) = text {
        payload["encrypted_blocked_reason"] =
            json!(crypto::server_fields::encrypt_text(text, &task.key, &[])?);
    }
    Ok(payload)
}
/// Transient server-side AI instruction fields, derived at dispatch only.
pub(super) fn add_start_plaintext(payload: &mut Value, task: &Resolved) {
    payload["plaintext_title"] = task.public["title"].clone();
    payload["plaintext_description"] = task.public["description"].clone();
    payload["plaintext_latest_instruction"] = task.public["latest_instruction"].clone();
}
fn kind_name(kind: WorkKind) -> &'static str {
    match kind {
        WorkKind::Task => "task",
        WorkKind::Plan => "plan",
    }
}
fn expected_version(delivery: &TaskDelivery) -> Result<u64> {
    let version = if delivery.kind == TaskMutationKind::Reorder {
        &delivery.input["moves"][0]["version"]
    } else {
        &delivery.input["version"]
    };
    version.as_u64().ok_or(Error::Protocol)
}

impl Tasks<'_> {
    /// Safe start-ai metadata (no plaintext) shared by direct and durable start.
    pub(super) fn start_intent(&self, task: &Resolved) -> Value {
        json!({"version":task.raw["version"],"primary_chat_id":task.public["primary_chat_id"],"linked_project_ids":task.public["linked_project_ids"],"team_id":self.filters.team_id})
    }
    /// Resolve anchors to canonical IDs and pin the moved Task's version.
    pub(super) async fn reorder_item(
        &mut self,
        task: &Resolved,
        movement: &mut TaskMove,
    ) -> Result<Value> {
        if movement.before_task_id.is_some() && movement.after_task_id.is_some() {
            return Err(Error::Invalid(
                "Choose either a before or after Task anchor.",
            ));
        }
        for anchor in [&mut movement.before_task_id, &mut movement.after_task_id]
            .into_iter()
            .flatten()
        {
            *anchor = string(&self.resolve(anchor).await?.raw, "task_id")?.into();
        }
        let mut item = serde_json::to_value(&*movement)?;
        item["task_id"] = task.raw["task_id"].clone();
        item["version"] = task.raw["version"].clone();
        Ok(item)
    }
    /// Project membership patch: append (deduplicated) or remove one project.
    pub(super) async fn project_patch(
        &mut self,
        id: &str,
        project: &str,
        add: bool,
    ) -> Result<TaskPatch> {
        let task = self.resolve(id).await?;
        let project = self.reference("project", project).await?;
        let mut projects = task.public["linked_project_ids"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|v| v.as_str().ok_or(Error::Protocol).map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        if add {
            if !projects.contains(&project) {
                projects.push(project);
            }
        } else {
            projects.retain(|id| *id != project);
        }
        Ok(TaskPatch {
            linked_project_ids: Some(projects),
            ..TaskPatch::default()
        })
    }

    async fn prepare_action(
        &mut self,
        id: &str,
        kind: TaskMutationKind,
        delivery_id: &str,
        input: impl FnOnce(&Self, &Resolved) -> Result<Value>,
    ) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        let mut payload = input(self, &task)?;
        if !matches!(
            kind,
            TaskMutationKind::Reorder
                | TaskMutationKind::DependencyAdd
                | TaskMutationKind::DependencyRemove
                | TaskMutationKind::ActivityDelete
        ) {
            payload["version"] = task.raw["version"].clone();
        }
        self.prepare(
            delivery_id,
            kind,
            string(&task.raw, "task_id")?.into(),
            payload,
            headers,
        )
        .await
    }
    /// Durable `tasks block`; the reason text is encrypted before journaling.
    pub async fn prepare_block(
        &mut self,
        id: &str,
        reason: &str,
        text: Option<&str>,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let reason = blocked_reason(reason)?;
        self.prepare_action(id, TaskMutationKind::Block, delivery_id, |me, task| {
            let mut payload = block_payload(task, &reason, text)?;
            payload["team_id"] = json!(me.filters.team_id);
            Ok(payload)
        })
        .await
    }
    /// Durable `tasks unblock` or `tasks skip` (version-pinned action routes).
    pub async fn prepare_transition(
        &mut self,
        id: &str,
        kind: TaskMutationKind,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        if !matches!(kind, TaskMutationKind::Unblock | TaskMutationKind::Skip) {
            return Err(Error::Invalid("Unsupported Task transition."));
        }
        self.prepare_action(id, kind, delivery_id, |me, _| {
            Ok(json!({"team_id":me.filters.team_id}))
        })
        .await
    }
    /// Durable `tasks start`: journals only safe metadata; see module docs.
    pub async fn prepare_start(&mut self, id: &str, delivery_id: &str) -> Result<TaskDelivery> {
        self.backend.verify_private_operation()?;
        let task = self.resolve(id).await?;
        if task.public["assignee_type"] == "external_ai" {
            return Err(Error::Invalid(
                "Resume an explicitly connected external Task; start runs OpenMates AI.",
            ));
        }
        self.prepare_action(id, TaskMutationKind::Start, delivery_id, |me, task| {
            Ok(me.start_intent(task))
        })
        .await
    }
    /// Durable `tasks reorder` for one move with canonical anchors.
    pub async fn prepare_reorder(
        &mut self,
        id: &str,
        mut movement: TaskMove,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let item = self.reorder_item(&task, &mut movement).await?;
        let team = self.filters.team_id.clone();
        self.prepare_action(id, TaskMutationKind::Reorder, delivery_id, move |_, _| {
            Ok(json!({"moves":[item],"team_id":team}))
        })
        .await
    }
    /// Durable `tasks restore`; the version pins reconciliation, not the route.
    pub async fn prepare_restore(
        &mut self,
        id: &str,
        entry: &str,
        state: RestoreState,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        entry_id(entry)?;
        self.prepare_action(id, TaskMutationKind::Restore, delivery_id, |_, _| {
            Ok(json!({"entry_id":entry,"state":state}))
        })
        .await
    }
    /// Durable `tasks add-to-project` / `remove-from-project` as an encrypted
    /// update (same intent npm queues for add-to-project).
    pub async fn prepare_project_membership(
        &mut self,
        id: &str,
        project: &str,
        add: bool,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let patch = self.project_patch(id, project, add).await?;
        self.prepare_update(id, patch, delivery_id).await
    }
    /// Durable `tasks activity delete` (logical tombstone of one entry).
    pub async fn prepare_activity_delete(
        &mut self,
        id: &str,
        entry: &str,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        entry_id(entry)?;
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        self.prepare(
            delivery_id,
            TaskMutationKind::ActivityDelete,
            string(&task.raw, "task_id")?.into(),
            json!({"entry_id":entry}),
            headers,
        )
        .await
    }
    /// Durable dependency add/remove for `task:<source>` → `kind:<target>`.
    pub async fn prepare_dependency(
        &mut self,
        source: &str,
        target: &DependencyTarget,
        add: bool,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let task = self.resolve(source).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let target_id = self.dependency_target(target).await?;
        let kind = kind_name(target.kind);
        let (mutation, input) = if add {
            (
                TaskMutationKind::DependencyAdd,
                json!({"target_ref":format!("{kind}:{target_id}")}),
            )
        } else {
            (
                TaskMutationKind::DependencyRemove,
                json!({"target_kind":kind,"target_id":target_id}),
            )
        };
        self.prepare(
            delivery_id,
            mutation,
            string(&task.raw, "task_id")?.into(),
            input,
            headers,
        )
        .await
    }

    /// Dispatch one validated action intent (see `execute_delivery`).
    pub(super) async fn execute_action_delivery(
        &mut self,
        delivery: &TaskDelivery,
        uncertain: bool,
        headers: &TaskHeaders,
    ) -> Result<Value> {
        if delivery.kind == TaskMutationKind::Start {
            self.backend.verify_private_operation()?;
        }
        if uncertain && let Some(value) = self.reconcile_action(delivery).await? {
            return Ok(value);
        }
        let id = delivery.task_id.as_str();
        let input = &delivery.input;
        let (method, route, body) = match delivery.kind {
            TaskMutationKind::Block | TaskMutationKind::Unblock | TaskMutationKind::Skip => {
                let action = match delivery.kind {
                    TaskMutationKind::Block => "block",
                    TaskMutationKind::Unblock => "unblock",
                    _ => "skip",
                };
                (
                    Method::POST,
                    format!("/v1/user-tasks/{id}/{action}"),
                    Some(input.clone()),
                )
            }
            TaskMutationKind::Start => {
                // Plaintext comes from the current row; a changed version is
                // rejected rather than starting with different content.
                let task = self.resolve(id).await?;
                if task.raw["version"] != input["version"] {
                    return Err(Error::Conflict);
                }
                let mut body = input.clone();
                add_start_plaintext(&mut body, &task);
                (
                    Method::POST,
                    format!("/v1/user-tasks/{id}/start-ai"),
                    Some(body),
                )
            }
            TaskMutationKind::Reorder => (
                Method::POST,
                "/v1/user-tasks/reorder".into(),
                Some(json!({"moves":input["moves"],"team_id":input["team_id"]})),
            ),
            TaskMutationKind::Restore => (
                Method::POST,
                self.scoped(&format!("/v1/user-tasks/{id}/restore"), &[]),
                Some(json!({"entry_id":input["entry_id"],"state":input["state"]})),
            ),
            TaskMutationKind::DependencyAdd => (
                Method::POST,
                self.scoped(&format!("/v1/user-tasks/{id}/dependencies"), &[]),
                Some(json!({"target_ref":input["target_ref"]})),
            ),
            TaskMutationKind::DependencyRemove => {
                let kind = input["target_kind"].as_str().ok_or(Error::Protocol)?;
                let target = input["target_id"].as_str().ok_or(Error::Protocol)?;
                if !["task", "plan"].contains(&kind) || target.contains(['/', '?', '#']) {
                    return Err(Error::Protocol);
                }
                (
                    Method::DELETE,
                    self.scoped(
                        &format!("/v1/user-tasks/{id}/dependencies/{kind}/{target}"),
                        &[],
                    ),
                    None,
                )
            }
            TaskMutationKind::ActivityDelete => {
                let entry = input["entry_id"].as_str().ok_or(Error::Protocol)?;
                entry_id(entry)?;
                let entry =
                    url::form_urlencoded::byte_serialize(entry.as_bytes()).collect::<String>();
                (
                    Method::DELETE,
                    self.scoped(&format!("/v1/user-tasks/{id}/activity/{entry}"), &[]),
                    None,
                )
            }
            _ => return Err(Error::Protocol),
        };
        let data = self
            .backend
            .request(method, &route, body, Some(headers))
            .await?;
        self.action_result(delivery, data).await
    }
    async fn action_result(&mut self, delivery: &TaskDelivery, data: Value) -> Result<Value> {
        match delivery.kind {
            TaskMutationKind::Restore
            | TaskMutationKind::DependencyAdd
            | TaskMutationKind::DependencyRemove => Ok(data),
            TaskMutationKind::ActivityDelete => {
                let task = self.resolve(&delivery.task_id).await?;
                if data["entry"]["entry_id"] != delivery.input["entry_id"] {
                    return Err(Error::Protocol);
                }
                task_crypto::activity(&task, &data["entry"])
            }
            TaskMutationKind::Reorder => {
                let (master, wrapping) = self.keys().await?;
                let mut tasks = Vec::new();
                for row in data["tasks"].as_array().ok_or(Error::Protocol)? {
                    tasks.push(
                        self.decode_row(row.clone(), &master, &wrapping)
                            .await?
                            .public,
                    );
                }
                Ok(Value::Array(tasks))
            }
            _ => {
                if data["task"]["task_id"] != delivery.task_id {
                    return Err(Error::Protocol);
                }
                let (master, wrapping) = self.keys().await?;
                Ok(self
                    .decode_row(data["task"].clone(), &master, &wrapping)
                    .await?
                    .public)
            }
        }
    }
    /// Read-before-retry after an uncertain outcome. `Some` = already applied,
    /// `None` = safe to resend the identical intent, `Conflict` = retained.
    async fn reconcile_action(&mut self, delivery: &TaskDelivery) -> Result<Option<Value>> {
        let id = delivery.task_id.clone();
        match delivery.kind {
            TaskMutationKind::DependencyAdd | TaskMutationKind::DependencyRemove => {
                let wanted = match delivery.kind {
                    TaskMutationKind::DependencyAdd => delivery.input["target_ref"].clone(),
                    _ => json!(format!(
                        "{}:{}",
                        delivery.input["target_kind"]
                            .as_str()
                            .ok_or(Error::Protocol)?,
                        delivery.input["target_id"]
                            .as_str()
                            .ok_or(Error::Protocol)?
                    )),
                };
                let p = self.scoped(&format!("/v1/user-tasks/{id}/dependencies"), &[]);
                let data = self.backend.request(Method::GET, &p, None, None).await?;
                let edge = data["dependencies"]
                    .as_array()
                    .ok_or(Error::Protocol)?
                    .iter()
                    .find(|edge| edge["target_ref"] == wanted)
                    .cloned();
                Ok(match (delivery.kind, edge) {
                    (TaskMutationKind::DependencyAdd, Some(edge)) => {
                        Some(json!({"dependency":edge}))
                    }
                    (TaskMutationKind::DependencyRemove, None) => Some(json!({"deleted":true})),
                    _ => None,
                })
            }
            TaskMutationKind::ActivityDelete => {
                let raw = self.current_raw(delivery).await?.ok_or(Error::Conflict)?;
                owner_unchanged(delivery, &raw)?;
                let Some(entry) = self
                    .find_activity_entry(&id, &delivery.input["entry_id"])
                    .await?
                else {
                    return Err(Error::Conflict);
                };
                if entry["kind"] != "tombstone" && entry["deleted_at"].is_null() {
                    return Ok(None);
                }
                let (master, wrapping) = self.keys().await?;
                let task = self.decode_row(raw, &master, &wrapping).await?;
                Ok(Some(task_crypto::activity(&task, &entry)?))
            }
            _ => {
                let raw = self.current_raw(delivery).await?.ok_or(Error::Conflict)?;
                if raw["task_id"] != delivery.task_id {
                    return Err(Error::Forbidden);
                }
                owner_unchanged(delivery, &raw)?;
                let expected = expected_version(delivery)?;
                let version = raw["version"].as_u64().ok_or(Error::Protocol)?;
                if version == expected {
                    return Ok(None);
                }
                if !action_applied(delivery, &raw, expected, version)? {
                    return Err(Error::Conflict);
                }
                let (master, wrapping) = self.keys().await?;
                let task = self.decode_row(raw, &master, &wrapping).await?.public;
                Ok(Some(if delivery.kind == TaskMutationKind::Reorder {
                    json!([task])
                } else {
                    task
                }))
            }
        }
    }
    /// Page the Activity history for one entry (tombstones included).
    pub(super) async fn find_activity_entry(
        &mut self,
        task_id: &str,
        entry_id: &Value,
    ) -> Result<Option<Value>> {
        let mut cursor: Option<String> = None;
        for _ in 0..100 {
            let mut query = vec![("limit".into(), "200".into())];
            if let Some(cursor) = &cursor {
                query.push(("cursor".into(), cursor.clone()));
            }
            let p = self.scoped(&format!("/v1/user-tasks/{task_id}/activity"), &query);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            for entry in data["entries"].as_array().ok_or(Error::Protocol)? {
                if entry["entry_id"] == *entry_id {
                    return Ok(Some(entry.clone()));
                }
            }
            let next = data["next_cursor"].as_str().filter(|s| !s.is_empty());
            if next.is_none() {
                return Ok(None);
            }
            if next == cursor.as_deref() {
                return Err(Error::Protocol);
            }
            cursor = next.map(str::to_owned);
        }
        Err(Error::Invalid(
            "Activity reconciliation exceeded the supported pagination limit.",
        ))
    }
}
fn owner_unchanged(delivery: &TaskDelivery, raw: &Value) -> Result<()> {
    if delivery
        .expected_owner_hash
        .as_ref()
        .is_some_and(|hash| raw["external_chat_lookup_hash"] != *hash)
    {
        return Err(Error::Conflict);
    }
    Ok(())
}
/// Whether the current row proves this exact action was applied once.
/// Start is goal-state idempotent: the queue may advance the row again after
/// admission, so any later version still assigned to OpenMates AI counts.
/// Restore has no observable fingerprint and is never assumed applied.
fn action_applied(
    delivery: &TaskDelivery,
    raw: &Value,
    expected: u64,
    version: u64,
) -> Result<bool> {
    let next = version == expected.checked_add(1).ok_or(Error::Protocol)?;
    let input = &delivery.input;
    Ok(match delivery.kind {
        TaskMutationKind::Block => {
            next && raw["status"] == "blocked"
                && raw["blocked_reason_code"] == input["blocked_reason_code"]
                && raw["encrypted_blocked_reason"]
                    == *input
                        .get("encrypted_blocked_reason")
                        .unwrap_or(&Value::Null)
        }
        TaskMutationKind::Unblock => {
            next && raw["status"] == "todo" && raw["blocked_reason_code"].is_null()
        }
        TaskMutationKind::Skip => {
            next && raw["status"] == "backlog" && raw["queue_state"] == "skipped"
        }
        TaskMutationKind::Start => {
            version > expected
                && raw["assignee_type"] == "openmates"
                && (raw["status"] == "todo" || raw["status"] == "in_progress")
        }
        TaskMutationKind::Reorder => {
            let movement = &input["moves"][0];
            next && movement
                .get("status")
                .is_none_or(|status| raw["status"] == *status)
                && movement
                    .get("position")
                    .is_none_or(|position| raw["position"] == *position)
        }
        _ => false,
    })
}

#[cfg(test)]
#[path = "action_delivery_tests.rs"]
mod tests;
