//! Canonical ciphertext freshness policy. No filesystem, auth or network IO.
//! A receipt describes canonical ciphertext freshness; it grants no authority.
use serde::{Deserialize, Serialize, ser::SerializeMap};
use serde_json::Value;
use sha2::{Digest, Sha256};

const RECEIPT_VERSION: u32 = 1;
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
struct SnapshotContents<'a>(&'a serde_json::Map<String, Value>);
impl Serialize for SnapshotContents<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut order = serde_json::Map::new();
        for key in self.0.keys() {
            order.insert(key.clone(), Value::Null);
        }
        order.remove(SNAPSHOT_FIELD);
        let mut map = serializer.serialize_map(Some(order.len()))?;
        for key in order.keys() {
            let value = self.0.get(key).ok_or_else(|| {
                <S::Error as serde::ser::Error>::custom("Snapshot projection key is missing.")
            })?;
            map.serialize_entry(key, value)?;
        }
        map.end()
    }
}
fn snapshot_digest(snapshot: &Value) -> Option<String> {
    // Every original field remains hashed; only the top-level receipt excludes
    // itself. The borrowed values retain exact legacy JSON/order/hash bytes.
    digest(&SnapshotContents(snapshot.as_object()?))
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
        snapshot: &Value,
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
        let Some((scope_sha256, snapshot_sha256)) = digest(scope).zip(snapshot_digest(snapshot))
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
            || snapshot_digest(snapshot).as_deref() != Some(receipt.snapshot_sha256.as_str())
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
        snapshot: &Value,
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
            && snapshot_digest(snapshot).as_deref() == Some(receipt.snapshot_sha256.as_str())
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
    fn policy(recovery: CanonicalRecoveryState) -> (ChatListFreshness, Value) {
        let mut policy = ChatListFreshness::default();
        let snapshot = json!({"chats":{},"wrappers":[],"history":{}});
        policy.canonical_committed(
            &scope(),
            &snapshot,
            Some(&clock(900, 900)),
            Some(&clock(1000, 1000)),
            recovery,
        );
        (policy, snapshot)
    }
    #[test]
    fn same_boot_restart_preserves_original_expiry_and_empty_complete_list() {
        let (policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let mut restored = ChatListFreshness::default();
        restored.restore(
            &scope(),
            &snapshot,
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        assert!(restored.may_read(&scope(), &snapshot, Some(&clock(300_999, 300_999)), clean()));
        // A second read, export or restore cannot move the 301000 boundary.
        assert!(!restored.may_read(&scope(), &snapshot, Some(&clock(301_000, 301_000)), clean()));
        let mut again = ChatListFreshness::default();
        again.restore(
            &scope(),
            &snapshot,
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        assert!(!again.may_read(&scope(), &snapshot, Some(&clock(301_000, 301_000)), clean()));
    }
    #[test]
    fn rollback_future_unknown_clock_and_other_boot_fail_closed() {
        let (policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(999, 1100)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 999)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(301_000, 1001)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, None, clean()));
        let other = CacheClockEvidence::from_platform("other-boot".into(), 1100, 1100).unwrap();
        assert!(!policy.may_read(&scope(), &snapshot, Some(&other), clean()));
    }
    #[test]
    fn pending_interval_and_own_restart_recovery_are_independent() {
        let (policy, snapshot) = policy(CanonicalRecoveryState::KnownRemotePending);
        assert!(policy.may_read(&scope(), &snapshot, Some(&clock(60_999, 60_999)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(61_000, 61_000)), clean()));
        assert!(!policy.may_read(
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
    fn changed_scope_snapshot_legacy_and_untrusted_restore_cannot_promote() {
        let (mut policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        let mut other = scope();
        other.active_team_id = Some("other-team");
        assert!(!policy.may_read(&other, &snapshot, Some(&clock(1100, 1100)), clean()));
        snapshot["history"]["different"] = json!([]);
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        policy.restore(
            &scope(),
            &snapshot,
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        policy.restore(
            &scope(),
            &json!({"chats":{}}),
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        let (mut policy, mut snapshot) = self::policy(CanonicalRecoveryState::Settled);
        snapshot[SNAPSHOT_FIELD] = policy.snapshot_metadata().unwrap();
        policy.restore(&scope(), &snapshot, SnapshotTrust::Untrusted);
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
    }
    #[test]
    fn failed_attempt_and_cancelled_or_mutating_paths_revoke_receipt() {
        let (mut policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        policy.invalidate();
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        policy.canonical_committed(
            &scope(),
            &snapshot,
            Some(&clock(1200, 1200)),
            Some(&clock(1100, 1100)),
            CanonicalRecoveryState::Settled,
        );
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1300, 1300)), clean()));
    }

    fn legacy_snapshot_bytes(snapshot: &Value) -> Option<Vec<u8>> {
        let mut canonical = snapshot.as_object()?.clone();
        canonical.remove(SNAPSHOT_FIELD);
        serde_json::to_vec(&canonical).ok()
    }
    fn assert_snapshot_digest_compatible(snapshot: &Value) {
        let original = snapshot.clone();
        let legacy = legacy_snapshot_bytes(snapshot);
        let borrowed = snapshot
            .as_object()
            .and_then(|map| serde_json::to_vec(&SnapshotContents(map)).ok());
        assert_eq!(
            borrowed, legacy,
            "receipt projection bytes must remain exact"
        );
        let expected = legacy.map(|bytes| {
            Sha256::digest(bytes)
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        });
        assert_eq!(snapshot_digest(snapshot), expected);
        assert_eq!(
            snapshot, &original,
            "hashing may not mutate ciphertext or receipt"
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn borrowed_projection_matches_legacy_for_nested_values_and_all_receipt_positions() {
        let values = vec![
            Value::Null,
            json!(false),
            json!(true),
            json!(i64::MIN),
            json!(u64::MAX),
            json!(0),
            json!(-0.0),
            json!(1.25),
            json!("quotes\" and slash\\ newline\n tab\t Unicode界é"),
            json!([]),
            json!({}),
            json!([null, true, -1, 1.5, {"z":[],"a":{"chat_list_freshness":"nested must remain"}}]),
        ];
        let receipts = vec![
            Value::Null,
            json!(false),
            json!(17),
            json!("malformed"),
            json!([]),
            json!({"unknown":[null,{"nested":"receipt data"}]}),
        ];
        for order in 0..3 {
            for position in 0..=values.len() + 1 {
                for receipt in &receipts {
                    let mut map = serde_json::Map::new();
                    for step in 0..=values.len() {
                        if step == position {
                            map.insert(SNAPSHOT_FIELD.into(), receipt.clone());
                        }
                        if step < values.len() {
                            let index = match order {
                                0 => step,
                                1 => values.len() - 1 - step,
                                _ => (step + 3) % values.len(),
                            };
                            map.insert(format!("field-{index:02}"), values[index].clone());
                        }
                    }
                    // position==len+1 is the absent-receipt case.
                    assert_snapshot_digest_compatible(&Value::Object(map));
                }
            }
        }
        assert_snapshot_digest_compatible(&json!({}));
        for receipt in &receipts {
            assert_snapshot_digest_compatible(&json!({"chat_list_freshness":receipt}));
        }
    }
    #[test]
    fn borrowed_projection_preserves_every_non_object_failure() {
        for snapshot in [
            Value::Null,
            json!(false),
            json!(true),
            json!(0),
            json!(-1),
            json!(1.5),
            json!("not an object"),
            json!([]),
            json!([{"chats":{}}]),
        ] {
            assert_snapshot_digest_compatible(&snapshot);
            assert_eq!(snapshot_digest(&snapshot), None);
        }
    }
    #[test]
    fn borrowed_projection_matches_large_ciphertext_without_losing_unknown_fields() {
        let mut chats = serde_json::Map::new();
        for index in 0..256 {
            chats.insert(format!("chat-{index:03}"),json!({"encrypted_title":"x".repeat(4096),"version":index,"nested":{"chat_list_freshness":[null,false,index]}}));
        }
        let snapshot = json!({"chats":chats,"history":{"messages":[{"ciphertext":"y".repeat(4096)}]},"wrappers":[{"unknown":[null,true,1.5]}],"embed_keys":{},"team_wrapped_key":null,"future_top_level":{"retained":"every byte"},"chat_list_freshness":{"malformed":"ignored only at top level"}});
        assert_snapshot_digest_compatible(&snapshot);
        let original = snapshot_digest(&snapshot);
        for field in [
            "chats",
            "history",
            "wrappers",
            "embed_keys",
            "team_wrapped_key",
            "future_top_level",
        ] {
            let mut changed = snapshot.clone();
            changed[field] = json!({"changed":true});
            assert_ne!(
                snapshot_digest(&changed),
                original,
                "every non-receipt field remains bound"
            );
        }
        let mut changed = snapshot.clone();
        changed[SNAPSHOT_FIELD] = json!({"different":"receipt"});
        assert_eq!(snapshot_digest(&changed), original);
        changed["chats"]["chat-000"]["nested"][SNAPSHOT_FIELD] = json!(["changed nested field"]);
        assert_ne!(
            snapshot_digest(&changed),
            original,
            "nested same-name fields must remain bound"
        );
    }
    #[test]
    fn exact_legacy_receipt_restores_but_all_invalid_receipts_and_changed_ciphertext_refuse() {
        let (policy, mut snapshot) = policy(CanonicalRecoveryState::Settled);
        let mut receipt: Receipt =
            serde_json::from_value(policy.snapshot_metadata().unwrap()).unwrap();
        let legacy = legacy_snapshot_bytes(&snapshot).unwrap();
        receipt.snapshot_sha256 = Sha256::digest(legacy)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        snapshot[SNAPSHOT_FIELD] = serde_json::to_value(receipt).unwrap();
        let mut restored = ChatListFreshness::default();
        restored.restore(
            &scope(),
            &snapshot,
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        assert!(restored.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        let mut changed = snapshot.clone();
        changed["history"]["changed"] = json!(["new ciphertext"]);
        assert!(!restored.may_read(&scope(), &changed, Some(&clock(1100, 1100)), clean()));
        for invalid in [
            Value::Null,
            json!(false),
            json!(17),
            json!("invalid"),
            json!([]),
            json!({}),
            json!({"version":1}),
            json!({"version":999,"scope_sha256":"untrusted"}),
        ] {
            let mut invalid_snapshot = snapshot.clone();
            invalid_snapshot[SNAPSHOT_FIELD] = invalid;
            restored.restore(
                &scope(),
                &invalid_snapshot,
                SnapshotTrust::AuthenticatedOwnerEnvelope,
            );
            assert!(!restored.may_read(
                &scope(),
                &invalid_snapshot,
                Some(&clock(1100, 1100)),
                clean()
            ));
        }
        restored.restore(&scope(), &snapshot, SnapshotTrust::Untrusted);
        assert!(!restored.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
    }
    #[test]
    fn borrowed_projection_cannot_renew_or_bypass_original_invalidation_pending_scope_and_clock_guards()
     {
        let (mut policy, snapshot) = policy(CanonicalRecoveryState::Settled);
        assert!(policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(301000, 301000)), clean()));
        assert!(!policy.may_read(&scope(), &snapshot, None, clean()));
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
            assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), requirements));
        }
        let mut other = scope();
        other.hashed_owner = "different-owner";
        assert!(!policy.may_read(&other, &snapshot, Some(&clock(1100, 1100)), clean()));
        let mut other = scope();
        other.authenticated_principal = Some("different-principal");
        assert!(!policy.may_read(&other, &snapshot, Some(&clock(1100, 1100)), clean()));
        policy.invalidate();
        assert!(!policy.may_read(&scope(), &snapshot, Some(&clock(1100, 1100)), clean()));
    }
}
