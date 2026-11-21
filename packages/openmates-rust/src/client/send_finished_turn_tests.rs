//! Resend of a finished turn completes from the canonical chat, without a claim.
use super::super::turn_runtime::TurnPhaseFuture;
use super::*;

const CHAT: &str = "chat-1";
const MESSAGE: &str = "user-msg";
const ASSISTANT: &str = "assistant-msg";
const TURN: &str = "turn-1";

/// Phases fake: only the canonical read, check and update delivery exist. Any
/// other phase (claim, replay, artifact persistence) would panic, proving the
/// finished-turn path never reaches them.
struct Fake {
    canonical: Chat,
    reads: usize,
}
impl SavedTurnClientPhases for Fake {
    fn check<'a>(
        &'a mut self,
        _s: &'a AsyncCryptoScope,
        _c: &'a str,
        _g: u64,
    ) -> TurnPhaseFuture<'a, ()> {
        Box::pin(async { Ok(()) })
    }
    fn deliver_update<'a>(
        &'a mut self,
        _s: &'a AsyncCryptoScope,
        _c: &'a str,
        updates: &'a mpsc::Sender<StreamUpdate>,
        _x: &'a CancellationToken,
        update: StreamUpdate,
    ) -> TurnPhaseFuture<'a, ()> {
        Box::pin(async move { updates.send(update).await.map_err(|_| Error::Cancelled) })
    }
    fn open_chat_live<'a>(&'a mut self, _id: &'a str) -> TurnPhaseFuture<'a, Chat> {
        self.reads += 1;
        let chat = self.canonical.clone();
        Box::pin(async move { Ok(chat) })
    }
    fn persist_focus_event<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _k: &'a str,
        _e: &'a Value,
        _c: &'a str,
        _key: &'a [u8; 32],
        _p: &'a mut Value,
    ) -> TurnPhaseFuture<'a, ()> {
        unreachable!("no focus")
    }
    fn project_routing_catalog<'a>(&'a mut self, _id: &'a str) -> TurnPhaseFuture<'a, Vec<Value>> {
        unreachable!("no catalog")
    }
    fn subchat_consent<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _e: &'a Value,
        _c: &'a str,
        _t: &'a str,
        _u: &'a mpsc::Sender<StreamUpdate>,
        _x: &'a CancellationToken,
        _p: SendConsentPolicy,
    ) -> TurnPhaseFuture<'a, Vec<(String, Value)>> {
        unreachable!("no consent")
    }
    fn memory_consent<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _e: &'a Value,
        _c: &'a str,
        _m: &'a str,
        _k: &'a [u8; 32],
        _me: &'a [Value],
        _ma: &'a [Value],
        _u: &'a mpsc::Sender<StreamUpdate>,
        _x: &'a CancellationToken,
        _p: SendConsentPolicy,
    ) -> TurnPhaseFuture<'a, (Vec<(String, Value)>, SendMemoryRequest, Vec<Value>)> {
        unreachable!("no memory consent")
    }
    fn e2b_consent<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _e: &'a Value,
        _c: &'a str,
        _k: &'a [u8; 32],
        _u: &'a mpsc::Sender<StreamUpdate>,
        _x: &'a CancellationToken,
        _p: E2bConsentPolicy,
    ) -> TurnPhaseFuture<'a, Option<SendE2bConsentRequest>> {
        unreachable!("no e2b consent")
    }
    fn replay_outputs<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _o: &'a BTreeMap<String, Value>,
        _r: Option<(&'a str, &'a [u8; 32])>,
    ) -> TurnPhaseFuture<'a, usize> {
        unreachable!("no replay")
    }
    fn persist_stream_artifacts<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _c: &'a str,
        _m: &'a str,
        _k: &'a [u8; 32],
        _t: &'a str,
        _e: &'a BTreeMap<String, Value>,
        _cp: &'a [Value],
    ) -> TurnPhaseFuture<'a, Vec<Item>> {
        unreachable!("no artifacts")
    }
    fn finish_task_jobs<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _o: &'a mut SendObservations,
        _i: &'a str,
        _m: &'a str,
        _k: &'a [u8; 32],
        _c: &'a CancellationToken,
        _op: &'a SendOptions,
    ) -> TurnPhaseFuture<'a, ()> {
        unreachable!("no task jobs")
    }
    fn project_create<'a>(
        &'a mut self,
        _w: &'a mut Socket,
        _k: &'a str,
        _e: &'a Value,
        _c: &'a str,
        _s: &'a mut project_create_request::ProjectCreateState,
    ) -> TurnPhaseFuture<'a, ()> {
        unreachable!("no project")
    }
    fn owner_id(&mut self) -> TurnPhaseFuture<'_, String> {
        unreachable!("no owner")
    }
    fn current_messages_version<'a>(
        &'a mut self,
        _i: &'a str,
        _k: &'a [u8; 32],
        _v: u64,
    ) -> TurnPhaseFuture<'a, u64> {
        unreachable!("no version")
    }
}

