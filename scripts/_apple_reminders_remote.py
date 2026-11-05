#!/usr/bin/env python3
"""Fixed Apple Reminders helper executed on the Mac by `apple_remote.py reminders-op`.

Reads one bounded JSON request from stdin and runs a fixed Swift/EventKit program
through `/usr/bin/swift -`. Request values reach Swift only as one argv JSON
string, never by source interpolation. `delete` removes one reminder by id and is
irreversible, so callers use it only when the user said "delete"; otherwise finishing a
reminder means marking it completed. Writes and deletes are limited to the lists
named in ALLOWED_WRITE_LISTS. (AppleScript/JXA was too slow: one id lookup scans
every reminder and exceeds two minutes.)
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import json
import subprocess
import sys

MAX_REQUEST_BYTES = 256 * 1024
ACTIONS = {"lists", "list", "create", "complete", "set-due", "update", "move", "delete", "batch"}
ALLOWED_WRITE_LISTS = ["OpenMates", "Personal Tasks"]

SWIFT = r"""
import EventKit
import Foundation

struct OpError: Error { let code: String }
func fatal(_ code: String, _ status: Int32) -> Never {
    FileHandle.standardError.write(code.data(using: .utf8)!)
    exit(status)
}
let request = (try? JSONSerialization.jsonObject(with: CommandLine.arguments[1].data(using: .utf8)!)) as? [String: Any] ?? [:]
let writable = Set(request["_writable"] as? [String] ?? [])
let store = EKEventStore()
let gate = DispatchSemaphore(value: 0)
var granted = false
if #available(macOS 14.0, *) {
    store.requestFullAccessToReminders { ok, _ in granted = ok; gate.signal() }
} else {
    store.requestAccess(to: .reminder) { ok, _ in granted = ok; gate.signal() }
}
gate.wait()
if !granted { fatal("reminders_access_denied", 3) }

let iso = ISO8601DateFormatter()
let prefix = "x-apple-reminder://"
func calendar(named name: String) throws -> EKCalendar {
    let found = store.calendars(for: .reminder).filter { $0.title == name }
    if found.count != 1 { throw OpError(code: "list_not_found:" + name) }
    return found[0]
}
func describe(_ r: EKReminder) -> [String: Any] {
    var due: Any = NSNull()
    if let c = r.dueDateComponents {
        if c.hour == nil, let y = c.year, let m = c.month, let d = c.day {
            due = String(format: "%04d-%02d-%02d", y, m, d)  // all-day: a date, not an instant
        } else if let d = Calendar.current.date(from: c) { due = iso.string(from: d) }
    }
    var start: Any = NSNull()
    if let c = r.startDateComponents, let d = Calendar.current.date(from: c) { start = iso.string(from: d) }
    let alarms: [Any] = (r.alarms ?? []).map { a in
        if let d = a.absoluteDate { return iso.string(from: d) }
        return "relative:\(Int(a.relativeOffset))"
    }
    return ["id": prefix + r.calendarItemIdentifier, "title": r.title ?? "", "notes": r.notes ?? "",
            "list": r.calendar.title, "due": due, "due_has_time": r.dueDateComponents?.hour != nil,
            "start": start, "alarms": alarms,
            "priority": r.priority, "completed": r.isCompleted,
            "created": r.creationDate.map { iso.string(from: $0) } ?? NSNull()]
}
func dueComponents(_ value: Any?) throws -> DateComponents? {
    guard let text = value as? String, !text.isEmpty else { return nil }
    // Rule: reminders always get a time of day; a bare YYYY-MM-DD is refused.
    if text.count == 10 { throw OpError(code: "due_time_required") }
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let date = iso.date(from: text) ?? fractional.date(from: text) else { throw OpError(code: "invalid_due") }
    return Calendar.current.dateComponents([.year, .month, .day, .hour, .minute, .timeZone], from: date)
}
// Due, start and alarm move together so Reminders and Calendar show the same moment.
func applyDue(_ r: EKReminder, _ value: Any?) throws {
    let components = try dueComponents(value)
    r.dueDateComponents = components
    r.startDateComponents = components
    for alarm in r.alarms ?? [] { r.removeAlarm(alarm) }
    if let c = components, let d = Calendar.current.date(from: c) { r.addAlarm(EKAlarm(absoluteDate: d)) }
}
func requireWritable(_ cal: EKCalendar) throws {
    if !writable.contains(cal.title) { throw OpError(code: "list_not_writable:" + cal.title) }
}
func reminder(_ req: [String: Any]) throws -> EKReminder {
    var id = req["id"] as? String ?? ""
    if id.hasPrefix(prefix) { id.removeFirst(prefix.count) }
    guard let r = store.calendarItem(withIdentifier: id) as? EKReminder else { throw OpError(code: "reminder_not_found") }
    try requireWritable(r.calendar)
    return r
}
func save(_ r: EKReminder) throws -> Any {
    do { try store.save(r, commit: true) } catch { throw OpError(code: "save_failed:\(error.localizedDescription)") }
    return describe(r)
}

