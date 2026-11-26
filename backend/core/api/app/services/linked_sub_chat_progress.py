"""Project content-free progress from a live personal parent sub-chat batch."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# Bounds mirror the existing closed progress reply (three-digit counts) and
# avoid decoding unbounded pending context on the Redis command thread.
MAX_REPORTED_CHILDREN = 999
MAX_PENDING_CONTEXT_BYTES = 8 * 1024 * 1024

_READ_LINKED_PROGRESS = """
local raw = redis.call('GET', KEYS[1])
if not raw or #raw > tonumber(ARGV[4]) then return nil end
local ok, pending = pcall(cjson.decode, raw)
if not ok or type(pending) ~= 'table' or pending.continuation_dispatched == true then return nil end
local function attached(value) return value ~= nil and value ~= cjson.null end
local parent = pending.parent_request_data
if type(parent) ~= 'table'
    or parent.user_id ~= ARGV[1] or parent.user_id_hash ~= ARGV[2] or parent.chat_id ~= ARGV[3]
    or parent.is_incognito == true or parent.is_external == true or parent.is_anonymous == true
    or parent.is_sub_chat == true
    or attached(parent.team_id) or attached(parent.team_id_hash)
    or attached(parent.team_workspace_type) or attached(parent.team_object_id_hash)
    or attached(parent.parent_id) then return nil end
local task_id, turn_id = pending.parent_task_id, parent.message_id
if type(task_id) ~= 'string' or #task_id == 0 or #task_id > 255
    or type(turn_id) ~= 'string' or #turn_id == 0 or #turn_id > 255 then return nil end
local children, completed = pending.expected_sub_chat_ids, pending.completed
if type(children) ~= 'table' or #children == 0 or #children > tonumber(ARGV[5])
    or type(completed) ~= 'table' then return nil end
local root_chat = type(parent.root_chat_id) == 'string' and parent.root_chat_id or parent.chat_id
local root_turn = type(parent.root_turn_id) == 'string' and parent.root_turn_id or turn_id
if root_chat ~= parent.chat_id or root_turn ~= turn_id then return nil end
local seen, count = {}, 0
for _, child in ipairs(children) do
    if type(child) ~= 'string' or #child == 0 or child == parent.chat_id or seen[child] then return nil end
    seen[child] = true
    local result = completed[child]
    if result ~= nil then
        if type(result) ~= 'table'
            or result.chat_id ~= child or result.parent_id ~= parent.chat_id
            or result.owner_hash ~= parent.user_id_hash
            or result.root_chat_id ~= root_chat or result.root_turn_id ~= root_turn
            or result.orchestration_id ~= parent.orchestration_id
            or type(result.completed_at) ~= 'number' or result.completed_at <= 0 then return nil end
        count = count + 1
    end
end
return {task_id, turn_id, count, #children}
"""


class LinkedProgress(NamedTuple):
    task_id: str
    turn_id: str
    completed_count: int
    task_count: int


async def read_linked_sub_chat_progress(
    cache: Any, *, user_id: str, user_hash: str, chat_id: str,
) -> LinkedProgress | None:
    """Read only scoped counts and the parent identity, with no child or history reads."""
    try:
        client = await cache.client
        if client is None:
            return None
        result = await client.eval(
            _READ_LINKED_PROGRESS, 1, f"sub_chat_pending:{chat_id}",
            user_id, user_hash, chat_id, MAX_PENDING_CONTEXT_BYTES, MAX_REPORTED_CHILDREN,
        )
    except Exception as exc:
        # Independent messages still use normal admission during cache failures.
        logger.info("Linked sub-chat progress unavailable (%s)", type(exc).__name__)
        return None
    if not result:
        return None
    task_id, turn_id, completed, total = result
    if isinstance(task_id, bytes):
        task_id = task_id.decode()
    if isinstance(turn_id, bytes):
        turn_id = turn_id.decode()
    return LinkedProgress(task_id, turn_id, completed, total)
