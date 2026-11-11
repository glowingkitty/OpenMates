//! Image Enhance: start body from the head, job parsing, backoff wait with wake-ups and deadline, version N+1 content, the enhance commit request and route refusals.
use super::refusal::classify;
use super::*;
use crate::client::embed_user_revision::prepare_user_revision;
use crate::client::embed_write::keys::{NonceSource, decrypt_text, encrypt_text};

const EMBED: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const PROJECT: &str = "33333333-3333-4333-8333-333333333333";
const OP: &str = "44444444-4444-4444-8444-444444444444";
const KEY: [u8; 32] = [5; 32];

struct Nonces(u8);
impl NonceSource for Nonces {
    fn next_nonce(&mut self) -> crate::error::Result<[u8; 12]> {
        self.0 += 1;
        Ok([self.0; 12])
    }
}

fn head_fields(v2: bool) -> Vec<(&'static str, Value)> {
    let encryption = if v2 {
        json!("aes-gcm-nonce-prefixed-v1")
    } else {
        Value::Null
    };
    let mut original = json!({"s3_key": "u/v2_original.png", "width": 1024, "height": 768,
        "format": "png", "mime_type": "image/png"});
    if v2 {
        original["encryption"] = encryption;
    }
    vec![
        ("app_id", json!("images")),
        ("skill_id", json!("generated_image")),
        ("type", json!("image")),
        ("embed_ref", json!("cat-photo-x1y")),
        ("prompt", json!("A cat on a sofa")),
        (
            "files",
            json!({"original": original, "preview": {"s3_key": "u/v2_preview.webp"}}),
        ),
        ("aes_key", json!("A".repeat(44))),
        ("aes_nonce", json!(if v2 { "" } else { "bm9uY2Vub25jZTE=" })),
        ("vault_wrapped_aes_key", json!("vault:v1:old")),
        ("revised_from", json!({"embed_id": EMBED, "version": 1})),
    ]
}

fn head_content(v2: bool) -> String {
    toon_encode::encode_fields(&head_fields(v2)).expect("toon head")
}

fn head() -> EmbedHead {
    EmbedHead {
        embed_id: EMBED.into(),
        version: 2,
        encrypted_content: encrypt_text(&head_content(true), &KEY, None, &mut Nonces(100))
            .expect("seal"),
        created_at: 1_700_000_000,
        hashed_chat_id: None,
    }
}

fn chat() -> RevisionScope {
    RevisionScope::Chat {
        chat_id: CHAT.into(),
        team_id: None,
    }
}

fn result_value() -> Value {
    let variant = |name: &str, format: &str| {
        json!({"s3_key": format!("u/enh_{name}.{format}"), "width": 2048, "height": 1536,
            "size_bytes": 10, "format": format, "mime_type": format!("image/{format}"),
            "encryption": "aes-gcm-nonce-prefixed-v1"})
    };
    json!({
        "files": {"original": variant("original", "png"), "full": variant("full", "webp"),
            "preview": variant("preview", "webp")},
        "s3_base_url": "https://chatfiles.example.org", "aes_key": "B".repeat(44), "aes_nonce": "",
        "vault_wrapped_aes_key": "vault:v1:new",
        "s3_file_keys": [
            {"bucket": "chatfiles", "key": "u/enh_original.png"},
            {"bucket": "chatfiles", "key": "u/enh_full.webp"},
            {"bucket": "chatfiles", "key": "u/enh_preview.webp"},
        ],
        "output_filetype": "png", "generated_at": "2026-11-11T10:00:00+00:00",
        "model": "gemini-image-enhance", "provider": "google", "aspect_ratio": "4:3",
        "image_size": "2K", "enhanced_from": {"embed_id": EMBED, "version": 2},
    })
}

fn job_value(state: &str, result: bool) -> Value {
    let mut job = json!({"operation_id": OP, "embed_id": EMBED, "state": state,
        "base_version": 2, "target_version": 3, "credits": 63, "charged": state != "pending",
        "created_at": 1_800_000_000, "expires_at": 1_800_086_400});
    if result {
        job["result"] = result_value();
    }
    job
}