func perform(_ req: [String: Any]) throws -> Any {
    switch req["action"] as? String ?? "" {
    case "lists":
        return store.calendars(for: .reminder).map { ["name": $0.title] }
    case "list":
        let calendars = try (req["lists"] as? [String] ?? []).map { try calendar(named: $0) }
        var rows: [[String: Any]] = []
        let done = DispatchSemaphore(value: 0)
        store.fetchReminders(matching: store.predicateForIncompleteReminders(
            withDueDateStarting: nil, ending: nil, calendars: calendars)) { found in
            rows = (found ?? []).map { describe($0) }
            done.signal()
        }
        done.wait()
        return rows
    case "create":
        let cal = try calendar(named: req["list"] as? String ?? "")
        try requireWritable(cal)
        let r = EKReminder(eventStore: store)
        r.calendar = cal
        r.title = req["title"] as? String ?? ""
        if r.title.isEmpty { throw OpError(code: "title_required") }
        r.notes = req["notes"] as? String
        try applyDue(r, req["due"])
        if let p = req["priority"] as? Int { r.priority = p }
        return try save(r)
    case "complete":
        let r = try reminder(req); r.isCompleted = true; return try save(r)
    case "set-due":
        let r = try reminder(req); try applyDue(r, req["due"]); return try save(r)
    case "update":
        let r = try reminder(req)
        if let t = req["title"] as? String { r.title = t }
        if let n = req["notes"] as? String { r.notes = n }
        if let p = req["priority"] as? Int { r.priority = p }
        return try save(r)
    case "delete":
        let r = try reminder(req)
        let gone = describe(r)
        do { try store.remove(r, commit: true) } catch { throw OpError(code: "delete_failed:\(error.localizedDescription)") }
        return gone
    case "move":
        let r = try reminder(req)
        let cal = try calendar(named: req["list"] as? String ?? "")
        try requireWritable(cal)
        r.calendar = cal
        return try save(r)
    default:
        throw OpError(code: "unknown_action")
    }
}

var output: Any
if request["action"] as? String == "batch" {
    output = (request["ops"] as? [[String: Any]] ?? []).map { op -> [String: Any] in
        if op["action"] as? String == "batch" { return ["ok": false, "error": "nested_batch"] }
        do { return ["ok": true, "result": try perform(op)] }
        catch let e as OpError { return ["ok": false, "error": e.code, "id": op["id"] ?? NSNull()] }
        catch { return ["ok": false, "error": "\(error)"] }
    }
} else {
    do { output = try perform(request) } catch let e as OpError { fatal(e.code, 4) } catch { fatal("\(error)", 4) }
}
print(String(data: try! JSONSerialization.data(withJSONObject: output), encoding: .utf8)!)
"""


def fail(code: str, detail: str = "") -> int:
    print(json.dumps({"ok": False, "error": code, "detail": detail[-2000:]}))
    return 2


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        return fail("request_too_large")
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        return fail("invalid_json")
    if not isinstance(request, dict) or request.get("action") not in ACTIONS:
        return fail("unknown_action")
    request["_writable"] = ALLOWED_WRITE_LISTS
    try:
        result = subprocess.run(["/usr/bin/swift", "-", json.dumps(request)], input=SWIFT,
                                capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return fail("reminders_timeout",
                    "Reminders did not answer; macOS may be showing a permission prompt on the Mac.")
    if result.returncode != 0:
        return fail("reminders_failed", result.stderr.strip())
    print(json.dumps({"ok": True, "action": request["action"], "result": json.loads(result.stdout)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
