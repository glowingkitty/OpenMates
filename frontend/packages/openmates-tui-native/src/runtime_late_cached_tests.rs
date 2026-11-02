//! One-use late-cache selection routing, authored UNRUN.
//! These pure tests do not authenticate, construct a cache publication or paint.
//! Existing SDK sealing, Store generation and UI consume guards stay mandatory.
//! The ordinary actual owned-peer terminal scenario remains required evidence.
//! This change closes reselect routing only, not the pre-terminal SDK gap.
// contract-test-file: tooling
use super::*;
fn pending() -> PendingCachedSelection {
    PendingCachedSelection {
        id: "synthetic-selection".into(),
        epoch: Stamp {
            security: 2,
            view: 3,
        },
        request: CancellationToken::new(),
    }
}
#[test]
fn later_cache_selection_requires_exact_security_view_auth_and_live_request() {
    let selection = pending();
    assert!(selection.is_current(selection.epoch, true));
    assert!(!selection.is_current(selection.epoch, false));
    for epoch in [
        Stamp {
            security: 1,
            view: 3,
        },
        Stamp {
            security: 2,
            view: 2,
        },
    ] {
        assert!(!selection.is_current(epoch, true));
    }
    selection.request.cancel();
    assert!(!selection.is_current(selection.epoch, true));
}
#[test]
fn original_boot_done_never_disarms_a_newer_open() {
    let selection = pending();
    assert!(!selection.is_completed_by(&Reply {
        epoch: Stamp {
            security: 2,
            view: 0
        },
        view: View::Done
    }));
    assert!(selection.is_completed_by(&Reply {
        epoch: selection.epoch,
        view: View::Done
    }));
}
#[test]
fn accepted_global_error_and_exact_open_failure_close_late_cache_opportunity() {
    let selection = pending();
    assert!(selection.is_completed_by(&Reply {
        epoch: Stamp {
            security: 2,
            view: 0
        },
        view: View::Failed(Error::Offline)
    }));
    assert!(selection.is_completed_by(&Reply {
        epoch: selection.epoch,
        view: View::ChatOpenFailed(Error::Forbidden)
    }));
    assert!(!selection.is_completed_by(&Reply {
        epoch: Stamp {
            security: 2,
            view: 1
        },
        view: View::ChatOpenFailed(Error::Offline)
    }));
}
#[test]
fn unrelated_status_and_items_do_not_complete_pending_selection() {
    let selection = pending();
    for view in [
        View::Status("Synthetic status"),
        View::Items(Workspace::Chats, vec![]),
    ] {
        assert!(!selection.is_completed_by(&Reply {
            epoch: selection.epoch,
            view
        }));
    }
}

#[test]
fn known_denial_for_older_view_still_closes_opportunity_but_canceled_monitor_does_not() {
    let selection = pending();
    let old = Stamp {
        security: 2,
        view: 1,
    };
    assert!(selection.is_completed_by(&Reply {
        epoch: old,
        view: View::ChatOpenFailed(Error::Forbidden)
    }));
    let canceled = CancellationToken::new();
    canceled.cancel();
    assert!(!selection.is_completed_by(&Reply {
        epoch: old,
        view: View::Monitor(Error::Forbidden, canceled)
    }));
    assert!(selection.is_completed_by(&Reply {
        epoch: old,
        view: View::Monitor(Error::Forbidden, CancellationToken::new())
    }));
}