fn ready_job() -> EnhanceJob {
    parse_job(&job_value("ready", true), OP, Some(EMBED)).expect("ready job")
}

/// Scripted job routes on a fake clock: each pause advances the clock by its
/// delay unless the waker already fired.
struct FakeIo {
    posts: Vec<ImageEnhanceResult<Value>>,
    gets: Vec<ImageEnhanceResult<Value>>,
    posted: usize,
    reads: usize,
    pauses: Vec<u64>,
    now: i64,
}

impl FakeIo {
    fn new(posts: Vec<ImageEnhanceResult<Value>>, gets: Vec<ImageEnhanceResult<Value>>) -> Self {
        Self {
            posts,
            gets,
            posted: 0,
            reads: 0,
            pauses: Vec::new(),
            now: 1_800_000_000_000,
        }
    }
}

impl EnhanceIo for FakeIo {
    async fn post_enhance(&mut self, body: &Value) -> ImageEnhanceResult<Value> {
        assert_eq!(body["operation_id"], OP);
        self.posted += 1;
        assert!(!self.posts.is_empty(), "unexpected POST");
        self.posts.remove(0)
    }
    async fn get_enhance(&mut self, operation_id: &str) -> ImageEnhanceResult<Value> {
        assert_eq!(operation_id, OP);
        self.reads += 1;
        assert!(!self.gets.is_empty(), "unexpected GET");
        self.gets.remove(0)
    }
    async fn pause(&mut self, delay: Duration, waker: Option<&ImageEnhanceWaker>) {
        if waker.is_some_and(|waker| waker.signal().is_cancelled()) {
            self.pauses.push(0);
            return;
        }
        let delay = delay.as_millis() as u64;
        self.pauses.push(delay);
        self.now += delay as i64;
    }
    fn now_ms(&self) -> i64 {
        self.now
    }
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.faithful-2k
#[test]
fn builds_the_start_body_from_the_heads_original_file() {
    let body = start_body(&head(), &head_content(true), &chat(), OP).expect("body");
    assert_eq!(body["operation_id"], OP);
    assert_eq!(body["embed_id"], EMBED);
    assert_eq!(body["expected_version"], 2);
    assert_eq!(body["scope"], json!({"kind": "chat", "chat_id": CHAT}));
    assert_eq!(
        body["source"],
        json!({"s3_key": "u/v2_original.png", "aes_key": "A".repeat(44), "format": "png",
            "width": 1024, "height": 768, "encryption": "aes-gcm-nonce-prefixed-v1"})
    );
    let legacy = start_body(&head(), &head_content(false), &chat(), OP).expect("legacy");
    assert_eq!(legacy["source"]["aes_nonce"], "bm9uY2Vub25jZTE=");
    assert!(legacy["source"].get("encryption").is_none());
    let project = RevisionScope::Project {
        project_id: PROJECT.into(),
        team_id: None,
    };
    let in_project = start_body(&head(), &head_content(true), &project, OP).expect("project");
    assert_eq!(
        in_project["scope"],
        json!({"kind": "project", "project_id": PROJECT})
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[test]
fn refuses_team_scope_and_non_images_before_any_request() {
    let team = RevisionScope::Chat {
        chat_id: CHAT.into(),
        team_id: Some("team-1".into()),
    };
    let refused = start_body(&head(), &head_content(true), &team, OP);
    assert_eq!(refused.map(|_| ()), Err(ImageEnhanceError::TeamUnavailable));
    let diagram = json!({"app_id": "diagrams", "skill_id": "html"}).to_string();
    assert_eq!(
        start_body(&head(), &diagram, &chat(), OP).map(|_| ()),
        Err(ImageEnhanceError::InvalidSource {
            code: "not_an_image"
        })
    );
    let mut svg = head_fields(true);
    svg[5].1["original"]["format"] = json!("svg");
    let svg = toon_encode::encode_fields(&svg).expect("toon");
    assert_eq!(
        start_body(&head(), &svg, &chat(), OP).map(|_| ()),
        Err(ImageEnhanceError::InvalidSource {
            code: "unsupported_format"
        })
    );
    assert_eq!(
        start_body(&head(), &head_content(true), &chat(), "op-1").map(|_| ()),
        Err(ImageEnhanceError::InvalidSource {
            code: "invalid_operation_id"
        })
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[tokio::test]
async fn a_lost_start_answer_is_resent_under_the_same_operation() {
    let mut io = FakeIo::new(
        vec![Err(Error::Offline.into()), Ok(job_value("pending", false))],
        vec![],
    );
    let body = start_body(&head(), &head_content(true), &chat(), OP).expect("body");
    let job = start_job(&mut io, &body, OP, EMBED).await.expect("job");
    assert_eq!(
        (io.posted, job.state, job.credits),
        (2, EnhanceJobState::Pending, 63)
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.faithful-2k
#[tokio::test]
async fn waits_with_backoff_until_the_result_is_ready() {
    let mut io = FakeIo::new(
        vec![],
        vec![
            Ok(job_value("pending", false)),
            Err(ImageEnhanceError::Busy),
            Err(Error::Offline.into()),
            Ok(job_value("ready", true)),
        ],
    );
    let job = wait_job(
        &mut io,
        OP,
        Some(EMBED),
        None,
        DEFAULT_ENHANCE_DEADLINE,
        false,
    )
    .await
    .expect("ready");
    assert_eq!(job.state, EnhanceJobState::Ready);
    assert!(job.result().is_some());
    assert_eq!(io.pauses, vec![1_500, 2_000, 3_000, 5_000]);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.button
#[tokio::test]
async fn a_forwarded_ready_event_ends_the_delay_at_once() {
    let waker = ImageEnhanceWaker::new();
    let frame = json!({"operation_id": OP, "embed_id": EMBED});
    assert!(waker.notify_frame("image_enhance_ready", &frame));
    assert!(!waker.notify_frame("embed_updated", &frame));
    let mut io = FakeIo::new(vec![], vec![Ok(job_value("ready", true))]);
    wait_job(
        &mut io,
        OP,
        Some(EMBED),
        Some(&waker),
        DEFAULT_ENHANCE_DEADLINE,
        false,
    )
    .await
    .expect("ready");
    assert_eq!(io.pauses, vec![0]);
    // One wake ends exactly one delay.
    assert!(!waker.signal().is_cancelled());
    assert_eq!(waker.last_event().map(|e| e.ready), Some(true));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[tokio::test]
async fn a_failed_job_reports_its_code_and_was_not_charged() {
    let mut failed = job_value("failed", false);
    failed["error_code"] = json!("provider_failed");
    let mut io = FakeIo::new(vec![], vec![Ok(failed.clone())]);
    let error = wait_job(&mut io, OP, None, None, DEFAULT_ENHANCE_DEADLINE, true).await;
    assert_eq!(
        error.map(|_| ()),
        Err(ImageEnhanceError::Failed {
            operation_id: OP.into(),
            code: "provider_failed".into()
        })
    );
    failed["charged"] = json!(false);
    assert!(!parse_job(&failed, OP, None).expect("failed").charged);
    let event = parse_image_enhance_event(
        "image_enhance_failed",
        &json!({"operation_id": OP, "embed_id": EMBED, "error_code": "<script>"}),
    )
    .expect("event");
    assert_eq!(event.error_code.as_deref(), Some("enhance_failed"));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[tokio::test]
async fn the_deadline_ends_the_wait_and_keeps_the_operation_id() {
    let pending = || Ok(job_value("pending", false));
    let mut io = FakeIo::new(vec![], vec![pending(), pending(), pending(), pending()]);
    let error = wait_job(&mut io, OP, None, None, Duration::from_secs(6), true).await;
    assert_eq!(
        error.map(|_| ()),
        Err(ImageEnhanceError::Timeout {
            operation_id: OP.into()
        })
    );
    // 1.5 + 2 + 2.5 (capped at the deadline) seconds.
    assert_eq!(io.pauses, vec![1_500, 2_000, 2_500]);
    assert!(
        ImageEnhanceError::Timeout {
            operation_id: OP.into()
        }
        .is_retryable()
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[test]
fn a_ready_job_without_result_is_expired_and_a_foreign_result_is_refused() {
    let job = parse_job(&job_value("ready", false), OP, None).expect("job");
    assert_eq!(job.state, EnhanceJobState::Expired);
    assert_eq!(
        unsaved_job_error(&job),
        ImageEnhanceError::Expired {
            operation_id: OP.into()
        }
    );
    let mut foreign = job_value("ready", true);
    foreign["result"]["enhanced_from"]["version"] = json!(1);
    assert_eq!(
        parse_job(&foreign, OP, None).map(|_| ()),
        Err(ImageEnhanceError::Transport(Error::Protocol))
    );
    let mut stray = job_value("ready", true);
    stray["result"]["s3_file_keys"] = json!([{"bucket": "chatfiles", "key": "other"}]);
    assert!(parse_job(&stray, OP, None).is_err());
    assert!(parse_job(&job_value("ready", true), OP, Some("another-embed")).is_err());
    assert!(!format!("{:?}", ready_job()).contains(&"B".repeat(44)));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.faithful-2k
#[test]
fn version_n_plus_1_has_the_enhanced_files_and_keeps_the_image_identity() {
    let job = ready_job();
    let content =
        enhanced_content(&head_content(true), job.result().expect("result")).expect("content");
    assert!(
        !content.trim_start().starts_with('{'),
        "TOON head stays TOON"
    );
    let decoded = decode_object(&content).expect("decodes");
    assert_eq!(decoded["embed_ref"], "cat-photo-x1y");
    assert_eq!(decoded["prompt"], "A cat on a sofa");
    assert_eq!(decoded["aes_key"], "B".repeat(44));
    assert_eq!(decoded["vault_wrapped_aes_key"], "vault:v1:new");
    assert_eq!(decoded["files"]["original"]["s3_key"], "u/enh_original.png");
    assert_eq!(decoded["image_size"], "2K");
    assert_eq!(
        decoded["enhanced_from"],
        json!({"embed_id": EMBED, "version": 2})
    );
    assert!(decoded.get("revised_from").is_none() && decoded.get("s3_file_keys").is_none());
    let json_head = serde_json::to_string(&Value::Object(
        head_fields(true)
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    ))
    .expect("json head");
    let as_json = enhanced_content(&json_head, job.result().expect("result")).expect("json");
    assert!(as_json.starts_with('{'));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.faithful-2k,embed-user-edits.enhance.billed-once-refunded-on-failure
#[test]
fn the_result_is_committed_as_an_enhance_of_the_same_embed_under_a_derived_id() {
    let job = ready_job();
    let request =
        enhance_revision_request(head(), &head_content(true), chat(), &job).expect("request");
    assert_eq!(request.action, EmbedUpdateAction::Enhance);
    assert_eq!(
        request.operation_id.as_deref(),
        Some(format!("enhance-{OP}").as_str())
    );
    let prepared =
        prepare_user_revision(&request, &KEY, 1_800_000_100_000, &mut Nonces(0)).expect("prepare");
    let body = prepared.body();
    assert_eq!(prepared.version(), 3);
    assert_eq!(body["action"], "enhance");
    assert_eq!(
        body["files"],
        json!({"new_files": [{"kind": "enhance", "operation_id": OP}]})
    );
    assert_eq!(body["media_index"]["vault_wrapped_aes_key"], "vault:v1:new");
    assert_eq!(body["media_index"]["content_type"], "image/png");
    assert_eq!(
        body["media_index"]["files"]["full"]["s3_key"],
        "u/enh_full.webp"
    );
    let sealed = body["head"]["encrypted_content"].as_str().expect("head");
    let opened = decrypt_text(sealed, &KEY, None).expect("open");
    assert_eq!(
        decode_object(&opened).expect("content")["aes_key"],
        "B".repeat(44)
    );
    // A second save attempt names the same commit (idempotent on the server).
    let again = enhance_revision_request(head(), &head_content(true), chat(), &job).expect("again");
    assert_eq!(again.operation_id, request.operation_id);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[test]
fn a_moved_head_or_an_unready_job_is_not_committed() {
    let job = ready_job();
    let mut moved = head();
    moved.version = 3;
    assert!(matches!(
        enhance_revision_request(moved, &head_content(true), chat(), &job),
        Err(ImageEnhanceError::VersionConflict {
            current_version: Some(3)
        })
    ));
    let pending = parse_job(&job_value("pending", false), OP, None).expect("pending");
    assert!(matches!(
        enhance_revision_request(head(), &head_content(true), chat(), &pending),
        Err(ImageEnhanceError::NotReady { .. })
    ));
    let mismatch = UserRevisionError::Refused {
        code: "operation_payload_mismatch",
    };
    assert!(may_be_already_saved(&mismatch, &job));
    let other = UserRevisionError::VersionConflict {
        current_revision: Some(4),
        current_content_hash: None,
    };
    assert!(!may_be_already_saved(&other, &job));
    assert_eq!(
        ImageEnhanceError::from(UserRevisionError::Refused {
            code: "enhance_scope_mismatch"
        }),
        ImageEnhanceError::ScopeMismatch
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
#[test]
fn classifies_enhance_route_refusals_into_typed_errors() {
    let refuse = |path: &str, status: u16, body: Value| {
        classify(path, status, body.to_string().as_bytes()).map(|r| r.into_error())
    };
    let start = "/v1/images/enhance";
    assert_eq!(
        refuse(start, 402, json!({"detail": "insufficient_credits"})),
        Some(ImageEnhanceError::InsufficientCredits)
    );
    assert_eq!(
        refuse(start, 403, json!({"detail": "team_enhance_unavailable"})),
        Some(ImageEnhanceError::TeamUnavailable)
    );
    assert_eq!(
        refuse(start, 403, json!({"detail": "project_context_required"})),
        Some(ImageEnhanceError::ProjectContextRequired)
    );
    assert_eq!(
        refuse(
            start,
            409,
            json!({"detail": {"code": "embed_version_conflict", "current_version": 4}})
        ),
        Some(ImageEnhanceError::VersionConflict {
            current_version: Some(4)
        })
    );
    assert_eq!(
        refuse(start, 429, json!({"error": "Rate limit exceeded"})),
        Some(ImageEnhanceError::RateLimited)
    );
    assert_eq!(
        refuse(
            &format!("{start}/{OP}"),
            404,
            json!({"detail": "enhance_not_found"})
        ),
        Some(ImageEnhanceError::NotFound {
            code: "enhance_not_found"
        })
    );
    assert_eq!(
        refuse(start, 422, json!({"detail": "source_not_owned"})),
        Some(ImageEnhanceError::InvalidSource {
            code: "source_not_owned"
        })
    );
    assert_eq!(refuse(start, 400, json!({"detail": "something raw"})), None);
    assert_eq!(refuse(start, 202, json!({})), None);
    assert_eq!(
        refuse(
            &format!("/v1/embeds/{EMBED}/user-revisions"),
            402,
            json!({})
        ),
        None
    );
}

#[test]
fn a_job_serializes_its_fields_but_never_the_result_key() {
    let job = ready_job();
    assert!(job.result().is_some());
    let value = serde_json::to_value(&job).expect("json");
    assert_eq!(
        value,
        json!({"operation_id": OP, "embed_id": EMBED, "state": "ready", "base_version": 2,
            "target_version": 3, "credits": 63, "charged": true, "created_at": 1_800_000_000,
            "expires_at": 1_800_086_400, "error_code": null})
    );
    assert!(!value.to_string().contains(&"B".repeat(44)));
}
