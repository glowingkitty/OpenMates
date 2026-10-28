"""Guest dictation admission, ephemeral protocol and conservative spend boundaries."""

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from backend.core.api.app.routes import audio_realtime
from backend.core.api.app.services import guest_transcription_meter as guest_module
from backend.shared.providers import transcript_correction as correction
from backend.shared.providers.transcript_correction_accounting import (
    admitted_correction,
    mark_correction_dispatched,
    correction_accountant,
    settle_correction,
    CorrectionAccountingError,
)


class Cache:
    def __init__(self):
        self.rows = {}

    @property
    async def client(self):
        return self

    async def set(self, key, value, **kwargs):
        if key in self.rows:
            return False
        self.rows[key] = value
        return True

    async def eval(self, _script, _count, key, token):
        if self.rows.get(key) == token:
            del self.rows[key]


class Service:
    def __init__(self, **kwargs):
        self.events = []
        self.allowed = True
        self.rate_allowed = True
        self.reject_after = None

    def request_identity(self, anonymous_id, ip):
        return anonymous_id or hashlib.sha256(ip.encode()).hexdigest()

    async def consume_local_rate_limit(self, identity, **kwargs):
        self.events.append(("rate", identity))
        return self.rate_allowed

    async def open_request(self, **kwargs):
        self.events.append(("open", kwargs))
        return SimpleNamespace(accepted=self.allowed, reason="budget_exhausted")

    async def reserve_operation(self, **kwargs):
        self.events.append(("reserve", kwargs))
        allowed = self.allowed and (
            self.reject_after is None
            or len([e for e in self.events if e[0] == "reserve"]) <= self.reject_after
        )
        return SimpleNamespace(accepted=allowed, reason="per_identity_exhausted")

    async def finalize_charge(self, charge_id, **kwargs):
        self.events.append(("settle", charge_id, kwargs["actual_credits"]))


class Socket:
    def __init__(self):
        self.headers = {"origin": "https://app.dev.openmates.org"}
        self.cookies = {}
        self.client = SimpleNamespace(host="8.8.8.8")
        self.query_params = {
            "anonymous_id": "stable-guest",
            "chat_id": "untrusted-chat",
            "correction_context": "workflow",
        }
        self.messages = []
        self.inputs = []
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                directus_service=object(),
                cache_service=Cache(),
                allowed_origins=[self.headers["origin"]],
                config_manager=SimpleNamespace(
                    get_model_pricing=lambda *_args: {
                        "tokens": {
                            "input": {"per_credit_unit": 1000},
                            "output": {"per_credit_unit": 1000},
                        }
                    }
                ),
                secrets_manager=SimpleNamespace(get_secret=self.secret),
            )
        )

    async def secret(self, *_args):
        return "provider-secret"

    async def accept(self):
        self.messages.append({"type": "accepted"})

    async def close(self, **kwargs):
        self.messages.append({"type": "closed", **kwargs})

    async def send_json(self, message):
        self.messages.append(message)

    async def receive_text(self):
        await asyncio.sleep(0)
        if self.inputs:
            item = self.inputs.pop(0)
            if isinstance(item, BaseException):
                raise item
            return json.dumps(item)
        await asyncio.Future()


