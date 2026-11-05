//! Visible-message read receipts (`visibleMessageReceipts.ts`).
//!
//! Bounds read telemetry across animation frames without retaining message
//! content: one in-flight send per message, a 30 s recheck interval, at most
//! 512 remembered message ids, and a full reset whenever the owner, chat,
//! workspace epoch or socket connection changes. The adapter performs the
//! actual send and reports its settlement with the returned ticket.
use std::collections::{HashMap, VecDeque};

pub const RECEIPT_RECHECK_MS: u64 = 30_000;
pub const MAX_RECENT_RECEIPTS: usize = 512;

/// Identity of the reporting context. `connection` is an adapter-assigned
/// token for the live socket object; `None` means no connection.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReceiptScope {
    pub owner_id: String,
    pub chat_id: String,
    pub epoch: u64,
    pub connection: Option<u64>,
}

/// What the adapter must do for one visible-frame report.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReceiptDecision {
    /// No owner or no connection: report `false`, send nothing.
    Refused,
    /// A send for this message is already in flight: await that same send.
    InFlight(u64),
    /// A receipt was sent within the recheck interval: report `true`.
    Recent,
    /// Send now and settle with this ticket.
    Send(u64),
}

#[derive(Clone, Copy)]
struct Entry {
    ticket: u64,
    sent_at_ms: Option<u64>,
}

#[derive(Default)]
pub struct VisibleReceiptLedger {
    scope: Option<ReceiptScope>,
    /// JavaScript `Map` insertion order: re-setting an existing key keeps it.
    order: VecDeque<String>,
    entries: HashMap<String, Entry>,
    next_ticket: u64,
}

impl VisibleReceiptLedger {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn report(
        &mut self,
        scope: &ReceiptScope,
        message_id: &str,
        now_ms: u64,
    ) -> ReceiptDecision {
        if scope.owner_id.is_empty() || scope.connection.is_none() {
            return ReceiptDecision::Refused;
        }
        if self.scope.as_ref() != Some(scope) {
            self.scope = Some(scope.clone());
            self.order.clear();
            self.entries.clear();
        }
        if let Some(previous) = self.entries.get(message_id) {
            match previous.sent_at_ms {
                None => return ReceiptDecision::InFlight(previous.ticket),
                Some(at) if now_ms.saturating_sub(at) < RECEIPT_RECHECK_MS => {
                    return ReceiptDecision::Recent;
                }
                Some(_) => {}
            }
        }
        while self.entries.len() >= MAX_RECENT_RECEIPTS {
            let Some(oldest) = self.order.pop_front() else {
                break;
            };
            self.entries.remove(&oldest);
        }
        self.next_ticket += 1;
        let ticket = self.next_ticket;
        if self
            .entries
            .insert(
                message_id.to_owned(),
                Entry {
                    ticket,
                    sent_at_ms: None,
                },
            )
            .is_none()
        {
            self.order.push_back(message_id.to_owned());
        }
        ReceiptDecision::Send(ticket)
    }