fn chat_with(assistant: Option<&str>) -> Chat {
    let mut chat = Chat {
        id: CHAT.into(),
        ..Default::default()
    };
    chat.messages.push(Message {
        id: MESSAGE.into(),
        role: "user".into(),
        content: "hi".into(),
        ..Message::default()
    });
    if let Some(content) = assistant {
        chat.messages.push(Message {
            id: ASSISTANT.into(),
            role: "assistant".into(),
            content: content.into(),
            ..Message::default()
        });
    }
    chat
}
fn confirmed(extra: Value) -> Value {
    let mut p = json!({"chat_id":CHAT,"message_id":MESSAGE,"temp_id":"t","turn_already_completed":true,"turn_id":TURN,"assistant_message_id":ASSISTANT});
    for (k, v) in extra.as_object().into_iter().flatten() {
        p[k] = v.clone();
    }
    p
}
async fn run(canonical: Chat, id: Option<&str>) -> (SendOutcome, Vec<StreamUpdate>, usize) {
    let mut phases = Fake {
        canonical,
        reads: 0,
    };
    let (updates, mut rx) = mpsc::channel(4);
    let api = "https://api.example.invalid";
    let client = Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: MESSAGE.into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    let scope = AsyncCryptoScope::begin(&client).unwrap();
    let outcome = complete_finished_turn(
        &mut phases,
        &scope,
        CHAT,
        MESSAGE,
        id,
        0,
        &updates,
        &CancellationToken::new(),
        SendObservations::default(),
    )
    .await
    .unwrap();
    drop(updates);
    let mut events = vec![];
    while let Some(e) = rx.recv().await {
        events.push(e);
    }
    (outcome, events, phases.reads)
}

#[tokio::test]
async fn resent_finished_turn_completes_with_canonical_assistant_content_and_no_claim() {
    let (outcome, events, reads) = run(chat_with(Some("stored answer")), Some(ASSISTANT)).await;
    assert!(matches!(outcome.status, SendStatus::Completed));
    assert_eq!(reads, 1);
    assert!(
        matches!(&events[..], [StreamUpdate::Completed{chat_id,message_id,content}]
        if chat_id == CHAT && message_id == ASSISTANT && content == "stored answer")
    );
}

#[tokio::test]
async fn resent_finished_turn_without_canonical_assistant_completes_quietly_without_a_blank_answer()
{
    let (outcome, events, _) = run(chat_with(None), Some(ASSISTANT)).await;
    assert!(matches!(outcome.status, SendStatus::Completed));
    assert_eq!(outcome.message_id.as_deref(), Some(ASSISTANT));
    assert!(
        events.is_empty(),
        "no empty Completed update may render a blank answer"
    );
}

#[test]
fn only_the_current_turns_already_completed_confirmation_is_recognised() {
    let ok = confirmed(json!({}));
    assert_eq!(
        finished_assistant_id("chat_message_confirmed", &ok, CHAT, MESSAGE, TURN),
        Some(Some(ASSISTANT))
    );
    assert_eq!(
        finished_assistant_id(
            "chat_message_confirmed",
            &confirmed(json!({"turn_id":""})),
            CHAT,
            MESSAGE,
            TURN
        ),
        Some(Some(ASSISTANT))
    );
    for bad in [
        finished_assistant_id("ai_typing_ended", &ok, CHAT, MESSAGE, TURN),
        finished_assistant_id("chat_message_confirmed", &ok, "other", MESSAGE, TURN),
        finished_assistant_id("chat_message_confirmed", &ok, CHAT, "other", TURN),
        finished_assistant_id("chat_message_confirmed", &ok, CHAT, MESSAGE, "other-turn"),
        finished_assistant_id(
            "chat_message_confirmed",
            &confirmed(json!({"turn_already_completed":false})),
            CHAT,
            MESSAGE,
            TURN,
        ),
    ] {
        assert_eq!(bad, None);
    }
}

#[test]
fn null_or_absent_assistant_id_still_marks_the_turn_finished() {
    for extra in [
        json!({"assistant_message_id":null}),
        json!({"assistant_message_id":""}),
    ] {
        assert_eq!(
            finished_assistant_id(
                "chat_message_confirmed",
                &confirmed(extra),
                CHAT,
                MESSAGE,
                TURN
            ),
            Some(None)
        );
    }
    let mut p = confirmed(json!({}));
    p.as_object_mut().unwrap().remove("assistant_message_id");
    assert_eq!(
        finished_assistant_id("chat_message_confirmed", &p, CHAT, MESSAGE, TURN),
        Some(None)
    );
}

#[tokio::test]
async fn missing_assistant_id_takes_the_first_assistant_message_after_the_user_message() {
    let (outcome, events, _) = run(chat_with(Some("stored answer")), None).await;
    assert!(matches!(outcome.status, SendStatus::Completed));
    assert_eq!(outcome.message_id.as_deref(), Some(ASSISTANT));
    assert!(
        matches!(&events[..], [StreamUpdate::Completed{message_id,content,..}]
        if message_id == ASSISTANT && content == "stored answer")
    );
}

#[tokio::test]
async fn missing_assistant_id_and_no_reply_completes_quietly_without_a_fake_id() {
    let (outcome, events, _) = run(chat_with(None), None).await;
    assert!(matches!(outcome.status, SendStatus::Completed));
    assert_eq!(outcome.message_id, None);
    assert!(
        events.is_empty(),
        "no empty Completed update may render a blank answer"
    );
}