@pytest.fixture
def guest_setup(monkeypatch):
    services = []

    def factory(**kwargs):
        service = Service(**kwargs)
        services.append(service)
        return service

    monkeypatch.setattr(guest_module, "AnonymousFreeUsageService", factory)
    monkeypatch.setattr(
        "backend.core.api.app.utils.server_mode.validate_request_domain",
        lambda _ws: ("app.dev.openmates.org", False, "development"),
    )
    return services


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("supplied", ["cookie", "token", "authorization", "none"])
async def test_optional_actor_never_downgrades_supplied_invalid_credentials(
    monkeypatch, supplied
):
    socket = Socket()
    if supplied == "cookie":
        socket.cookies["auth_refresh_token"] = ""
    elif supplied == "token":
        socket.query_params["token"] = ""
    elif supplied == "authorization":
        socket.headers["authorization"] = "invalid"
    calls = []

    async def auth(_ws):
        calls.append(True)
        return None

    monkeypatch.setattr(audio_realtime, "get_current_user_ws", auth)
    result = await audio_realtime._optional_transcription_actor(socket)
    assert result == (None if supplied == "none" else {"authentication_failed": True})
    assert bool(calls) == (supplied != "none")


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_guest_admission_has_local_and_ip_rate_and_concurrency_and_one_credit_hold(
    guest_setup,
):
    socket = Socket()
    meter = guest_module.GuestTranscriptionMeter(socket)
    await meter.admit()
    assert len(socket.app.state.cache_service.rows) == 2
    assert len([e for e in meter.service.events if e[0] == "rate"]) == 2
    assert meter.service.events[-1][1]["quoted_credits"] == 1
    for invalid_seconds in [121, float("nan"), float("inf")]:
        with pytest.raises(guest_module.GuestTranscriptionDenied):
            await meter.reserve_audio(invalid_seconds)
    await meter.reserve_audio(6)
    assert len([e for e in meter.service.events if e[0] == "reserve"]) == 1
    await meter.reserve_audio(6.01)
    assert meter.service.events[-1][1]["quoted_credits"] == 1
    # Rotating the local ID retains the shared IP concurrency boundary.
    second = Socket()
    second.app.state.cache_service = socket.app.state.cache_service
    second.query_params["anonymous_id"] = "rotated-guest"
    other = guest_module.GuestTranscriptionMeter(second)
    with pytest.raises(
        guest_module.GuestTranscriptionDenied, match="free allowance"
    ) as exc:
        await other.admit()
    assert exc.value.code == "recording_active"
    await other.release_locks()
    assert len(socket.app.state.cache_service.rows) == 2
    await meter.settle_audio(0)
    assert meter.service.events[-1][-1] == 0
    await meter.release_locks()
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["origin", "self_host", "budget", "rate", "cache", "identity"]
)
async def test_denied_guest_dispatches_no_provider_work(
    monkeypatch, guest_setup, failure
):
    socket = Socket()
    if failure == "origin":
        socket.headers["origin"] = "https://third-party.example"
    elif failure == "self_host":
        monkeypatch.setattr(
            "backend.core.api.app.utils.server_mode.validate_request_domain",
            lambda _ws: ("custom.example", True, "self_hosted"),
        )
    elif failure == "identity":
        socket.query_params["anonymous_id"] = "x" * 129
    elif failure == "cache":
        socket.app.state.cache_service = SimpleNamespace(
            client=asyncio.sleep(0, result=None)
        )
    original = guest_module.GuestTranscriptionMeter.admit

    async def admit(self):
        if failure == "budget":
            self.service.allowed = False
        if failure == "rate":
            self.service.rate_allowed = False
        await original(self)

    monkeypatch.setattr(guest_module.GuestTranscriptionMeter, "admit", admit)

    def no_provider(**kwargs):
        pytest.fail("Denied admission must not create a provider connection")

    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", no_provider)
    await audio_realtime.realtime_transcription(socket, auth_data=None)
    assert (
        not socket.app.state.cache_service.rows
        if isinstance(socket.app.state.cache_service, Cache)
        else True
    )
    if failure in {"budget", "rate"}:
        error = next(m for m in socket.messages if m["type"] == "session.error")
        assert error["signup_required"] == (failure == "budget")


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "termination",
    [
        "complete",
        "cancel",
        "disconnect",
        "audio_denied",
        "ambiguous_send",
        "correction_denied",
        "idle",
        "wall",
        "missing_created",
        "missing_updated",
        "correction_unavailable",
    ],
)
# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
async def test_guest_protocol_reserves_before_forwarding_and_settles_ephemeral_work(
    monkeypatch, guest_setup, termination
):
    socket = Socket()
    samples = b"\x01\x00" * 800
    socket.inputs = [
        {"type": "input_audio.append", "audio": base64.b64encode(samples).decode()}
    ]
    if termination == "audio_denied":
        # Initial one-credit hold cannot cover this eight-second chunk.
        socket.inputs[0]["audio"] = base64.b64encode(b"\x01\x00" * 128000).decode()
    if termination == "ambiguous_send":
        # First chunk is known dispatched; a later large chunk crosses a new
        # cumulative credit boundary before its transport becomes ambiguous.
        socket.inputs.append(
            {
                "type": "input_audio.append",
                "audio": base64.b64encode(b"\x01\x00" * 128000).decode(),
            }
        )
    socket.inputs += (
        [WebSocketDisconnect()]
        if termination == "disconnect"
        else [
            {"type": "session.cancel" if termination == "cancel" else "input_audio.end"}
        ]
    )
    if termination in {"idle", "wall", "missing_created", "missing_updated"}:
        socket.inputs = []
        monkeypatch.setattr(
            audio_realtime,
            "GUEST_WALL_SECONDS" if termination == "wall" else "GUEST_IDLE_SECONDS",
            0.001,
        )
    events = []

    class Provider:
        def __init__(self):
            self.handshake = [{"type": "session.created"}, {"type": "session.updated"}]
            self.ended = asyncio.Event()
            self.sent_final = False
            self.setup_cancelled = False

        async def receive_json(self):
            if (termination == "missing_created" and len(self.handshake) == 2) or (
                termination == "missing_updated" and len(self.handshake) == 1
            ):
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.setup_cancelled = True
                    raise
            return self.handshake.pop(0)

        async def send_json(self, message):
            events.append(message["type"])
            if message["type"] == "input_audio.append":
                assert any(e[0] == "reserve" for e in guest_setup[0].events)
                if (
                    termination == "ambiguous_send"
                    and events.count("input_audio.append") == 2
                ):
                    raise ConnectionError("ambiguous network send")
            if message["type"] == "input_audio.end":
                self.ended.set()

        async def receive(self):
            await self.ended.wait()
            if self.sent_final:
                await asyncio.Future()
            self.sent_final = True
            return SimpleNamespace(
                type=audio_realtime.aiohttp.WSMsgType.TEXT,
                data=json.dumps(
                    {
                        "type": "transcription.done",
                        "text": "Keep this note. " * 80
                        if termination == "correction_denied"
                        else "Keep this note.",
                        "language": "en",
                    }
                ),
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    provider = Provider()

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def ws_connect(self, *args, **kwargs):
            return provider

    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", Session)

    async def correct(_ws, text, language, context):
        assert context is None
        assert correction_accountant.get() is not None
        if termination == "correction_unavailable":
            raise RuntimeError("recoverable provider outage")
        async with admitted_correction(
            correction.GEMINI_CORRECTION_MODEL, 9000, 2048
        ) as operation:
            await settle_correction(operation, 100, 30)
        return {"transcript": text, "title": "Note", "correction_model": "test"}

    monkeypatch.setattr(audio_realtime, "_correct_segment", correct)

    def no_account_billing(_ws):
        pytest.fail("Guest must never charge an account")

    monkeypatch.setattr(audio_realtime, "_create_billing_service", no_account_billing)
    original = guest_module.GuestTranscriptionMeter.admit

    async def admit(self):
        await original(self)
        if termination in {"audio_denied", "correction_denied"}:
            self.service.reject_after = 2 if termination == "correction_denied" else 1

    monkeypatch.setattr(guest_module.GuestTranscriptionMeter, "admit", admit)
    await asyncio.wait_for(
        audio_realtime.realtime_transcription(socket, auth_data=None), timeout=1
    )
    service = guest_setup[0]
    settled = [e for e in service.events if e[0] == "settle"]
    assert not socket.app.state.cache_service.rows
    if termination == "ambiguous_send":
        assert len(settled) == 1
        assert (
            settled[0][-1]
            == sum(
                row[1]["quoted_credits"]
                for row in service.events
                if row[0] == "reserve"
            )
            == 2
        )
    elif termination == "audio_denied":
        assert "input_audio.append" not in events
        assert settled[0][-1] == 0
    elif termination in {"idle", "wall", "missing_created", "missing_updated"}:
        assert settled[0][-1] == 0
        assert socket.messages[-1]["code"] == "recording_timeout"
        assert not socket.messages[-1]["signup_required"]
        if termination in {"missing_created", "missing_updated"}:
            assert provider.setup_cancelled
            assert not any(
                message["type"] == "session.ready" for message in socket.messages
            )
            assert "input_audio.append" not in events
    else:
        assert settled[0][1].endswith(":pcm")
        assert settled[0][-1] == 1
    if termination == "complete":
        assert len(settled) == 2
        assert socket.messages[-1]["type"] == "correction.done"
    if termination == "correction_denied":
        assert socket.messages[-1]["type"] == "session.error"
        assert socket.messages[-1]["signup_required"]
        assert not any(
            message["type"] in {"correction.done", "correction.failed"}
            for message in socket.messages
        )
        # The first batch succeeded before the later admission denial.
        assert len([row for row in settled if ":correction:" in row[1]]) == 1
    if termination == "correction_unavailable":
        assert socket.messages[-1]["type"] == "correction.failed"
        assert not any(
            message["type"] == "session.error" for message in socket.messages
        )
    assert all("untrusted-chat" not in json.dumps(e) for e in service.events)


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_guest_correction_accounts_each_fallback_and_finalizes_ambiguous_attempt(
    monkeypatch, guest_setup
):
    socket = Socket()
    meter = guest_module.GuestTranscriptionMeter(socket)
    await meter.admit()
    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(
        correction, "resolve_api_key", lambda _secrets: asyncio.sleep(0, result="key")
    )

    class Mercury:
        def __init__(self, *args, **kwargs):
            self.transport = kwargs["transport"]

        async def complete(self, request):
            assert request.max_completion_tokens == 2048
            assert len([e for e in meter.service.events if e[0] == "reserve"]) == 2
            # Simulate the injected transport crossing the network boundary.
            mark_correction_dispatched(self.transport.operation)
            await self.transport.aclose()
            raise ConnectionError("response unavailable")

    monkeypatch.setattr(correction, "InceptionClient", Mercury)

    async def gemini(text, key, language):
        async with admitted_correction(
            correction.GEMINI_CORRECTION_MODEL, 9000, 2048
        ) as op:
            await settle_correction(op, 100, 20)
        return {"title": "Note", "corrected_transcript": text}

    monkeypatch.setattr(correction, "correct_transcript_with_gemini", gemini)
    token = correction_accountant.set(meter)
    try:
        result = await correction.correct_transcript(
            "Keep this note.", socket.app.state.secrets_manager, "en"
        )
    finally:
        correction_accountant.reset(token)
        await meter.release_locks()
    assert result["model"] == correction.GEMINI_CORRECTION_MODEL
    reserves = [e for e in meter.service.events if e[0] == "reserve"]
    settles = [e for e in meter.service.events if e[0] == "settle"]
    assert len(reserves) == 3 and len(settles) == 2
    assert settles[0][1] == reserves[-2][1]["charge_id"]
    assert settles[0][-1] == reserves[-2][1]["quoted_credits"]
    assert settles[1][1] == reserves[-1][1]["charge_id"]


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_correction_admission_failure_does_not_attempt_fallback(monkeypatch):
    class Denied:
        async def reserve_correction(self, *args):
            raise guest_module.GuestTranscriptionDenied("budget_exhausted")

    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(
        correction, "resolve_api_key", lambda _secrets: asyncio.sleep(0, result="key")
    )

    async def no_fallback(*args):
        pytest.fail("Accounting denial must not dispatch a fallback")

    monkeypatch.setattr(correction, "correct_transcript_with_gemini", no_fallback)
    token = correction_accountant.set(Denied())
    try:
        with pytest.raises(CorrectionAccountingError):
            await correction.correct_transcript("A note.", object(), "en")
    finally:
        correction_accountant.reset(token)


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_guest_correction_real_catalogue_quotes_and_signed_in_output_defaults(
    monkeypatch, guest_setup
):
    from pathlib import Path
    from backend.core.api.app.utils import config_manager
    from backend.shared.providers.transcript_correction_accounting import (
        correction_output_limit,
    )

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        config_manager, "BACKEND_CONFIG_FILE", str(root / "config/backend_config.yml")
    )
    monkeypatch.setattr(config_manager, "PROVIDERS_CONFIG_DIR", str(root / "providers"))
    monkeypatch.setattr(config_manager, "PROVIDER_OVERLAY_CONFIG_DIR", None)
    config = object.__new__(config_manager.ConfigManager)
    config._load_configs()
    socket = Socket()
    socket.app.state.config_manager = config
    meter = guest_module.GuestTranscriptionMeter(socket)
    await meter.admit()
    for model in [
        correction.MERCURY_CORRECTION_MODEL,
        correction.GEMINI_CORRECTION_MODEL,
    ]:
        operation = await meter.reserve_correction(model, 12_000, 2048)
        assert operation.quote > 0
        await operation.settle(300, 100)
    assert len([e for e in meter.service.events if e[0] == "settle"]) == 2
    assert correction_output_limit(8192) == 8192
    token = correction_accountant.set(meter)
    try:
        assert correction_output_limit(8192) == 2048
    finally:
        correction_accountant.reset(token)
        await meter.release_locks()


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("usage", ["reported", "missing", "error"])
async def test_guest_gemini_real_wrapper_admits_before_http_caps_output_and_settles(
    monkeypatch, guest_setup, usage
):
    from backend.shared.providers import gemini_transcript_correction as gemini

    socket = Socket()
    meter = guest_module.GuestTranscriptionMeter(socket)
    await meter.admit()

    class Response:
        status_code = 500 if usage == "error" else 200
        text = "provider error"

        def json(self):
            return {
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 10,
                }
                if usage == "reported"
                else {},
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": gemini.GEMINI_TRANSCRIPT_TOOL_NAME,
                                        "args": {
                                            "title": "Note",
                                            "corrected_transcript": "Keep the note.",
                                        },
                                    }
                                }
                            ]
                        }
                    }
                ],
            }

    class HTTP:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert len([e for e in meter.service.events if e[0] == "reserve"]) == 2
            assert kwargs["json"]["generationConfig"]["maxOutputTokens"] == 2048
            return Response()

    monkeypatch.setattr(gemini.httpx, "AsyncClient", HTTP)
    token = correction_accountant.set(meter)
    try:
        if usage == "error":
            with pytest.raises(RuntimeError):
                await gemini.correct_transcript_with_gemini(
                    "Keep the note.", "secret", "en"
                )
        else:
            await gemini.correct_transcript_with_gemini(
                "Keep the note.", "secret", "en"
            )
    finally:
        correction_accountant.reset(token)
        await meter.release_locks()
    settled = [e for e in meter.service.events if e[0] == "settle"]
    if usage == "error":
        assert len(settled) == 1
        assert (
            settled[0][-1]
            == [e for e in meter.service.events if e[0] == "reserve"][-1][1][
                "quoted_credits"
            ]
        )
    else:
        assert len(settled) == 1
        quote = [e for e in meter.service.events if e[0] == "reserve"][-1][1][
            "quoted_credits"
        ]
        assert settled[0][-1] <= quote
        if usage == "missing":
            assert settled[0][-1] == quote


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "cancel", "before_dispatch"])
async def test_guest_ambiguous_spend_survives_normal_reservation_expiry(failure):
    from datetime import datetime, timedelta, timezone
    from backend.tests.test_anonymous_free_usage_budget import FakeDirectus
    from backend.core.api.app.services.anonymous_free_usage_service import (
        AnonymousFreeUsageService,
    )

    clock = [datetime(2026, 10, 28, 10, tzinfo=timezone.utc)]
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(
        directus_service=directus, now_provider=lambda: clock[0]
    )
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=10_000,
        daily_hard_cap_percent=10,
        weekly_cap_percent=20,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin",
    )
    meter = guest_module.GuestTranscriptionMeter(Socket())
    meter.service = service
    assert (
        await service.open_request(
            request_id=meter.request_id, anonymous_id="guest", ip_address="8.8.8.8"
        )
    ).accepted
    await meter.reserve_audio(0.05)  # known first chunk
    await meter.reserve_audio(8.05)  # admitted later transport attempt is ambiguous
    await meter.settle_ambiguous_audio()
    # Idempotent settlement cannot deduct twice.
    await meter.settle_ambiguous_audio()
    error = (
        asyncio.CancelledError("cancel during network")
        if failure == "cancel"
        else ConnectionError("no response")
    )
    token = correction_accountant.set(meter)
    try:
        with pytest.raises(type(error)) as raised:
            async with admitted_correction(
                correction.GEMINI_CORRECTION_MODEL, 9000, 2048
            ) as op:
                if failure != "before_dispatch":
                    mark_correction_dispatched(op)
                raise error
        assert raised.value is error, (
            "Accounting preserves the original provider/cancellation exception"
        )
    finally:
        correction_accountant.reset(token)
    used = directus.budget["daily_used_credits"]
    rows = list(directus.reservations.values())
    correction_row = next(row for row in rows if ":correction:" in row["request_id"])
    assert correction_row["status"] == "finalized"
    assert correction_row["finalized_credits"] == (
        0 if failure == "before_dispatch" else correction_row["reserved_credits"]
    )
    assert used == 2 + correction_row["finalized_credits"]
    clock[0] += timedelta(hours=3)
    await service._release_expired_reservations_locked()
    assert directus.budget["daily_used_credits"] == used
    assert correction_row["status"] == "finalized"
    assert all(row["status"] == "finalized" for row in rows if row.get("charge_id"))


