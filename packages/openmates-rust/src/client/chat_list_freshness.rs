//! Canonical ciphertext freshness policy. No filesystem, auth or network IO.
//! A receipt describes canonical ciphertext freshness; it grants no authority.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use serde_json::Value;
use sha2::{Digest, Sha256};

// Version 2 binds only the list-rendering inputs (rows, arrival order, key
// wrappers and the Team wrapped key). Version 1 receipts bound the whole
// ciphertext snapshot and are refused, which only loses the optimization.
const RECEIPT_VERSION: u32 = 2;
const DEFAULT_TTL_MS: u64 = 300_000;
const PENDING_TTL_MS: u64 = 60_000;
pub(super) const SNAPSHOT_FIELD: &str = "chat_list_freshness";

/// Supplied explicitly by a thin platform adapter. The boot namespace must be
/// stable across processes in one boot, change after reboot, and stay local.
/// `elapsed_ms` must include suspend. Ordinary SystemTime/Instant or file mtimes
/// alone do not meet this contract. Unsupported/untrusted clocks supply None.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CacheClockEvidence {
    boot_namespace: String,
    elapsed_ms: u64,
    wall_unix_ms: u64,
}
impl CacheClockEvidence {
    pub fn from_platform(
        boot_namespace: String,
        elapsed_ms: u64,
        wall_unix_ms: u64,
    ) -> Option<Self> {
        if boot_namespace.is_empty() || boot_namespace.len() > 256 || wall_unix_ms == 0 {
            return None;
        }
        Some(Self {
            boot_namespace,
            elapsed_ms,
            wall_unix_ms,
        })
    }
    fn age_since(&self, older: &Self) -> Option<u64> {
        if self.boot_namespace != older.boot_namespace {
            return None;
        }
        // Neither a future tick nor a wall clock predating the receipt is fresh.
        // Taking the larger age means wall rollback can never extend the TTL.
        let monotonic = self.elapsed_ms.checked_sub(older.elapsed_ms)?;
        let wall = self.wall_unix_ms.checked_sub(older.wall_unix_ms)?;
        Some(monotonic.max(wall))
    }
}

/// Stable across access-token/cookie rotation, unlike credential revisions.
/// Construct from the SDK's explicit canonical origin and selected session.
#[derive(Serialize)]
pub(super) struct CacheScope<'a> {
    pub canonical_api_origin: &'a str,
    pub hashed_owner: &'a str,
    pub active_team_id: Option<&'a str>,
    #[serde(skip)]
    pub authenticated_principal: Option<&'a str>,
}

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum CanonicalRecoveryState {
    Settled,
    /// Server discovery is complete, but there are known unclaimed remote
    /// outputs. This never describes owned jobs or an uncertain restart.
    KnownRemotePending,
}
impl CanonicalRecoveryState {
    fn ttl_ms(self) -> u64 {
        match self {
            Self::Settled => DEFAULT_TTL_MS,
            Self::KnownRemotePending => PENDING_TTL_MS,
        }
    }
}

/// The runtime must independently report own pending/restart checkpoints. A
/// cached receipt cannot clear newer journal evidence or consent/recovery work.
pub(super) struct CacheReadRequirements {
    pub force_refresh: bool,
    pub own_pending_or_uncertain_recovery: bool,
}

/// Only an authenticated local owner/key/context envelope is restoration proof.
/// This flag is an explicit adapter trust boundary, never read from cache JSON.
pub(super) enum SnapshotTrust {
    AuthenticatedOwnerEnvelope,
    Untrusted,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    version: u32,
    scope_sha256: String,
    snapshot_sha256: String,
    principal_sha256: String,
    completed: CacheClockEvidence,
    recovery: CanonicalRecoveryState,
}

#[derive(Default)]
pub(super) struct ChatListFreshness {
    receipt: Option<Receipt>,
}

