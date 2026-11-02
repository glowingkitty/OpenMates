"""Genuine PyO3 saved-stream lifecycle; no native/facade doubles or test hooks."""

from __future__ import annotations
import asyncio
import json
from session_saved_stream_peer import SavedStreamPeer
from openmates import SessionClient, SessionClientError


async def saved_stream_vector(suite, vector):
    peer = SavedStreamPeer(suite, vector, "pip").start()
    spec = suite["saved_stream"]
    account, protocol = spec["account"], spec["protocol"]
    client = SessionClient(
        api_url=peer.endpoint,
        app_url=protocol["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=True,
    )

    async def wait(predicate):
        for _ in range(500):
            report = peer.status()
            assert report["failure"] is None
            if predicate(report):
                return report
            await asyncio.sleep(0.01)
        raise AssertionError("saved protocol barrier")

    async def refused(operation):
        try:
            await operation()
        except SessionClientError as error:
            assert error.code in {"cancelled", "expired", "authentication", "forbidden"}
            assert "synthetic-private" not in str(error)
        else:
            raise AssertionError("saved operation unexpectedly accepted")

    def assert_b(chat_result):
        report = peer.status()
        expected = report["admitted_messages"][-1]
        assert chat_result["id"] == report["admitted_chats"][-1]
        assert any(
            message["id"] == expected
            and message["role"] == "user"
            and message["content"] == protocol["input"]
            for message in chat_result["messages"]
        )

    try:
        session = {
            "api_url": peer.endpoint,
            "session_id": account["session_id"],
            "cookies": {"auth_refresh_token": account["cookie"]},
            "ws_token": None,
            "master_key": account["master_key"],
            "hashed_email": "synthetic-email-hash",
            "user_email_salt": "synthetic-salt",
            "email_encryption_key": None,
            "created_at": 1,
            "paired_session_expires_at": None,
            "active_team_id": None,
        }
        await client.import_session(session)
        chat = None if vector["chat_selector"] == "new" else protocol["initial_chat_id"]
        native = client._native

        async def native_event(identity):
            output = await native.next_event_prepare(identity)
            try:
                raw = output.release_json()
                try:
                    output.release_json()
                except Exception as error:
                    assert json.loads(str(error))["code"] == "cancelled"
                else:
                    raise AssertionError("opaque native output released twice")
                return json.loads(raw)
            finally:
                output.discard()

        async def drain_native(identity):
            try:
                while True:
                    output = await native.next_event_prepare(identity)
                    try:
                        terminal = output.is_terminal()
                    finally:
                        output.discard()
                    if terminal:
                        return
            except Exception as error:
                assert json.loads(str(error))["code"] == "cancelled"

        if vector["mode"].startswith("saved_owned_apps_"):
            a = client.stream(protocol["input"], chat_id=chat)
            while True:
                admitted = await anext(a)
                assert admitted["type"] == "update"
                if "Admitted" in admitted["update"]:
                    break
            await wait(lambda report: report["admissions"] == 1)
            assert peer.status()["closed_sockets"] == 0

            def inventory(rows):
                assert len(rows) == 1
                assert rows[0]["id"] == rows[0]["fields"]["id"] == "fixture-app"
                assert (
                    rows[0]["title"] == "Fixture inventory"
                    and rows[0]["category"] == "Apps"
                )

            if vector["mode"] == "saved_owned_apps_pre_cancel":
                # Cancel before this coroutine's first native dispatch.
                b = asyncio.create_task(client.list("apps"))
                b.cancel()
                try:
                    await b
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("prestarted B did not cancel")
                assert peer.status()["inventory_requests"] == 0
            elif vector["mode"] == "saved_owned_apps_success":
                inventory(await asyncio.wait_for(client.list("apps"), 10))
                assert peer.status()["inventory_requests"] == 1
            elif vector["mode"] == "saved_owned_apps_cancel_headers":
                peer.hold_next_inventory = True
                peer.release_inventory_body.clear()
                b = asyncio.create_task(client.list("apps"))
                await wait(lambda report: report["inventory_headers"] == 1)
                # This real request is accepted only with the first B's newly
                # rotated cookie. A status counter alone is not that proof.
                inventory(await asyncio.wait_for(client.list("apps"), 10))
                b.cancel()
                try:
                    await b
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("own B did not cancel")
                peer.release_inventory_body.set()
                assert peer.status()["inventory_requests"] == 2
            else:
                raise AssertionError("unknown saved owned Apps mode")
            assert peer.status()["closed_sockets"] == 0
            assert peer.release_owned_a is not None
            peer.release_owned_a()
            while True:
                completed = await asyncio.wait_for(anext(a), 10)
                assert completed["type"] != "error"
                if completed["type"] == "completed":
                    assert_b(completed["chat"])
                    break
            await a.aclose()
            after = await client.export_session(include_secrets=True)
            if vector["mode"] != "saved_owned_apps_pre_cancel":
                expected = (
                    "synthetic-inventory-rotation-1"
                    if vector["mode"] == "saved_owned_apps_success"
                    else "synthetic-inventory-rotation-2"
                )
                assert after["session"]["cookies"]["auth_refresh_token"] == expected
        elif vector["mode"] == "saved_auth_denial":
            await refused(lambda: client.send(protocol["input"], chat_id=chat))
            await refused(lambda: client.send(protocol["input"], chat_id=chat))
        elif vector["mode"] in {
            "saved_queued_import_revoke",
            "saved_queued_close_revoke",
            "saved_queued_malformed_revoke",
        }:
            a = await native.start_send(protocol["input"], chat)
            held = await native.next_event_prepare(a)
            assert not held.is_terminal()
            await wait(lambda report: report["admissions"] == 1)
            if vector["mode"] == "saved_queued_import_revoke":
                await client.import_session(session)
            elif vector["mode"] == "saved_queued_close_revoke":
                await client.close()
            else:
                try:
                    await client.import_session({})
                except SessionClientError as error:
                    assert error.code == "invalid_argument"
                else:
                    raise AssertionError("malformed import accepted")
            try:
                held.release_json()
            except Exception as error:
                assert json.loads(str(error))["code"] == "cancelled"
            else:
                raise AssertionError("retired queued private output released")
            held.discard()
            await drain_native(a)
            if vector["mode"] == "saved_queued_import_revoke":
                b = await client.send(protocol["input"])
                assert_b(b)
            if vector["mode"] == "saved_queued_malformed_revoke":
                unchanged = await client.export_session(include_secrets=True)
                assert unchanged["session"]["session_id"] == session["session_id"]
                assert unchanged["session"]["master_key"] == session["master_key"]
        elif vector["mode"] == "saved_queued_successor_terminal":
            a = await native.start_send(protocol["input"], chat)
            while True:
                held = await native.next_event_prepare(a)
                if held.is_terminal():
                    break
                held.release_json()
                held.discard()
            await wait(lambda report: report["closed_sockets"] == 1)
            b = await native.start_send(protocol["input"], chat)
            while True:
                event = await native_event(b)
                assert event["type"] == "update"
                if "Admitted" in event["update"]:
                    break
            await wait(lambda report: report["admissions"] == 2)
            try:
                held.release_json()
            except Exception as error:
                assert json.loads(str(error))["code"] == "cancelled"
            else:
                raise AssertionError("stale terminal A released under B")
            held.discard()
            assert peer.status()["closed_sockets"] == 1
            peer.release_b.set()
            while True:
                event = await native_event(b)
                assert event["type"] != "error"
                if event["type"] == "completed":
                    assert_b(event["chat"])
                    break
        elif vector["mode"] == "saved_pre_effect_abort":
            a = await native.start_send(protocol["input"], chat)
            await wait(lambda report: report["snapshot_waiting"])
            native.cancel_stream(a)
            await drain_native(a)
            await wait(lambda report: report["closed_sockets"] == 1)
            b = await client.send(protocol["input"], chat_id=chat)
            assert_b(b)
        elif vector["mode"] == "saved_stale_terminal":
            # Real public native ID API proves stale-ID conflict independently
            # of the ergonomic facade lifecycle exercised by the other modes.
            a = await native.start_send(protocol["input"], chat)
            while (await native_event(a))["type"] != "completed":
                pass
            await wait(lambda report: report["closed_sockets"] == 1)
            b = await native.start_send(protocol["input"], chat)
            await wait(lambda report: report["admissions"] == 2)
            try:
                native.cancel_stream(a)
            except Exception as error:
                assert json.loads(str(error))["code"] == "conflict"
            else:
                raise AssertionError("stale A accepted")
            assert peer.status()["closed_sockets"] == 1
            peer.release_b.set()
            while True:
                event = await native_event(b)
                assert event["type"] != "error"
                if event["type"] == "completed":
                    assert_b(event["chat"])
                    break
        else:
            a = client.stream(protocol["input"], chat_id=chat)
            while True:
                admitted = await anext(a)
                assert admitted["type"] == "update"
                if "Admitted" in admitted["update"]:
                    break
            await wait(lambda report: report["admissions"] == 1)
            if vector["mode"] == "saved_active_task_cancel":
                while True:
                    content = await anext(a)
                    assert content["type"] == "update"
                    if "Content" in content["update"]:
                        assert (
                            content["update"]["Content"]["content"]
                            == "Synthetic live fragment"
                        )
                        break
            mode = vector["mode"]
            if mode in {
                "saved_consumer_close",
                "saved_same_chat_after_uncertain",
                "saved_active_task_cancel",
            }:
                await a.aclose()
            elif mode == "saved_host_abort":
                pending = asyncio.create_task(anext(a))
                await asyncio.sleep(0)
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("host cancellation not observed")
                await a.aclose()
            elif mode == "saved_global_cancel":
                client.cancel()
                await refused(lambda: anext(a))
                await a.aclose()
            elif mode == "saved_close_no_rearm":
                close = asyncio.create_task(client.close())
                await asyncio.sleep(0)
                await refused(lambda: anext(a))
                await a.aclose()
                await close
                await refused(lambda: client.send(protocol["input"], chat_id=chat))
            else:
                raise AssertionError("unknown saved mode")
            await wait(lambda report: report["closed_sockets"] >= 1)
            if mode != "saved_close_no_rearm":
                # A remains quarantined/uncertain; this is an explicit new B.
                successor = (
                    chat if vector.get("successor_chat_selector") == "same" else None
                )
                b = await client.send(protocol["input"], chat_id=successor)
                assert_b(b)
        report = await wait(
            lambda report: report["admissions"] == vector["expected_admissions"]
        )
        assert (
            len(report["turns"])
            == len(report["message_ids"])
            == vector["expected_admissions"]
        )
        if vector["mode"] == "saved_active_task_cancel":
            assert report["task_cancel_requests"] == 1
        if vector["mode"] == "saved_auth_denial":
            assert report["auth_denials"] >= 1
        else:
            for check in (
                "actual-encrypted-saved-admission",
                "no-replay-of-turn-or-message-identities",
                "no-model-provider-override",
            ):
                assert check in report["checks"]
        return {"id": vector["id"], "status": "passed"}
    finally:
        await client.close()
        peer.close()
