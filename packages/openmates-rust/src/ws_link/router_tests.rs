//! Handler routing: order, de-duplication, lanes and early buffering.
use super::router::EARLY_BUFFER_CAP;
use super::*;

#[test]
fn handlers_run_in_registration_order_without_duplicates() {
    let mut router = Router::new();
    assert_eq!(router.on("chat_deleted", 7), Registered::Added { replay: 0 });
    assert_eq!(router.on("chat_deleted", 3), Registered::Added { replay: 0 });
    assert_eq!(router.on("chat_deleted", 7), Registered::Duplicate);
    assert_eq!(router.route("chat_deleted"), Route::Dispatch { lane: Lane::Concurrent, handlers: &[7, 3] });
    assert!(router.off("chat_deleted", 7));
    assert!(!router.off("chat_deleted", 7));
    assert_eq!(router.route("chat_deleted"), Route::Dispatch { lane: Lane::Concurrent, handlers: &[3] });
    assert!(router.off("chat_deleted", 3));
    assert_eq!(router.handler_count("chat_deleted"), 0);
    assert_eq!(router.route("chat_deleted"), Route::Unhandled);
}

#[test]
fn phased_sync_frames_use_the_serialized_lane() {
    let mut router = Router::new();
    for message_type in ["phase_1_last_chat_ready", "phase_1b_chat_content_ready", "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready", "phased_sync_complete"] {
        router.on(message_type, 1);
        assert_eq!(router.route(message_type), Route::Dispatch { lane: Lane::Serialized, handlers: &[1] });
    }
    router.on("ai_message_update", 1);
    assert!(matches!(router.route("ai_message_update"), Route::Dispatch { lane: Lane::Concurrent, .. }));
}

#[test]
fn recovery_announcements_are_buffered_up_to_the_cap_and_replayed_once() {
    let mut router = Router::new();
    for index in 0..EARLY_BUFFER_CAP + 3 {
        let evict_oldest = index >= EARLY_BUFFER_CAP;
        assert_eq!(router.route("recovery_jobs_available"), Route::Buffer { evict_oldest });
    }
    assert_eq!(router.on("recovery_jobs_available", 9), Registered::Added { replay: EARLY_BUFFER_CAP });
    assert_eq!(router.on("recovery_jobs_available", 10), Registered::Added { replay: 0 }, "a later handler gets no replay");
    assert_eq!(router.route("recovery_jobs_available"), Route::Dispatch { lane: Lane::Concurrent, handlers: &[9, 10] });
}

#[test]
fn declared_families_buffer_until_their_dynamic_handlers_register() {
    let mut router = Router::new();
    assert_eq!(router.route("webhook_chat"), Route::Unhandled, "undeclared families keep the TypeScript drop");
    router.declare(Family::Webhooks);
    router.declare(Family::AppSettings);
    assert_eq!(router.route("webhook_chat"), Route::Buffer { evict_oldest: false });
    assert_eq!(router.route("webhook_chat"), Route::Buffer { evict_oldest: false });
    assert_eq!(router.route("reminder_fired"), Route::Buffer { evict_oldest: false });
    assert_eq!(router.route("message_highlight_added"), Route::Unhandled);
    assert_eq!(router.on("webhook_chat", 4), Registered::Added { replay: 2 });
    assert_eq!(router.route("webhook_chat"), Route::Dispatch { lane: Lane::Concurrent, handlers: &[4] });
}

#[test]
fn every_family_type_maps_back_to_its_family() {
    for family in Family::ALL {
        assert_eq!(Family::from_code(family.code()), Some(family));
        for message_type in family.types() {
            assert_eq!(Family::of(message_type), Some(family), "{message_type}");
        }
    }
    assert_eq!(Family::of("ai_message_update"), None);
    assert_eq!(Family::from_code(9), None);
}

#[test]
fn acknowledgements_need_no_handler() {
    let mut router = Router::new();
    for message_type in ["active_chat_set_ack", "pong", "draft_update_receipt", "draft_delete_receipt"] {
        assert_eq!(router.route(message_type), Route::Ignore);
    }
}

#[test]
fn clear_and_clear_all_remove_handlers() {
    let mut router = Router::new();
    router.on("a", 1);
    router.on("a", 2);
    router.on("b", 3);
    assert!(router.clear("a"));
    assert!(!router.clear("a"));
    router.on("a", 1);
    assert_eq!(router.clear_all(), 2);
    assert_eq!(router.route("b"), Route::Unhandled);
}

#[test]
fn classification_drives_the_link() {
    assert_eq!(Router::classify("pong", None), FrameKind::Pong);
    assert_eq!(Router::classify("server_restarting", None), FrameKind::ServerRestarting);
    assert_eq!(Router::classify("error", Some("Session expired")), FrameKind::AuthError("Session expired"));
    assert_eq!(Router::classify("error", Some("version_conflict")), FrameKind::Data);
    assert_eq!(Router::classify("error", None), FrameKind::Data);
    assert_eq!(Router::classify("ai_message_update", Some("Session expired")), FrameKind::Data);
}

#[test]
fn interned_routes_follow_every_registration_change() {
    let mut router = Router::new();
    let id = router.intern("webhook_chat").unwrap();
    assert_eq!(router.intern("webhook_chat"), Some(id));
    assert_eq!(router.type_name(id), Some("webhook_chat"));
    assert_eq!(router.route_id(id), Some(RouteAction::Unhandled));
    router.on("webhook_chat", 1);
    assert_eq!(router.route_id(id), Some(RouteAction::Dispatch(Lane::Concurrent)));
    // Memoized dispatch stays correct across off/on/clear/clear_all.
    assert!(router.off("webhook_chat", 1));
    assert_eq!(router.route_id(id), Some(RouteAction::Unhandled));
    router.on("webhook_chat", 2);
    assert_eq!(router.route_id(id), Some(RouteAction::Dispatch(Lane::Concurrent)));
    assert!(router.clear("webhook_chat"));
    assert_eq!(router.route_id(id), Some(RouteAction::Unhandled));
    router.on("webhook_chat", 3);
    router.route_id(id);
    router.clear_all();
    assert_eq!(router.route_id(id), Some(RouteAction::Unhandled));

    let phased = router.intern("phase_1_last_chat_ready").unwrap();
    router.on("phase_1_last_chat_ready", 4);
    assert_eq!(router.route_id(phased), Some(RouteAction::Dispatch(Lane::Serialized)));
    assert_eq!(router.route_id(9999), None);
}

#[test]
fn interned_buffering_counts_like_string_routing() {
    let mut router = Router::new();
    let id = router.intern("recovery_jobs_available").unwrap();
    for _ in 0..EARLY_BUFFER_CAP {
        assert_eq!(router.route_id(id), Some(RouteAction::Buffer { evict_oldest: false }));
    }
    assert_eq!(router.route("recovery_jobs_available").action(), RouteAction::Buffer { evict_oldest: true });
    assert_eq!(router.on("recovery_jobs_available", 1), Registered::Added { replay: EARLY_BUFFER_CAP });
}

#[test]
fn the_intern_table_is_bounded() {
    let mut router = Router::new();
    for index in 0..INTERN_CAP {
        assert_eq!(router.intern(&format!("type_{index}")), Some(index as u32));
    }
    assert_eq!(router.intern("one_too_many"), None);
    assert_eq!(router.intern("type_0"), Some(0));
}