# contract-test: supporting surface=rest_api assertions=message-input.audio.guest-admission,billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_guest_mercury_dispatch_marker_runs_at_http_transport_boundary(
    monkeypatch, guest_setup
):
    import httpx
    from backend.shared.providers import transcript_correction_accounting as accounting

    meter = guest_module.GuestTranscriptionMeter(Socket())
    await meter.admit()
    operation = await meter.reserve_correction(
        correction.MERCURY_CORRECTION_MODEL, 9000, 2048
    )

    async def network(request):
        assert operation.dispatched, (
            "Mark dispatch immediately before actual HTTP transport"
        )
        raise ConnectionError("response lost after dispatch")

    monkeypatch.setattr(
        accounting.httpx,
        "AsyncHTTPTransport",
        lambda **kwargs: httpx.MockTransport(network),
    )
    transport = accounting.correction_dispatch_transport(operation)
    assert not operation.dispatched
    with pytest.raises(ConnectionError):
        async with httpx.AsyncClient(transport=transport) as client:
            assert not operation.dispatched, (
                "Creating/entering the HTTP client is not dispatch"
            )
            await client.post("https://provider.invalid/chat/completions", json={})
    assert operation.dispatched
    await operation.finalize_unresolved()
    await operation.finalize_unresolved()
    settlements = [event for event in meter.service.events if event[0] == "settle"]
    assert len(settlements) == 1 and settlements[0][-1] == operation.quote
    await meter.release_locks()
