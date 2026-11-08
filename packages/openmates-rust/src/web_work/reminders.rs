//! Saved-item reminder schedule (shared Rust core `work` op, saved-embed reminder slice).
//!
//! spec: specifications/features/notifications (saved item reminders, reminder email context)
//!
//! Mirrors the pure part of the web `savedEmbedReminders.ts` reached from the
//! async `scheduleSavedEmbedReminders`: `buildSavedReminderPlan` (title, start
//! and prompt per kind, event venue), the offsets table and
//! `getReminderTriggerDateTimes`, and the ordered `set-reminder` body. The page
//! keeps fetch, the thumbnail capture, the response handling, the user's time
//! zone (a body slot read at send time like the TS), the locale slot label and
//! every `Date` parse (the `dates` table). No credential or key crosses.
//! Parity: `reminders_ts_vectors.json` (`workReminderVectors.test.ts`).

use serde_json::{Map, Value, json};

use super::reminder_context::{PageFacts, context_entries, date_ms};
use super::{Body, Decision, member, object, refusal, truthy};
use crate::account::imports_parse::iso_from_ms;

const DAY: f64 = 24.0 * 60.0;
const SET_REMINDER: &str = "/v1/apps/reminder/skills/set-reminder";

/// Runs one `reminder*` op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS throws come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "reminderSavedSchedule" => schedule(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// `SAVED_ITEM_REMINDER_OFFSETS_MINUTES`: minutes before the start, in TS order.
fn offsets(kind: &str) -> &'static [f64] {
    const EVENT: [f64; 3] = [7.0 * DAY, 12.0 * 60.0, 60.0];
    const CONNECTION: [f64; 4] = [30.0 * DAY, 7.0 * DAY, DAY, 3.0 * 60.0];
    const STAY: [f64; 2] = [DAY, 7.0 * DAY];
    const LISTING: [f64; 2] = [DAY, 3.0 * DAY];
    const HEALTH: [f64; 3] = [7.0 * DAY, DAY, 3.0 * 60.0];
    match kind {
        "event" => &EVENT,
        "travel_connection" => &CONNECTION,
        "travel_stay" => &STAY,
        "home_listing" => &LISTING,
        _ => &HEALTH,
    }
}

/// The TS `str(value)`: a non-empty string.
fn text(value: Option<&Value>) -> Option<&str> {
    value.and_then(Value::as_str).filter(|s| !s.is_empty())
}

