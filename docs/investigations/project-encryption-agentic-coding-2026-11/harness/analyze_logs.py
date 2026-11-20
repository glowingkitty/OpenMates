"""Correlate dev logs of Project file operations into per-op timelines.

t_dispatch: AI worker yields after dispatching op (LLM already generated the call)
t_cont:     api/worker dispatches continuation task X for op (client result settled)
t_recv:     continuation task X received by worker
t_main:     continuation X starts main processing (LLM loop)
t_next:     continuation X dispatches its next file op (if any)
"""
import json
import re
import statistics as st
import sys
from pathlib import Path

D = Path(sys.argv[1])

def rows(name):
    out = []
    for r in json.load(open(D / f"{name}.json"))["rows"]:
        m = r["message"]
        try:
            m = json.loads(m)["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        out.append((r["_timestamp"] / 1e6, r["service"], m))
    return out

disp = {}
by_task_disp = {}
for t, s, m in rows("dispatch"):
    mm = re.search(r"Celery Task ID: ([0-9a-f-]+), ChatID: ([0-9a-f-]+)\].*operation ([0-9a-f-]+) dispatched", m)
    if mm:
        task, chat, op = mm.groups()
        disp[op] = (t, task, chat)
        by_task_disp.setdefault(task, []).append((t, op))

cont = {}
for t, s, m in rows("cont"):
    mm = re.search(r"continuation task ([0-9a-f-]+) for completed task ([0-9a-f-]+)", m)
    if mm:
        cont[mm.group(2)] = (t, mm.group(1), s)

def index(name, pat):
    d = {}
    for t, s, m in rows(name):
        mm = re.search(pat, m)
        if mm:
            d.setdefault(mm.group(1), t)
    return d

recv = index("received", r"Task ID: ([0-9a-f-]+)\]")
main = index("mainstart", r"Task ID: ([0-9a-f-]+)\]")
lo = min(recv.values()) if recv else 0

client, queue, pre, llm, cycle = [], [], [], [], []
paused = 0
per_chat = {}
for op, (t_d, task, chat) in disp.items():
    if t_d < lo:
        continue
    per_chat.setdefault(chat, []).append(op)
    c = cont.get(op)
    if not c:
        paused += 1
        continue
    t_c, x, _ = c
    if t_c - t_d > 1200:
        paused += 1
        continue
    client.append(t_c - t_d)
    if x in recv:
        queue.append(recv[x] - t_c)
        if x in main:
            pre.append(main[x] - recv[x])
    nxt = sorted(by_task_disp.get(x, []))
    if nxt and x in main:
        llm.append(nxt[0][0] - main[x])
        cycle.append(nxt[0][0] - t_d)

def summ(name, xs):
    if not xs:
        return f"{name}: n=0"
    xs = sorted(xs)

    def p(q):
        return xs[min(len(xs) - 1, int(q * len(xs)))]

    return (f"{name}: n={len(xs)} median={st.median(xs):.2f}s p25={p(.25):.2f} p75={p(.75):.2f} "
            f"p90={p(.9):.2f} mean={st.mean(xs):.2f}")

print("window start", lo, "ops in window", sum(len(v) for v in per_chat.values()), "chats", len(per_chat))
print("never settled within 20 min (paused/abandoned):", paused)
print(summ("A client round trip (dispatch -> result settled -> continuation dispatched)", client))
print(summ("B celery queue pickup of continuation", queue))
print(summ("C continuation setup before main loop (preprocessing resume etc.)", pre))
print(summ("D main loop start -> next file op dispatched (LLM generation + tool parse)", llm))
print(summ("E full cycle op_n dispatch -> op_n+1 dispatch", cycle))
json.dump({"client": client, "queue": queue, "pre": pre, "llm": llm, "cycle": cycle, "paused": paused},
          open(D / "timeline_stats.json", "w"))
