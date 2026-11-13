//! Web send preparation and offline outbox decisions for the shared Rust core Worker.
//!
//! spec: specifications/features/chats#chats.message.identity-idempotent
//!
//! Pure ports of `offlineChangeOrder.ts`, the receipt decision of
//! `offlineSyncBatch.ts` and `modelRoutingRestrictions.ts` and the deferred-delete replay check of `sendersSync.ts`. The page keeps IndexedDB, the WebSocket and the
//! per-connection batch bookkeeping; it sends the minimal change fields and
//! gets back which rows are ready to replay, in which order.
pub mod deferred_delete;
pub mod outbox_order;
pub mod outbox_receipt;
pub mod routing_restrictions;

#[cfg(test)]
mod tests;

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}