fn digest(value: &impl Serialize) -> Option<String> {
    let bytes = serde_json::to_vec(value).ok()?;
    let hash = Sha256::digest(bytes);
    Some(hash.iter().map(|byte| format!("{byte:02x}")).collect())
}

// Preserve the legacy map backend's exact remove ordering while borrowing all
// nested Values. Only shallow top-level keys are copied; ciphertext/history
// values are never recursively cloned. serde_json/preserve_order can implement
// remove as swap_remove, so filtering input iteration alone is not equivalent.
struct HashWriter(Sha256);
impl std::io::Write for HashWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
const LIST_INPUTS_DOMAIN: &[u8] = b"openmates.chat-list-inputs.v2\n";
/// Streams the exact JSON of every list-rendering input into SHA-256 without
/// cloning or buffering the cache. History, embeds, selected first pages and
/// sync windows never influence list output and are deliberately not bound;
/// every owner/account/Team/principal/clock/recovery guard is unchanged.
fn list_inputs_digest<C, O, W, T>(chats: &C, order: O, wrappers: &W, team_wrapped_key: &T) -> Option<String>
where
    C: Serialize + ?Sized,
    O: Serialize,
    W: Serialize + ?Sized,
    T: Serialize + ?Sized,
{
    let mut writer = HashWriter(Sha256::new());
    writer.0.update(LIST_INPUTS_DOMAIN);
    serde_json::to_writer(&mut writer, chats).ok()?;
    writer.0.update(b"\n");
    serde_json::to_writer(&mut writer, &order).ok()?;
    writer.0.update(b"\n");
    serde_json::to_writer(&mut writer, wrappers).ok()?;
    writer.0.update(b"\n");
    serde_json::to_writer(&mut writer, team_wrapped_key).ok()?;
    Some(
        writer
            .0
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
    )
}
/// Client-side projection; byte-identical to [`snapshot_list_digest`] of the
/// snapshot the same Client would produce.
pub(super) fn client_list_digest(
    chats: &BTreeMap<String, Value>,
    arrival_order: Option<&Vec<String>>,
    wrappers: &[Value],
    team_wrapped_key: &Option<(String, String)>,
) -> Option<String> {
    list_inputs_digest(chats, arrival_order.map(|ids| (1u32, ids)), wrappers, team_wrapped_key)
}
fn snapshot_list_digest(snapshot: &Value) -> Option<String> {
    let map = snapshot.as_object()?;
    let null = Value::Null;
    let order = map
        .get(super::chat_arrival_order::SNAPSHOT_FIELD)
        .map(|order| (order.get("version").unwrap_or(&null), order.get("ids").unwrap_or(&null)));
    list_inputs_digest(
        map.get("chats").unwrap_or(&null),
        order,
        map.get("wrappers").unwrap_or(&null),
        map.get("team_wrapped_key").unwrap_or(&null),
    )
}

impl ChatListFreshness {
    /// Call before a canonical sync attempt, local mutation, owned recovery
    /// effect, account/Team change, clear, or cache replacement. Failure keeps
    /// ciphertext available for the separate offline path, but not fresh.
    pub(super) fn invalidate(&mut self) {
        self.receipt = None;
    }

    /// SDK-internal only: call after the shared full-sync proof is consumed,
    /// strict metadata+sync+recovery fences pass, all accepted effects settle,
    /// and any resulting canonical re-sync succeeds. Never on monitor-only or
    /// partial sync. `started` was sampled before this transaction began.
    /// The caller must first establish there is no owned/uncertain recovery.
    pub(super) fn canonical_committed(
        &mut self,
        scope: &CacheScope<'_>,
        list_digest: Option<&str>,
        started: Option<&CacheClockEvidence>,
        completed: Option<&CacheClockEvidence>,
        recovery: CanonicalRecoveryState,
    ) {
        self.invalidate();
        let Some((started, completed)) = started.zip(completed) else {
            return;
        };
        if completed.age_since(started).is_none() {
            return;
        }
        let Some((scope_sha256, snapshot_sha256)) =
            digest(scope).zip(list_digest.map(str::to_owned))
        else {
            return;
        };
        let Some(principal_sha256) = scope
            .authenticated_principal
            .filter(|id| !id.is_empty())
            .and_then(|id| digest(&id))
        else {
            return;
        };
        self.receipt = Some(Receipt {
            version: RECEIPT_VERSION,
            scope_sha256,
            snapshot_sha256,
            principal_sha256,
            completed: completed.clone(),
            recovery,
        });
    }