/// `eventVenue(content)`: the venue object's parts (or the flat `venue_*`
/// members), non-blank strings joined by newlines.
fn event_venue(content: &Map<String, Value>) -> String {
    let flat = ["venue_name", "venue_address", "venue_city", "venue_state", "venue_country"];
    let nested = ["name", "address", "city", "state", "country"];
    // `venue && typeof venue === 'object'`: arrays count as objects but carry no named parts.
    let parts: Vec<Option<&Value>> = match content.get("venue") {
        Some(Value::Object(venue)) => nested.iter().map(|k| venue.get(*k)).collect(),
        Some(Value::Array(_)) => vec![None],
        _ => flat.iter().map(|k| content.get(*k)).collect(),
    };
    parts
        .into_iter()
        .filter_map(|p| p.and_then(Value::as_str))
        .filter(|p| !super::teams::js_trim(p).is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

/// Title, start string and prompt title of one saved item, or `None` for a
/// kind outside the TS union (its `switch` assigns no start).
fn pick<'a>(
    kind: &str,
    content: &'a Map<String, Value>,
    slot_label: Option<&str>,
) -> Result<Option<(String, Option<&'a str>, Option<String>)>, String> {
    let get = |key: &str| text(content.get(key));
    Ok(Some(match kind {
        "event" => (get("title").unwrap_or("Event").to_owned(), get("date_start"), None),
        "home_listing" => (get("title").unwrap_or("Listing").to_owned(), get("available_from"), None),
        "travel_stay" => (get("name").unwrap_or("Stay").to_owned(), get("check_in").or_else(|| get("check_in_date")), None),
        "travel_connection" => {
            let leg = content.get("legs").and_then(Value::as_array).and_then(|legs| legs.first());
            let leg_departure = leg.and_then(Value::as_object).and_then(|leg| text(leg.get("departure")));
            let title = get("route_display").or_else(|| get("title")).unwrap_or("Travel connection");
            (title.to_owned(), get("departure").or(leg_departure), None)
        }
        "health_appointment" => {
            let title = get("name").or_else(|| get("speciality")).unwrap_or("Appointment").to_owned();
            let when = get("slot_datetime");
            // The page formats the slot with the browser locale (`formatAppointmentSlot`).
            let prompt = match when {
                None => None,
                Some(_) => Some(format!("{title} at {}", slot_label.ok_or("missing_field:slotLabel")?)),
            };
            (title, when, prompt)
        }
        _ => return Ok(None),
    }))
}

/// `scheduleSavedEmbedReminders` up to its first await: `{schedule: null}`
/// wherever the TS returns 0 early (no kind, no parseable start, no embed id,
/// no future trigger), else the plan, the trigger instants and the body steps
/// (`trigger_datetime`, `timezone` and `notification_context` are page slots).
fn schedule(input: &Value) -> Decision {
    let none = Ok(json!({ "schedule": null }));
    let Some(kind) = input.get("kind").and_then(Value::as_str).filter(|k| !k.is_empty()) else { return none };
    let content = object(input, "content")?;
    let dates = object(input, "dates")?;
    let slot_label = input.get("slotLabel").and_then(Value::as_str);
    let Some((title, when, prompt)) = pick(kind, content, slot_label)? else { return none };
    let Some(when) = when else { return none };
    let Some(target) = date_ms(dates, when)? else { return none };
    let mut fields = content.clone();
    if kind == "event" {
        let venue = event_venue(content);
        let online = content.get("event_type").and_then(Value::as_str) == Some("ONLINE");
        let location = if !venue.is_empty() { venue } else if online { "Online event".into() } else { String::new() };
        fields.insert("location".into(), json!(location));
    }
    let timezone = match input.get("timezone") {
        None | Some(Value::Null) => None,
        Some(zone) => Some(zone.as_str().ok_or("bad_field:timezone")?),
    };
    let app_id = input.get("appId");
    let context = context_entries(kind, &title, &fields, app_id, &PageFacts { dates, timezone })?;
    if !truthy(input.get("embedId")) {
        return none;
    }
    let now = member(input, "nowMs")?.as_f64().ok_or("bad_field:nowMs")?;
    let mut triggers = Vec::new();
    for offset in offsets(kind) {
        let trigger = target - offset * 60.0 * 1000.0;
        if trigger > now + 60.0 * 1000.0 {
            match iso_from_ms(trigger) {
                Ok(iso) => triggers.push(json!(iso)),
                Err(message) => return Ok(refusal(&message)),
            }
        }
    }
    if triggers.is_empty() {
        return none;
    }
    let source_chat = text(input.get("chatId")).or_else(|| text(content.get("chat_id")));
    let prompt_title = prompt.unwrap_or_else(|| title.clone());
    let mut body = Body::default();
    body.value("prompt", json!(format!("Reminder: {prompt_title}")));
    body.value("trigger_type", json!("specific"));
    body.slot("trigger_datetime");
    body.slot("timezone");
    body.value("target_type", json!("embed"));
    body.value("target_embed_id", member(input, "embedId")?.clone());
    if let Some(app) = app_id {
        body.value("target_embed_app_id", app.clone());
    }
    body.value("target_embed_title", json!(title));
    body.slot("notification_context");
    if let Some(chat) = source_chat {
        body.value("chat_id", json!(chat));
    }
    body.value("response_type", json!("simple"));
    let mut plan = Map::new();
    plan.insert("title".into(), json!(title));
    plan.insert("promptTitle".into(), json!(prompt_title));
    if let Some(chat) = source_chat {
        plan.insert("sourceChatId".into(), json!(chat));
    }
    let thumbnail = text(content.get("image_url"))
        .or_else(|| text(content.get("cover_url")))
        .or_else(|| text(content.get("thumbnail_url")));
    if let Some(url) = thumbnail {
        plan.insert("thumbnailUrl".into(), json!(url));
    }
    plan.insert("context".into(), Value::Array(context.into_iter().map(|(k, v)| json!([k, v])).collect()));
    plan.insert("triggers".into(), Value::Array(triggers));
    plan.insert("request".into(), body.request(SET_REMINDER.into(), "POST", Map::new()));
    Ok(json!({ "schedule": plan }))
}
