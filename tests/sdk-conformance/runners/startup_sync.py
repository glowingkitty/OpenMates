"""Actual direct Python startup operation against shared independent actor peer."""

import asyncio


async def startup_sync(
    first,
    second_client,
    replace_credentials,
    vector,
    endpoint,
    *,
    request,
    wait,
    refused,
):
    monitor = await first.watch_chats()
    operation = metadata = None
    try:
        if vector["mode"] == "startup_foreign_monitor":
            foreign = await second_client()
            try:
                try:
                    foreign._native.initial_sync_open(monitor._id)
                except Exception as error:
                    from openmates.session_client import _failure

                    assert _failure(error).code == "cancelled"
                else:
                    raise AssertionError("foreign Bridge accepted another monitor")
            finally:
                await foreign.close()
            status = await request(endpoint, "/__test/status")
            assert status["startup_requests"] == 0 and status["metadata_requests"] == 0
            return
        operation = monitor.begin_initial_sync()
        mode = vector["mode"]
        if mode == "startup_cancel_before":
            operation.cancel()
            await refused(operation.run(), {"cancelled"})
        elif mode == "startup_stale":
            await replace_credentials()
            await refused(operation.run(), {"cancelled"})
        else:
            pending = asyncio.create_task(operation.run())
            if mode in {"startup_cancel_inflight", "startup_foreign_context"}:
                await wait(endpoint, lambda status: status["metadata_requests"] == 1)
                if mode == "startup_foreign_context":
                    await wait(
                        endpoint,
                        lambda status: "foreign-context-offered" in status["checks"],
                    )
                    await asyncio.sleep(0.03)
                    assert not pending.done()
                operation.cancel()
                await refused(pending, {"cancelled"})
            elif mode == "startup_server_error":
                await refused(pending, {"offline"})
            else:
                metadata = await pending
                assert (
                    await metadata.received_metadata_count() == vector["expected_count"]
                )
                await refused(operation.run(), {"conflict"})
                if mode == "startup_repeat":
                    duplicate = monitor.begin_initial_sync()
                    try:
                        await refused(duplicate.run(), {"conflict", "cancelled"})
                    finally:
                        duplicate.cancel()
                else:
                    await monitor.close()
                    await refused(metadata.received_metadata_count(), {"cancelled"})
        status = await request(endpoint, "/__test/status")
        assert status["failure"] is None and status["unexpected_frames"] == 0
        assert status["startup_requests"] == (
            0 if mode in {"startup_cancel_before", "startup_stale"} else 1
        )
        assert status["metadata_requests"] == (
            1
            if vector.get("total_chat_count", 0) > 100
            and mode not in {"startup_cancel_before", "startup_stale"}
            else 0
        )
    finally:
        if metadata:
            metadata.cancel()
        if operation:
            operation.cancel()
        await monitor.close()