    /// Addition to the existing encrypted snapshot; saving never renews it.
    pub(super) fn snapshot_metadata(&self) -> Option<Value> {
        self.receipt
            .as_ref()
            .and_then(|value| serde_json::to_value(value).ok())
    }

    /// Legacy/malformed/unknown receipts only lose the optimization. Their
    /// ciphertext remains usable through existing validated offline behavior.
    /// Ordinary restore_ciphertext_snapshot must use Untrusted, not promote
    /// arbitrary application JSON into authenticated cache provenance.
    pub(super) fn restore(
        &mut self,
        scope: &CacheScope<'_>,
        snapshot: &Value,
        trust: SnapshotTrust,
    ) {
        self.invalidate();
        if !matches!(trust, SnapshotTrust::AuthenticatedOwnerEnvelope) {
            return;
        }
        let Some(value) = snapshot.get(SNAPSHOT_FIELD) else {
            return;
        };
        let Ok(receipt) = serde_json::from_value::<Receipt>(value.clone()) else {
            return;
        };
        if receipt.version != RECEIPT_VERSION
            || digest(scope).as_deref() != Some(receipt.scope_sha256.as_str())
            || snapshot_list_digest(snapshot).as_deref() != Some(receipt.snapshot_sha256.as_str())
        {
            return;
        }
        self.receipt = Some(receipt);
    }

