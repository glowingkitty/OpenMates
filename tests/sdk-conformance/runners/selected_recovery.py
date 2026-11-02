"""Authored actual Python facade calls; execution belongs to isolated CI."""

import asyncio
import os
import stat


async def selected_recovery(
    first,
    suite,
    vector,
    endpoint,
    directory,
    *,
    request,
    wait,
    refused,
    durable,
    digest,
):
    owned = []
    try:
        recovery = first.completion_recovery
        chat = vector["chat_id"]
        await refused(recovery.jobs_for_chat(chat), {"unavailable"})
        await recovery.enable(True)
        preserved = b"synthetic opaque encrypted unrelated checkpoint\n"
        journal_file = write_selected(directory, "unrelated-journal", preserved)
        owned.append(journal_file)
        mode = vector["mode"]
        if mode == "selected_partial_failure":
            await refused(recovery.jobs_for_chat(chat), {"protocol"})
        elif mode == "selected_cancel":
            pending = asyncio.create_task(recovery.jobs_for_chat(chat))
            await wait(
                endpoint,
                lambda status: status.get("selected_discovery_waiting", 0) >= 1,
            )
            first.cancel()
            await refused(pending, {"cancelled"})
        else:
            jobs = await recovery.jobs_for_chat(chat)
            assert all(
                set(entry) == {"id", "job"} and entry["job"]["chat_id"] == chat
                for entry in jobs
            )
            if mode in {"selected_empty", "selected_pending"}:
                assert not jobs
            else:
                assert len(jobs) == 1
                other = await recovery.jobs_for_chat(vector["unrelated_chat_id"])
                assert (
                    len(other) == 1
                    and other[0]["job"]["chat_id"] == vector["unrelated_chat_id"]
                )
                stage = await recovery.stage(jobs[0]["id"])
                assert stage["kind"] == "ready"
                checkpoint_bytes = stage["checkpoint_json"].encode("utf8")
                checkpoint_file = write_selected(
                    directory, "checkpoint", checkpoint_bytes
                )
                owned.append(checkpoint_file)
                assert (await request(endpoint, "/__test/status"))["persists"] == 0
                receipt = await recovery.commit(
                    stage["id"],
                    {
                        "checkpoint_sha256": digest(
                            read_selected(
                                directory,
                                "checkpoint",
                                checkpoint_bytes,
                                checkpoint_file,
                            )
                        )
                    },
                )
                assert (
                    receipt["state"] == "TERMINAL"
                    and receipt["assistant_message_id"]
                    == suite["protocol"]["assistant_id"]
                )
        assert (
            read_selected(directory, "unrelated-journal", preserved, journal_file)
            == preserved
        )
        if mode != "selected_main":
            assert not (directory / "checkpoint").exists()
        status = await request(endpoint, "/__test/status")
        assert status["failure"] is None and status["admissions"] == 0
        assert status["claims"] == (1 if mode == "selected_main" else 0)
        assert "selected-startup-without-phased-sync" in status["checks"]
    finally:
        close_error = None
        for lease in reversed(owned):
            try:
                close_selected(lease)
            except BaseException as error:
                if close_error is None:
                    close_error = error
        if close_error is not None:
            raise close_error


def _parent(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _current_parent(directory, info)
        assert info.st_uid == os.geteuid()
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _current_parent(directory, owned):
    named = os.lstat(directory)
    assert stat.S_ISDIR(named.st_mode) and not stat.S_ISLNK(named.st_mode)
    assert (named.st_dev, named.st_ino, named.st_uid) == (
        owned.st_dev,
        owned.st_ino,
        owned.st_uid,
    )
    assert stat.S_IMODE(named.st_mode) == 0o700


def _file(directory, name, fd, owned, size, parent):
    assert name in {"checkpoint", "unrelated-journal"}
    info = os.fstat(fd)
    named = os.stat(name, dir_fd=parent, follow_symlinks=False)
    assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(named.st_mode)
    assert (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
    ) == (
        named.st_dev,
        named.st_ino,
        named.st_uid,
        named.st_mode,
        named.st_nlink,
        named.st_size,
    )
    assert (
        info.st_uid == owned.st_uid
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )
    assert info.st_size == size
    _current_parent(directory, owned)


def read_selected(directory, name, expected, lease):
    assert (
        not lease["closed"]
        and lease["directory"] == directory
        and lease["name"] == name
    )
    fd, parent, owned = lease["fd"], lease["parent"], lease["owned"]
    _file(directory, name, fd, owned, len(expected), parent)
    current = os.fstat(fd)
    assert (current.st_dev, current.st_ino) == lease["physical"]
    # The original writer remains open across every await and final reread.
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    remaining = len(expected)
    while remaining:
        chunk = os.read(fd, remaining)
        assert chunk
        chunks.append(chunk)
        remaining -= len(chunk)
    assert os.read(fd, 1) == b""
    _file(directory, name, fd, owned, len(expected), parent)
    result = b"".join(chunks)
    assert result == expected
    return result


def close_selected(lease):
    if lease["closed"]:
        return
    lease["closed"] = True
    try:
        os.close(lease["fd"])
    finally:
        os.close(lease["parent"])


def write_selected(directory, name, raw):
    parent, owned = _parent(directory)
    fd = lease = None
    try:
        assert name in {"checkpoint", "unrelated-journal"}
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        _file(directory, name, fd, owned, 0, parent)
        position = 0
        while position < len(raw):
            written = os.write(fd, raw[position:])
            assert written > 0
            position += written
        _file(directory, name, fd, owned, len(raw), parent)
        os.fsync(fd)
        os.fsync(parent)
        _file(directory, name, fd, owned, len(raw), parent)
        current = os.fstat(fd)
        lease = {
            "directory": directory,
            "name": name,
            "fd": fd,
            "parent": parent,
            "owned": owned,
            "physical": (current.st_dev, current.st_ino),
            "closed": False,
        }
        read_selected(directory, name, raw, lease)
        return lease
    except BaseException:
        if lease is not None:
            close_selected(lease)
        else:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                os.close(parent)
        raise
