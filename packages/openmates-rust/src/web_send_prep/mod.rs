//! Web send preparation and offline outbox decisions for the shared Rust core Worker.
//!
//! spec: specifications/features/chats#chats.message.identity-idempotent
//!
//! Pure ports of `offlineChangeOrder.ts` and the receipt decision of
//! `offlineSyncBatch.ts`. The page keeps IndexedDB, the WebSocket and the
//! per-connection batch bookkeeping; it sends the minimal change fields and
//! gets back which rows are ready to replay, in which order.
pub mod outbox_order;
pub mod outbox_receipt;

#[cfg(test)]
mod tests;

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}