    /// Settle a send. Returns the value the original report resolves to.
    /// Tickets from an earlier scope or a replaced entry change nothing.
    pub fn settle(&mut self, ticket: u64, sent: bool, now_ms: u64) -> bool {
        let current = self
            .entries
            .iter()
            .find(|(_, entry)| entry.ticket == ticket && entry.sent_at_ms.is_none())
            .map(|(id, _)| id.clone());
        if let Some(id) = current {
            if sent {
                if let Some(entry) = self.entries.get_mut(&id) {
                    entry.sent_at_ms = Some(now_ms);
                }
            } else {
                // A failed receipt remains eligible on the next visible frame.
                self.entries.remove(&id);
                self.order.retain(|existing| *existing != id);
            }
        }
        sent
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn scope() -> ReceiptScope {
        ReceiptScope {
            owner_id: "owner".into(),
            chat_id: "chat".into(),
            epoch: 1,
            connection: Some(1),
        }
    }
    fn send(ledger: &mut VisibleReceiptLedger, scope: &ReceiptScope, id: &str, now: u64) -> u64 {
        match ledger.report(scope, id, now) {
            ReceiptDecision::Send(ticket) => ticket,
            other => panic!("expected send, got {other:?}"),
        }
    }

    // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
    #[test]
    fn concurrent_frames_coalesce_into_one_send_per_message() {
        let mut ledger = VisibleReceiptLedger::new();
        let active = scope();
        let ids = ["one", "two", "three", "four"];
        let tickets: Vec<_> = ids
            .iter()
            .map(|id| send(&mut ledger, &active, id, 0))
            .collect();
        for _ in 0..60 {
            for (id, ticket) in ids.iter().zip(&tickets) {
                assert_eq!(
                    ledger.report(&active, id, 1),
                    ReceiptDecision::InFlight(*ticket)
                );
            }
        }
        for ticket in tickets {
            assert!(ledger.settle(ticket, true, 2));
        }
        for id in ids {
            assert_eq!(ledger.report(&active, id, 3), ReceiptDecision::Recent);
        }
    }

    // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
    #[test]
    fn failures_retry_and_successes_recheck_after_the_interval() {
        let mut ledger = VisibleReceiptLedger::new();
        let active = scope();
        let first = send(&mut ledger, &active, "one", 0);
        assert!(!ledger.settle(first, false, 0));
        let second = send(&mut ledger, &active, "one", 0);
        assert!(ledger.settle(second, true, 0));
        assert_eq!(
            ledger.report(&active, "one", RECEIPT_RECHECK_MS - 1),
            ReceiptDecision::Recent
        );
        send(&mut ledger, &active, "one", RECEIPT_RECHECK_MS);
    }

    // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
    #[test]
    fn every_scope_field_resets_and_no_connection_is_refused() {
        let active = scope();
        let changes = [
            ReceiptScope {
                owner_id: "other".into(),
                ..scope()
            },
            ReceiptScope {
                chat_id: "other".into(),
                ..scope()
            },
            ReceiptScope {
                epoch: 2,
                ..scope()
            },
            ReceiptScope {
                connection: Some(2),
                ..scope()
            },
        ];
        for changed in changes {
            let mut ledger = VisibleReceiptLedger::new();
            let ticket = send(&mut ledger, &active, "one", 0);
            ledger.settle(ticket, true, 0);
            send(&mut ledger, &changed, "one", 1);
        }
        let mut ledger = VisibleReceiptLedger::new();
        assert_eq!(
            ledger.report(
                &ReceiptScope {
                    connection: None,
                    ..scope()
                },
                "one",
                0
            ),
            ReceiptDecision::Refused
        );
        assert_eq!(
            ledger.report(
                &ReceiptScope {
                    owner_id: String::new(),
                    ..scope()
                },
                "one",
                0
            ),
            ReceiptDecision::Refused
        );
        assert!(ledger.is_empty());
    }

    // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
    #[test]
    fn an_old_connection_completion_cannot_suppress_the_new_connection() {
        let mut ledger = VisibleReceiptLedger::new();
        let old = scope();
        let next = ReceiptScope {
            connection: Some(2),
            ..scope()
        };
        let previous = send(&mut ledger, &old, "one", 0);
        let current = send(&mut ledger, &next, "one", 1);
        assert!(ledger.settle(previous, true, 2));
        assert_eq!(
            ledger.report(&next, "one", 3),
            ReceiptDecision::InFlight(current)
        );
        assert!(ledger.settle(current, true, 4));
        assert_eq!(ledger.report(&next, "one", 5), ReceiptDecision::Recent);
    }

    #[test]
    fn the_ledger_evicts_oldest_insertions_and_keeps_reinserted_positions() {
        let mut ledger = VisibleReceiptLedger::new();
        let active = scope();
        for index in 0..MAX_RECENT_RECEIPTS - 1 {
            let ticket = send(&mut ledger, &active, &index.to_string(), 0);
            ledger.settle(ticket, true, 0);
        }
        // Below the bound a stale "0" is re-set in place: it stays the oldest.
        let now = RECEIPT_RECHECK_MS;
        let refreshed = send(&mut ledger, &active, "0", now);
        ledger.settle(refreshed, true, now);
        assert_eq!(ledger.len(), MAX_RECENT_RECEIPTS - 1);
        send(&mut ledger, &active, "fill", now);
        assert_eq!(ledger.len(), MAX_RECENT_RECEIPTS);
        // At the bound the oldest insertion ("0") is evicted for a new id.
        send(&mut ledger, &active, "new", now);
        assert_eq!(ledger.len(), MAX_RECENT_RECEIPTS);
        send(&mut ledger, &active, "0", now);
        // At the bound a stale id evicts the oldest first, even itself.
        let mut full = VisibleReceiptLedger::new();
        for index in 0..MAX_RECENT_RECEIPTS {
            let ticket = send(&mut full, &active, &index.to_string(), 0);
            full.settle(ticket, true, 0);
        }
        let ticket = send(&mut full, &active, "0", now);
        full.settle(ticket, true, now);
        send(&mut full, &active, "next", now);
        assert_eq!(full.report(&active, "0", now), ReceiptDecision::Recent);
        send(&mut full, &active, "1", now);
    }
}