    /// Read-only: no timestamp/TTL renewal. This is evaluated only after the
    /// native fresh session/protected-account gate and before final durability,
    /// cancellation/generation and output publication fences.
    pub(super) fn may_read(
        &self,
        scope: &CacheScope<'_>,
        list_digest: Option<&str>,
        now: Option<&CacheClockEvidence>,
        requirements: CacheReadRequirements,
    ) -> bool {
        if requirements.force_refresh || requirements.own_pending_or_uncertain_recovery {
            return false;
        }
        let Some((receipt, now)) = self.receipt.as_ref().zip(now) else {
            return false;
        };
        let Some(principal) = scope.authenticated_principal.filter(|id| !id.is_empty()) else {
            return false;
        };
        receipt.version == RECEIPT_VERSION
            && digest(&principal).as_deref() == Some(receipt.principal_sha256.as_str())
            && digest(scope).as_deref() == Some(receipt.scope_sha256.as_str())
            && list_digest == Some(receipt.snapshot_sha256.as_str())
            && now
                .age_since(&receipt.completed)
                .is_some_and(|age| age < receipt.recovery.ttl_ms())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn clock(tick: u64, wall: u64) -> CacheClockEvidence {
        CacheClockEvidence::from_platform("synthetic-boot".into(), tick, wall).unwrap()
    }
    fn scope() -> CacheScope<'static> {
        CacheScope {
            canonical_api_origin: "https://api.example.test",
            hashed_owner: "owner",
            active_team_id: None,
            authenticated_principal: Some("synthetic-principal"),
        }
    }
    fn clean() -> CacheReadRequirements {
        CacheReadRequirements {
            force_refresh: false,
            own_pending_or_uncertain_recovery: false,
        }
    }
    fn read(
        policy: &ChatListFreshness,
        scope: &CacheScope<'_>,
        snapshot: &Value,
        now: Option<&CacheClockEvidence>,
        requirements: CacheReadRequirements,
    ) -> bool {
        policy.may_read(scope, snapshot_list_digest(snapshot).as_deref(), now, requirements)
    }
    fn at(policy: &ChatListFreshness, snapshot: &Value, tick: u64) -> bool {
        read(policy, &scope(), snapshot, Some(&clock(tick, tick)), clean())
    }
    fn policy(recovery: CanonicalRecoveryState) -> (ChatListFreshness, Value) {
        let mut policy = ChatListFreshness::default();
        let snapshot = json!({"chats":{},"wrappers":[],"history":{}});
        policy.canonical_committed(
            &scope(),
            snapshot_list_digest(&snapshot).as_deref(),
            Some(&clock(900, 900)),
            Some(&clock(1000, 1000)),
            recovery,
        );
        (policy, snapshot)
    }
    fn restored(snapshot: &Value, trust: SnapshotTrust) -> ChatListFreshness {
        let mut restored = ChatListFreshness::default();
        restored.restore(&scope(), snapshot, trust);
        restored
    }
    #[test]
    fn same_boot_restart_preserves_original_expiry_and_empty_complete_list() {
        let (policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let restored = restored(&snapshot, SnapshotTrust::AuthenticatedOwnerEnvelope);
        assert!(at(&restored, &snapshot, 300_999));
        assert!(!at(&restored, &snapshot, 301_000));
        let again = self::restored(&snapshot, SnapshotTrust::AuthenticatedOwnerEnvelope);
        assert!(!at(&again, &snapshot, 301_000));
    }
    #[test]
    fn rollback_future_unknown_clock_and_other_boot_fail_closed() {
        let (policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        assert!(!read(&policy, &scope(), &snapshot, Some(&clock(999, 1100)), clean()));
        assert!(!read(&policy, &scope(), &snapshot, Some(&clock(1100, 999)), clean()));
        assert!(!read(&policy, &scope(), &snapshot, Some(&clock(301_000, 1001)), clean()));
        assert!(!read(&policy, &scope(), &snapshot, None, clean()));
        let other = CacheClockEvidence::from_platform("other-boot".into(), 1100, 1100).unwrap();
        assert!(!read(&policy, &scope(), &snapshot, Some(&other), clean()));
    }
    #[test]
    fn pending_interval_and_own_restart_recovery_are_independent() {
        let (policy, snapshot) = policy(CanonicalRecoveryState::KnownRemotePending);
        assert!(at(&policy, &snapshot, 60_999));
        assert!(!at(&policy, &snapshot, 61_000));
        assert!(!read(
            &policy,
            &scope(),
            &snapshot,
            Some(&clock(1100, 1100)),
            CacheReadRequirements {
                force_refresh: false,
                own_pending_or_uncertain_recovery: true
            }
        ));
    }
    #[test]
    fn changed_scope_list_input_legacy_and_untrusted_restore_cannot_promote() {
        let (mut policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let mut other = scope();
        other.active_team_id = Some("other-team");
        assert!(!read(&policy, &other, &snapshot, Some(&clock(1100, 1100)), clean()));
        snapshot["chats"]["different"] = json!({"id":"different"});
        assert!(!at(&policy, &snapshot, 1100));
        policy.restore(&scope(), &snapshot, SnapshotTrust::AuthenticatedOwnerEnvelope);
        assert!(!at(&policy, &snapshot, 1100));
        policy.restore(&scope(), &json!({"chats":{}}), SnapshotTrust::AuthenticatedOwnerEnvelope);
        assert!(!at(&policy, &snapshot, 1100));
        let (policy, mut snapshot) = self::policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let untrusted = restored(&snapshot, SnapshotTrust::Untrusted);
        assert!(!at(&untrusted, &snapshot, 1100));
    }
    #[test]
    fn failed_attempt_and_cancelled_or_mutating_paths_revoke_receipt() {
        let (mut policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        policy.invalidate();
        assert!(!at(&policy, &snapshot, 1100));
        policy.canonical_committed(
            &scope(),
            snapshot_list_digest(&snapshot).as_deref(),
            Some(&clock(1200, 1200)),
            Some(&clock(1100, 1100)),
            CanonicalRecoveryState::Settled,
        );
        assert!(!at(&policy, &snapshot, 1300));
        policy.canonical_committed(
            &scope(),
            None,
            Some(&clock(900, 900)),
            Some(&clock(1000, 1000)),
            CanonicalRecoveryState::Settled,
        );
        assert!(!at(&policy, &snapshot, 1100));
    }

    fn rich_inputs() -> (BTreeMap<String, Value>, Vec<String>, Vec<Value>, Option<(String, String)>) {
        let mut chats = BTreeMap::new();
        for index in 0..64 {
            chats.insert(
                format!("chat-{index:03}"),
                json!({"id":format!("chat-{index:03}"),"encrypted_title":"x".repeat(512),
                    "messages_v":index,"last_edited_overall_timestamp":1.5+index as f64,
                    "nested":{"chat_list_freshness":[null,false,index]},"unicode":"界é\"\\\n"}),
            );
        }
        let order = chats.keys().rev().cloned().collect();
        let wrappers = vec![json!({"hashed_chat_id":"h","encrypted_chat_key":"k","unknown":[null,true,-0.0]})];
        (chats, order, wrappers, Some(("team".into(), "wrapped".into())))
    }
    fn snapshot_of(
        chats: &BTreeMap<String, Value>,
        order: Option<&Vec<String>>,
        wrappers: &[Value],
        team: &Option<(String, String)>,
    ) -> Value {
        // Same construction as Client::ciphertext_snapshot.
        let mut snapshot = json!({"chats":chats,"wrappers":wrappers,"history":{"chat-000":[{"ciphertext":"y"}]},"embeds":{},"embed_keys":[],"team_wrapped_key":team});
        if let Some(order) = order {
            snapshot[super::super::chat_arrival_order::SNAPSHOT_FIELD] = json!({"version":1,"ids":order});
        }
        snapshot
    }
    #[test]
    fn client_projection_matches_snapshot_and_survives_disk_roundtrip() {
        let (chats, order, wrappers, team) = rich_inputs();
        for order in [None, Some(&order)] {
            for team in [None, team.clone()] {
                let client = client_list_digest(&chats, order, &wrappers, &team);
                assert!(client.is_some());
                let snapshot = snapshot_of(&chats, order, &wrappers, &team);
                assert_eq!(snapshot_list_digest(&snapshot), client);
                let disk: Value = serde_json::from_slice(&serde_json::to_vec(&snapshot).unwrap()).unwrap();
                assert_eq!(snapshot_list_digest(&disk), client);
                let empty = client_list_digest(&BTreeMap::new(), None, &[], &None);
                assert_eq!(
                    snapshot_list_digest(&snapshot_of(&BTreeMap::new(), None, &[], &None)),
                    empty
                );
            }
        }
    }
    #[test]
    fn every_list_input_is_bound_and_non_list_ciphertext_is_not() {
        let (chats, order, wrappers, team) = rich_inputs();
        let snapshot = snapshot_of(&chats, Some(&order), &wrappers, &team);
        let original = snapshot_list_digest(&snapshot);
        let order_field = super::super::chat_arrival_order::SNAPSHOT_FIELD;
        let mut changes: Vec<Box<dyn Fn(&mut Value)>> = vec![
            Box::new(|s| s["chats"]["chat-000"]["messages_v"] = json!(999)),
            Box::new(|s| s["chats"]["chat-001"]["encrypted_title"] = json!("changed")),
            Box::new(|s| s["chats"]["chat-002"]["nested"][SNAPSHOT_FIELD] = json!("nested is bound")),
            Box::new(|s| s["chats"]["chat-003"]["read_details"] = json!({"created_at":1})),
            Box::new(|s| { s["chats"].as_object_mut().unwrap().remove("chat-004"); }),
            Box::new(|s| s["wrappers"][0]["encrypted_chat_key"] = json!("other")),
            Box::new(|s| s["team_wrapped_key"] = Value::Null),
            Box::new(move |s| { s.as_object_mut().unwrap().remove(order_field); }),
            Box::new(move |s| s[order_field]["ids"].as_array_mut().unwrap().swap(0, 1)),
        ];
        for change in changes.drain(..) {
            let mut changed = snapshot.clone();
            change(&mut changed);
            assert_ne!(snapshot_list_digest(&changed), original);
        }
        for field in ["history", "embeds", "embed_keys", "future_top_level", "selected_first_pages_v1", SNAPSHOT_FIELD] {
            let mut changed = snapshot.clone();
            changed[field] = json!({"changed":"not a list input"});
            assert_eq!(snapshot_list_digest(&changed), original, "{field}");
        }
        assert_eq!(
            client_list_digest(&chats, Some(&order), &wrappers, &team),
            original
        );
    }
    #[test]
    fn non_object_snapshots_have_no_digest() {
        for snapshot in [Value::Null, json!(false), json!(0), json!("x"), json!([]), json!([{"chats":{}}])] {
            assert_eq!(snapshot_list_digest(&snapshot), None);
        }
    }
    #[test]
    fn version_one_and_invalid_receipts_refuse_while_exact_v2_restores() {
        let (policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let restored = restored(&snapshot, SnapshotTrust::AuthenticatedOwnerEnvelope);
        assert!(at(&restored, &snapshot, 1100));
        let mut v1 = snapshot.clone();
        v1[SNAPSHOT_FIELD]["version"] = json!(1);
        assert!(!at(&self::restored(&v1, SnapshotTrust::AuthenticatedOwnerEnvelope), &v1, 1100));
        for invalid in [
            Value::Null,
            json!(false),
            json!(17),
            json!("invalid"),
            json!([]),
            json!({}),
            json!({"version":2}),
            json!({"version":999,"scope_sha256":"untrusted"}),
        ] {
            let mut invalid_snapshot = snapshot.clone();
            invalid_snapshot[SNAPSHOT_FIELD] = invalid;
            let restored = self::restored(&invalid_snapshot, SnapshotTrust::AuthenticatedOwnerEnvelope);
            assert!(!at(&restored, &invalid_snapshot, 1100));
        }
        let mut changed = snapshot.clone();
        changed["chats"]["new"] = json!({"id":"new"});
        assert!(!at(&self::restored(&changed, SnapshotTrust::AuthenticatedOwnerEnvelope), &changed, 1100));
    }
    #[test]
    fn projection_cannot_renew_or_bypass_invalidation_pending_scope_and_clock_guards() {
        let (mut policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        assert!(at(&policy, &snapshot, 1100));
        assert!(!at(&policy, &snapshot, 301_000));
        assert!(!read(&policy, &scope(), &snapshot, None, clean()));
        assert!(!policy.may_read(&scope(), None, Some(&clock(1100, 1100)), clean()));
        for requirements in [
            CacheReadRequirements {
                force_refresh: true,
                own_pending_or_uncertain_recovery: false,
            },
            CacheReadRequirements {
                force_refresh: false,
                own_pending_or_uncertain_recovery: true,
            },
        ] {
            assert!(!read(&policy, &scope(), &snapshot, Some(&clock(1100, 1100)), requirements));
        }
        let mut other = scope();
        other.hashed_owner = "different-owner";
        assert!(!read(&policy, &other, &snapshot, Some(&clock(1100, 1100)), clean()));
        let mut other = scope();
        other.authenticated_principal = Some("different-principal");
        assert!(!read(&policy, &other, &snapshot, Some(&clock(1100, 1100)), clean()));
        policy.invalidate();
        assert!(!at(&policy, &snapshot, 1100));
    }
}
