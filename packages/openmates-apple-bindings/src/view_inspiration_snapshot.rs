//! Apple presentation adapter for the shared Daily Inspiration snapshot
//! selector. Scope and storage remain with the caller's existing cache session.

/// Selects the current private set from already scoped, decoded snapshot bytes.
/// See `daily-inspiration.personalized-priority`; an unusable set returns none.
#[uniffi::export]
pub fn select_personalized_inspiration_snapshot(
    payload: Vec<u8>,
    now_seconds: f64,
) -> Option<Vec<u8>> {
    openmates_sdk::client::overview::inspirations::snapshot::select_personalized_snapshot(
        &payload,
        now_seconds,
    )
}
