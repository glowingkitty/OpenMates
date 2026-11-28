use super::offline::{EditAccess, OfflineMerge, merge_offline};
use super::support::*;
use super::{LiveItemKind, LocalOp};

#[test]
fn outbox_is_sent_when_edit_access_remains() {
    let mut items = replicas(LiveItemKind::Code, "a\nb\n", 2);
    items[0]
        .apply_local_op(LocalOp::CodeSetText("a\nB\n".into()))
        .unwrap();
    let expected = items[0].outbox().to_vec();
    assert_eq!(
        merge_offline(&items[0], EditAccess::HasEdit).unwrap(),
        OfflineMerge::Send(expected)
    );
}

#[test]
fn lost_access_keeps_the_local_text_as_a_private_copy() {
    let mut items = replicas(LiveItemKind::Code, "a\nb\n", 2);
    items[0]
        .apply_local_op(LocalOp::CodeSetText("a\nB\n".into()))
        .unwrap();
    assert_eq!(
        merge_offline(&items[0], EditAccess::Lost).unwrap(),
        OfflineMerge::AccessLost {
            private_copy_text: "a\nB\n".into()
        }
    );
}

#[test]
fn lost_access_without_offline_work_sends_nothing() {
    let items = replicas(LiveItemKind::Code, "a\n", 1);
    assert_eq!(
        merge_offline(&items[0], EditAccess::Lost).unwrap(),
        OfflineMerge::Send(Vec::new())
    );
}
