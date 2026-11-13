//! Per-turn send options and the delivery receipt over the `actor_tests`
//! fixture with a scripted client: reserved user-message id on the optimistic
//! message, queued receipt facts, and refused option combinations.
use super::actor_tests::{CHAT, Fixture, Sink, fixture, persisted, session};
use super::send_flows::TurnDispatch;
use super::send_request::{TurnSummary, receipt};
use super::*;
use crate::{
    client::{Client, ReservedTurnIds, SendQueueMode, SendStatus},
    error::{Error, Result},
    model::{Chat, Message, StreamUpdate},
};
use futures_util::future::BoxFuture;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const USER: &str = "66666666-6666-4666-8666-666666666666";
const SEND: RequestId = RequestId(11);

/// Plays a queued admission of `USER` and reports `summary`.
struct Queued {
    reserved: Option<String>,
    summary: Option<TurnSummary>,
}

impl TurnDispatch for Queued {
    fn dispatch<'a>(
        &'a mut self,
        _client: &'a mut Client,
        chat_id: Option<&'a str>,
        _text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        _cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Chat>> {
        let chat = chat_id.unwrap_or(CHAT).to_owned();
        Box::pin(async move {
            for update in [
                StreamUpdate::Started {
                    chat_id: chat.clone(),
                    message_id: USER.into(),
                    expects_reply: true,
                },
                StreamUpdate::Admitted {
                    chat_id: chat.clone(),
                    message_id: USER.into(),
                },
                StreamUpdate::Status("Message saved and queued.".into()),
            ] {
                updates.send(update).await.unwrap();
            }
            Ok(Chat {
                id: chat,
                messages: vec![Message {
                    id: USER.into(),
                    role: "user".into(),
                    content: "synthetic follow-up".into(),
                    ..Message::default()
                }],
                ..Chat::default()
            })
        })
    }

    fn reserved_user_id(&self) -> Option<&str> {
        self.reserved.as_deref()
    }

    fn take_summary(&mut self) -> Option<TurnSummary> {
        self.summary.take()
    }
}

fn queued_summary() -> TurnSummary {
    TurnSummary {
        status: SendStatus::Queued,
        chat_id: CHAT.into(),
        user_message_id: Some(USER.into()),
        assistant_message_id: None,
        queue_mode: Some(SendQueueMode::FollowUp),
        queue_revision: Some(3),
    }
}

async fn started_with_open_chat() -> (Fixture, Sink) {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    let record = chat_window_from_chat(
        &Chat {
            id: CHAT.into(),
            ..Chat::default()
        },
        ChatWindowSource::Canonical,
        Some(false),
        true,
        false,
        PiiRestoration::AllCachedUserRows,
    )
    .unwrap();
    let core = f.host.core_mut();
    core.begin_window(RequestId(5), CHAT);
    assert!(core.publish_window(RequestId(5), record).is_some());
    (f, sink)
}

#[tokio::test]
async fn reserved_message_id_keys_the_optimistic_message_and_the_receipt_reports_the_queue() {
    let (mut f, sink) = started_with_open_chat().await;
    let before = sink.events().len();
    let mut dispatch = Queued {
        reserved: Some(USER.into()),
        summary: Some(queued_summary()),
    };
    let receipt = receipt(
        &mut f.host,
        SEND,
        Some(CHAT.into()),
        "synthetic follow-up".into(),
        &sink,
        &CancellationToken::new(),
        &mut dispatch,
    )
    .await
    .unwrap();
    let events = sink.events()[before..].to_vec();
    let ViewEvent::ChatWindow { window, .. } = &events[0] else {
        panic!("the optimistic window comes first");
    };
    let optimistic = window.messages.last().unwrap();
    assert_eq!(
        optimistic.id, USER,
        "no provisional id when one is reserved"
    );
    assert_eq!(optimistic.send_state, Some(SendState::Sending));
    assert!(receipt.status == SendStatus::Queued);
    assert!(receipt.queue_mode == Some(SendQueueMode::FollowUp));
    assert_eq!(receipt.queue_revision, Some(3));
    assert_eq!(receipt.assistant_message_id, None);
    assert_eq!(receipt.user_message_id.as_deref(), Some(USER));
    assert_eq!(receipt.window.chat_id, CHAT);
}

#[tokio::test]
async fn a_dispatch_without_delivery_facts_is_a_protocol_error() {
    let (mut f, sink) = started_with_open_chat().await;
    let mut dispatch = Queued {
        reserved: None,
        summary: None,
    };
    let result = receipt(
        &mut f.host,
        SEND,
        Some(CHAT.into()),
        "synthetic follow-up".into(),
        &sink,
        &CancellationToken::new(),
        &mut dispatch,
    )
    .await;
    assert!(matches!(result, Err(Error::Protocol)));
}

#[tokio::test]
async fn refused_option_combinations_show_and_send_nothing() {
    let (mut f, sink) = started_with_open_chat().await;
    let before = sink.events().len();
    let refused = [
        SendTurnOptions {
            incognito: true,
            ..SendTurnOptions::default()
        },
        SendTurnOptions {
            slug: Some("kitchen-renovation".into()),
            ..SendTurnOptions::default()
        },
        SendTurnOptions {
            reserved: ReservedTurnIds {
                chat_id: Some(USER.into()),
                message_id: None,
            },
            ..SendTurnOptions::default()
        },
    ];
    for options in refused {
        let result = send_with(
            &mut f.host,
            SEND,
            Some(CHAT.into()),
            "synthetic question".into(),
            options,
            &sink,
            &CancellationToken::new(),
        )
        .await;
        assert!(matches!(result, Err(Error::Invalid(_))));
    }
    let incognito_slug = SendTurnOptions {
        incognito: true,
        slug: Some("kitchen-renovation".into()),
        ..SendTurnOptions::default()
    };
    let result = send_with(
        &mut f.host,
        SEND,
        None,
        "synthetic question".into(),
        incognito_slug,
        &sink,
        &CancellationToken::new(),
    )
    .await;
    assert!(matches!(result, Err(Error::Invalid(_))));
    assert_eq!(sink.events().len(), before, "nothing is shown");
}

#[test]
fn default_options_are_the_plain_send() {
    let options = SendTurnOptions::default().send_options();
    assert!(options.pii_detection && !options.incognito);
    assert!(options.slug.is_none() && options.reserved_ids.is_none());
    let reserved = SendTurnOptions {
        pii_detection: false,
        reserved: ReservedTurnIds {
            chat_id: None,
            message_id: Some(USER.into()),
        },
        ..SendTurnOptions::default()
    }
    .send_options();
    assert!(!reserved.pii_detection);
    assert_eq!(
        reserved
            .reserved_ids
            .and_then(|ids| ids.message_id)
            .as_deref(),
        Some(USER)
    );
}

#[test]
fn project_id_passes_to_the_client_and_must_be_canonical() {
    let project = "77777777-7777-4777-8777-777777777777";
    let options = SendTurnOptions {
        project_id: Some(project.into()),
        ..SendTurnOptions::default()
    };
    assert_eq!(options.send_options().project_id.as_deref(), Some(project));
    options.check(None).unwrap();
    options.check(Some(CHAT)).unwrap();
    let bad = SendTurnOptions {
        project_id: Some("not-a-uuid".into()),
        ..SendTurnOptions::default()
    };
    assert!(matches!(bad.check(None), Err(Error::Invalid(_))));
}
