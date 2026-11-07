//! Bulk chat-key load planning (keys lane K3, the Worker `crypto` unit).
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/features/auth#auth.keys.independent-unlock
//!
//! Mirrors the pure decisions of `loadChatKeysFromDatabase` in
//! `db/chatKeyManagement.ts` (`db/chatKeyBulkPlan.ts`): how collected encrypted chat
//! keys are split into decrypt batches and what the master-key retry timer does.
//! The page keeps the IndexedDB cursor, the master key and the unwrap/inject I/O;
//! no key material crosses here. Parity: `web_key_bulk_ts_vectors.json`, generated
//! from the TS reference and checked by `chatKeyBulkPlanVectors.test.ts`.

/// Encrypted chat keys unwrapped concurrently per batch.
pub const BATCH_SIZE: usize = 20;
/// Delay before the first and every following master-key retry.
pub const RETRY_DELAY_MS: u32 = 500;
/// Retries before the load gives up.
pub const MAX_RETRIES: u32 = 6;

/// What the master-key retry timer does.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RetryStep {
    /// The master key is available: decrypt the collected keys.
    Decrypt,
    /// Not available yet: schedule another attempt.
    Retry,
    /// Retries exhausted.
    GiveUp,
}

impl RetryStep {
    /// Wire string shared with the TS reference.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Decrypt => "decrypt",
            Self::Retry => "retry",
            Self::GiveUp => "give_up",
        }
    }
}

/// Half-open `(start, end)` index ranges of the decrypt batches for `count` keys.
pub fn batch_ranges(count: usize) -> Vec<(usize, usize)> {
    (0..count)
        .step_by(BATCH_SIZE)
        .map(|start| (start, (start + BATCH_SIZE).min(count)))
        .collect()
}

/// The retry timer's step after `retry_count` attempts (already incremented).
pub fn retry_step(retry_count: u32, master_key_available: bool) -> RetryStep {
    if master_key_available {
        RetryStep::Decrypt
    } else if retry_count < MAX_RETRIES {
        RetryStep::Retry
    } else {
        RetryStep::GiveUp
    }
}
