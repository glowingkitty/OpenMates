# Plan create request (openmates.plan_create_request v1)

Plans are client-encrypted, so after `plans:create` the server asks a first-party client to create the rows.

## Request
`plans:create` returns `pending_client_action` and, for assistant turns, the server publishes it as WebSocket event `plan_create_requested` to the owner's foreground connections that advertise capability `plan_create_requests`:

```
{"type":"plan_create_requested","payload":{"chat_id","request_id","pending_client_action":{
  "contract":"openmates.plan_create_request","version":1,"request_id":"plan-create-request-<uuid>",
  "action":"create","plan_id","title","summary","goal","specification_ref",
  "assumptions":[{"assumption_id","text","required_before"}],
  "chat_id","message_id","expires_at":<unix seconds>,"notification_queued":true}}}
```

`notification_queued` is true only when the event was published. The request lives 10 minutes.

## Result
The client answers with WebSocket message `plan_create_result`:
`{request_id, status: "created"|"failed", plan_id, error_code?}` (`error_code` is a stable code, never content).
The server accepts it only from the same owner, for the same `plan_id`, before `expires_at`; anything else is ignored with a warning. Accepting clears the request record; no durable write.

## Idempotency
The client creates the Plan with the given `plan_id` and each assumption with its `assumption_id`. A repeated create is harmless. REST returns 409 `PLAN_ID_CONFLICT` when the id belongs to another owner.
