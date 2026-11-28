use super::timeline::*;

const MIN: u64 = 60_000;

fn change(who: &str, at: u64) -> TimelineEvent {
    TimelineEvent::Change {
        contributor: who.into(),
        at_ms: at,
    }
}

#[test]
fn keystrokes_group_into_one_session_that_closes_after_three_idle_minutes() {
    let mut t = Timeline::new();
    for i in 0..50 {
        assert!(t.push(change("u1", i * 1000)).is_empty());
    }
    assert!(t.tick(49_000 + 2 * MIN).is_empty());
    let closed = t.tick(49_000 + 3 * MIN);
    assert_eq!(closed.len(), 1);
    assert_eq!(closed[0].kind, VersionKind::Session);
    assert_eq!((closed[0].started_at, closed[0].ended_at), (0, 49_000));
}

#[test]
fn a_change_after_the_idle_gap_starts_a_new_session() {
    let mut t = Timeline::new();
    t.push(change("u1", 0));
    let closed = t.push(change("u2", 4 * MIN));
    assert_eq!(closed.len(), 1);
    assert_eq!(closed[0].contributors, ["u1"]);
    assert_eq!(t.flush()[0].contributors, ["u2"]);
}

#[test]
fn continuous_editing_closes_after_thirty_minutes_and_records_contributors() {
    let mut t = Timeline::new();
    let mut closed = Vec::new();
    for minute in 0..=31 {
        let who = if minute % 2 == 0 { "u1" } else { "u2" };
        closed.extend(t.push(change(who, minute * MIN)));
    }
    assert_eq!(closed.len(), 1);
    assert_eq!(closed[0].contributors, ["u1", "u2"]);
    assert_eq!(closed[0].ended_at, 29 * MIN);
}

#[test]
fn assistant_restore_and_commit_are_their_own_entries() {
    let mut t = Timeline::new();
    t.push(change("u1", 0));
    let out = t.push(TimelineEvent::Assistant {
        mate_name: "Sophia".into(),
        at_ms: MIN,
    });
    assert_eq!(
        out.iter().map(|v| v.kind).collect::<Vec<_>>(),
        [VersionKind::Session, VersionKind::Assistant]
    );
    assert_eq!(out[1].contributors, ["Sophia"]);
    let out = t.push(TimelineEvent::Restore {
        contributor: "u1".into(),
        at_ms: 2 * MIN,
    });
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].kind, VersionKind::Restore);
    let out = t.push(TimelineEvent::Commit {
        contributor: "u1".into(),
        at_ms: 3 * MIN,
    });
    assert_eq!(out[0].kind, VersionKind::Commit);
}

#[test]
fn naming_turns_the_open_session_into_a_named_version() {
    let mut t = Timeline::new();
    t.push(change("u1", 0));
    t.push(change("u2", MIN));
    let out = t.push(TimelineEvent::NameVersion {
        name: "Before review".into(),
        at_ms: 2 * MIN,
    });
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].kind, VersionKind::Named);
    assert_eq!(out[0].name.as_deref(), Some("Before review"));
    assert_eq!(out[0].contributors, ["u1", "u2"]);
    assert!(t.flush().is_empty());
}

fn session(day: u64, hour: u64) -> VersionCheckpoint {
    let at = day * 86_400_000 + hour * 3_600_000;
    VersionCheckpoint {
        kind: VersionKind::Session,
        contributors: vec![format!("u{hour}")],
        started_at: at,
        ended_at: at + MIN,
        name: None,
    }
}

#[test]
fn compaction_merges_old_unnamed_sessions_per_day_and_keeps_other_kinds() {
    let now = 100 * 86_400_000;
    let mut versions = vec![
        session(10, 1),
        session(10, 2),
        session(11, 1),
        session(90, 1),
        session(90, 2),
    ];
    let mut named = session(10, 3);
    named.kind = VersionKind::Named;
    named.name = Some("v1".into());
    versions.push(named);
    let mut assistant = session(10, 4);
    assistant.kind = VersionKind::Assistant;
    versions.push(assistant);
    let plan = compaction_plan(&versions, now);
    assert_eq!(plan.len(), 1);
    assert_eq!(plan[0].day, 10);
    assert_eq!(plan[0].indexes, [0, 1]);
    assert_eq!(plan[0].merged.contributors, ["u1", "u2"]);
    assert_eq!(plan[0].merged.started_at, versions[0].started_at);
    assert_eq!(plan[0].merged.ended_at, versions[1].ended_at);
}
