"""Per-chat server timeline of an agentic turn from dev OpenObserve logs.

Splits wall time between the first task receipt and the final task end into:
  setup   task received -> LLM request sent (context rebuild, prompts, tools)
  llm     LLM request sent -> tool call yielded / stream finished
  dispatch tool call yielded -> op dispatched (server-side dispatch work)
  client  op dispatched -> continuation dispatched (client round trip + settle)
  queue   continuation dispatched -> next task received
  tail    after last stream finished until task completed (billing, persistence)
Usage: chat_timeline.py <out.json> <chat_id> [<chat_id> ...]
"""
import json
import re
import subprocess
import sys


def query(value, minutes=240, extra=None):
    filters = [{"field": "message", "op": "like", "value": f"%{value}%"}]
    if extra:
        filters.append({"field": "message", "op": "like", "value": f"%{extra}%"})
    body = {"stream": "default", "since_minutes": minutes, "limit": 1000, "filters": filters}
    raw = subprocess.run(["docker", "exec", "api", "python", "/app/backend/scripts/debug.py", "logs", "--o2", "--json",
                          "--query-json", json.dumps(body)], capture_output=True, text=True, check=True).stdout
    out = []
    for r in json.loads(raw)["rows"]:
        m = r["message"]
        try:
            m = json.loads(m)["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        out.append((r["_timestamp"] / 1e6, r.get("service", ""), m))
    return sorted(out)


def chat_events(chat_id):
    rows = query(chat_id, extra="Received apps.ai.tasks.skill_ask")
    tasks = []
    for t, s, m in rows:
        mm = re.search(r"Received apps\.ai\.tasks\.skill_ask task", m)
        tid = re.search(r"\[(?:Celery )?Task ID: ([0-9a-f-]+)", m)
        if mm and tid:
            tasks.append(tid.group(1))
    tasks = list(dict.fromkeys(tasks))
    events = []
    ops = []
    for task in tasks:
        for t, s, m in query(task):
            kind = None
            if "Received apps.ai.tasks.skill_ask task" in m:
                kind = "received"
            elif "http_request_headers_sent" in m and "Main Stream" not in m:
                kind = "llm_sent"
            elif "first_provider_chunk" in m:
                kind = "llm_first"
            elif "Yielding a tool call from stream" in m:
                kind = "tool:" + m.split("Yielding a tool call from stream: ")[-1].split(" ")[0]
            elif "Stream finished." in m:
                kind = "llm_done"
            elif "dispatched; yielding to client completion" in m:
                kind = "op_dispatched"
                ops.append(re.search(r"operation ([0-9a-f-]+)", m).group(1))
            elif "TASK_COMPLETED" in m and "skill_ask" in m:
                kind = "task_done"
            elif "Billing HTTP completed" in m:
                kind = "billing_done"
            if kind:
                events.append((t, task, kind))
    for op in ops:
        for t, s, m in query(op):
            if "Dispatched async skill continuation task" in m:
                events.append((t, op, "cont_dispatched"))
    return sorted(events), tasks


def breakdown(events):
    buckets = {"setup": 0.0, "llm": 0.0, "dispatch": 0.0, "client": 0.0, "queue": 0.0, "other": 0.0}
    state, last = None, None
    trans = {("received", "llm_sent"): "setup", ("llm_done", "llm_sent"): "setup",
             ("llm_sent", "llm_first"): "llm", ("llm_first", "llm_done"): "llm", ("llm_sent", "llm_done"): "llm",
             ("llm_done", "op_dispatched"): "dispatch", ("op_dispatched", "cont_dispatched"): "client",
             ("cont_dispatched", "received"): "queue"}
    llm_calls, tools = 0, []
    for t, _, kind in events:
        if kind.startswith("tool:"):
            tools.append(kind[5:])
            continue
        if kind in ("billing_done", "task_done"):
            continue
        if kind == "llm_sent":
            llm_calls += 1
        if state is not None:
            buckets[trans.get((state, kind), "other")] += t - last
        state, last = kind, t
    return buckets, llm_calls, tools


def main():
    out = {}
    for chat in sys.argv[2:]:
        events, tasks = chat_events(chat)
        b, calls, tools = breakdown(events)
        first = min(t for t, _, _ in events)
        done = max(t for t, _, k in events if k in ("llm_done", "task_done"))
        last_llm = max(t for t, _, k in events if k == "llm_done")
        out[chat] = {"first_abs": first, "last_llm_done_abs": last_llm, "tasks": len(tasks), "llm_calls": calls, "tools": tools, "server_span_s": round(done - first, 2),
                     "buckets_s": {k: round(v, 2) for k, v in b.items()},
                     "events": [(round(t - first, 3), k) for t, _, k in events]}
        print(chat, json.dumps({k: v for k, v in out[chat].items() if k != "events"}))
    json.dump(out, open(sys.argv[1], "w"), indent=1)


if __name__ == "__main__":
    main()
