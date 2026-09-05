#!/usr/bin/env node
/*
 * Conflict-only delivery contracts for OpenCode presence.
 * Reads remain allowed, exact writes remain delegated to existing guards, and
 * unrelated sessions receive no appended context or synthetic chat activity.
 * Run: node --test scripts/tests/test_opencode_presence_collisions.mjs.
 */

// contract-test-file: tooling

import assert from "node:assert/strict";
import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { childMutationDecisionForTest, readConflictWarningForTest } = OpenMatesHooks.test;

const data = {
  sessions: {
    a111: { opencode_session_id: "ses-a", task: "edit sessions", worktree: { status: "active" } },
    b222: { opencode_session_id: "ses-b", task: "frontend", worktree: { status: "active" } },
  },
  edit_leases: { "scripts/sessions.py": { session_id: "a111", since: "2026-08-05T00:00:00Z" } },
};
const presence = { sessions: { "ses-a": { execution: "busy", child_role: "unknown" } } };

test("unrelated paths add no context", () => {
  assert.equal(readConflictWarningForTest({ path: "frontend/example.ts", sessionID: "ses-b", data, presence }), "");
});

test("read overlapping a live writer gets one concise non-blocking warning", () => {
  const warning = readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-b", data, presence });
  assert.match(warning, /OpenMates presence conflict/);
  assert.match(warning, /scripts\/sessions\.py/);
  assert.match(warning, /a111/);
  assert.doesNotMatch(warning, /frontend|full active|prompt/);
});

test("a session and its explicitly read-only child do not conflict", () => {
  const grouped = {
    sessions: {
      "ses-a": { execution: "busy", child_role: "unknown" },
      "ses-child": { execution: "busy", parent_id: "ses-a", child_role: "read_only" },
    },
  };
  assert.equal(readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-child", data, presence: grouped }), "");
});

test("collision calculation has no prompt or command side effects", () => {
  let calls = 0;
  const sideEffects = { prompt: () => calls++, command: () => calls++ };
  readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-b", data, presence, sideEffects });
  assert.equal(calls, 0);
});

test("only writable children can mutate through an inherited parent route", () => {
  for (const role of ["unknown", "read_only", "reviewer"]) {
    const decision = childMutationDecisionForTest({ inheritedParentRoute: true, childRole: role }, "apply_patch");
    assert.equal(decision.decision, "block");
    assert.match(decision.message, /Reason:/);
    assert.match(decision.message, /Next:/);
  }
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "writable" }, "apply_patch").decision, "allow");
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "writable" }, "bash", "npm run format").decision, "allow");
  for (const command of [
    "python3 scripts/sessions.py start --mode bug --task test",
    "python scripts/sessions.py start --mode bug --task test",
    "./scripts/sessions.py start --mode bug --task test",
    "env python3 scripts/sessions.py start --mode bug --task test",
    "python3 -u scripts/../scripts/sessions.py start --mode bug --task test",
    `python3 ${process.cwd()}/scripts/sessions.py start --mode bug --task test`,
    "python3 -m scripts.sessions start --mode bug --task test",
    "date && python3 scripts/sessions.py worktree ensure --session child",
  ]) {
    assert.equal(childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "writable" }, "bash", command).decision, "block");
  }
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "reviewer" }, "read").decision, "allow");
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: false, childRole: "writable" }, "apply_patch").decision, "allow");
});

test("writable children cannot alias sessions.py to create a child worktree", () => {
  const directory = mkdtempSync(join(tmpdir(), "openmates-child-session-"));
  const alias = join(directory, "child.py");
  try {
    symlinkSync(new URL("../../scripts/sessions.py", import.meta.url), alias);
    const decision = childMutationDecisionForTest(
      { inheritedParentRoute: true, childRole: "writable" },
      "bash",
      `python3 ${alias} start --mode bug --task test`,
    );
    assert.equal(decision.decision, "block");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("inherited children can run known read-only shell diagnostics", () => {
  const route = { inheritedParentRoute: true, childRole: "unknown" };
  const commands = [
    "git status --short",
    "git blame -L 2800,2830 -- backend/apps/ai/processing/main_processor.py",
    "git diff --no-ext-diff --name-status de53771^ de53771",
    "git log --oneline --all -- backend/apps/ai/processing/main_processor.py",
    "git show origin/main:backend/apps/ai/processing/main_processor.py",
    "git diff --no-ext-diff --name-only $(git merge-base de53771 origin/main) de53771",
    "gh run view 31112777028 --log-failed",
    "docker exec api python /app/backend/scripts/debug.py chat synthetic-chat-id",
    "docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json '{}'",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --production",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --timeline --production",
    "python3 scripts/issues.py show synthetic-id --env prod",
    "python3 scripts/issues.py show synthetic-id --env prod --full --json",
    "python3 scripts/issues.py timeline synthetic-id --env prod --compact",
    "python3 scripts/issues.py --help",
    "./scripts/issues.py show synthetic-id --env prod",
    "python3 scripts/sessions.py --help",
    "openmates apps code get_docs --library React --question 'How do I use useState?' --json",
    "openmates apps web search 'official OpenCode configuration documentation' --json",
    "openmates apps web read https://example.com --json",
    "openmates apps web read --url https://example.com --formats markdown --only-main-content true --max-age 0 --timeout 30000 --json",
    "python3 scripts/tests.py status --json && python3 scripts/tests.py triage --json",
    "git blame -L 807,1052 -- frontend/packages/openmates-cli/src/ws.ts | rg awaitingSubChatsCompletion",
    "rg -o -i \"[a-zA-Z0-9_.-]*(journey|occupancy|coach|ris|disruption)[a-zA-Z0-9_.-]*\" /tmp/bundle.js | sort -u",
    "wc -c /tmp/stop.js /tmp/main.js && rg -o -i \"[a-zA-Z0-9_.-]*(journey|occupancy)[a-zA-Z0-9_.-]*\" /tmp/stop.js | sort -u",
    "rg -o -P '.{0,500}zM=fi\\(`/details/\\$train/j/\\$journeyId`\\).{0,1500}' /tmp/bundle.js",
    "rg -o \"BM=fi\" /tmp/bundle.js | wc -l",
    "git show HEAD:scripts/sessions.py | nl -ba | head -n 20",
    "docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json '{\"stream\":\"client_console\",\"filters\":[],\"since_minutes\":1440,\"limit\":100}' && docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json '{\"stream\":\"default\",\"filters\":[],\"since_minutes\":1440,\"limit\":100}' && docker exec api python /app/backend/scripts/debug.py trace errors --last 24h",
  ];
  for (const command of commands) {
    assert.equal(childMutationDecisionForTest(route, "bash", command).decision, "allow", command);
  }
  assert.equal(
    childMutationDecisionForTest(route, "bash", "python3 scripts/sessions.py start --mode bug --task test").decision,
    "block",
  );
  for (const command of [
    "git status --short && touch scripts/child-write.py",
    "git status --short $(touch scripts/child-write.py)",
    "rg -o -P \".{0,500}zM=fi\\(`/details/\\$train/j/\\$journeyId`\\).{0,1500}\" /tmp/bundle.js",
    "git status --short <(touch scripts/child-write.py)",
    "git diff --output=scripts/child-write.py",
    "git diff $(touch scripts/child-write.py)",
    "GIT_EXTERNAL_DIFF=./scripts/mutate.sh git diff --ext-diff",
    "env GIT_EXTERNAL_DIFF=./scripts/mutate.sh git diff --ext-diff",
    "git diff --ext-diff",
    "git show --textconv HEAD:file.txt",
    "git --paginate log --oneline",
    "rg --pre 'touch scripts/child-write.py' needle .",
    "rg --pre=./scripts/mutate.sh needle .",
    "rg --hostname-bin ./scripts/mutate.sh needle .",
    "rg --search-zip needle .",
    "sort -o scripts/child-write.py package.json",
    "sort --output=scripts/child-write.py package.json",
    "sort --compress-program=./scripts/mutate.sh package.json",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --delete --yes",
    "docker exec api python /app/backend/scripts/debug.py logs --upload-update",
    "docker exec api python /app/backend/scripts/debug.py logs --preview-update",
    "docker exec api python /app/backend/scripts/debug.py chat synthetic-id --repair-messages-v",
    "python3 scripts/issues.py findings synthetic-id --env prod",
    "./scripts/issues.py mark synthetic-id --env prod --status resolved",
    "python3 scripts/issues.py link synthetic-id --github issue-url",
    "python3 -c 'from pathlib import Path; Path(\"scripts/child-write.py\").write_text(\"x\")' scripts/issues.py show synthetic-id",
    "python3 -m scripts.issues show synthetic-id",
    "python3 - scripts/issues.py show synthetic-id",
    "docker exec api python -c 'print(1)' /app/backend/scripts/debug.py issue synthetic-id --production",
    "python3 scripts/issues.py show synthetic-id --unknown-write-flag",
    "python3 scripts/issues.py show synthetic-id --env --unknown-write-flag",
    "python3 scripts/issues.py show synthetic-id --env=--unknown-write-flag",
    "python3 scripts/sessions.py --help --unknown-write-flag",
    "openmates apps code search --query React --json",
    "openmates apps web search --query docs --api-key secret --json",
    "openmates apps web read https://example.com --disable-prompt-injection-protection --json",
    "openmates apps web read https://example.com --json && touch scripts/child-write.py",
    "openmates apps github create_issue --input '{} ' --json",
    "python3 scripts/tests.py run --suite playwright",
    "python3 -m pytest scripts/tests/test_sessions_worktree_lifecycle.py",
    "python3 scripts/tests.py next --lease --session child",
    "python3 scripts/tests.py triage --json --claim",
    "docker exec api python /app/backend/scripts/debug.py trace errors --last 24h --repair",
    "git diff {--output=scripts/child-write.py,}",
    "docker exec api python /app/backend/scripts/debug.py trace errors --last ${IFS}24h${IFS}--repair",
    "python3 scripts/tests.py status $TEST_FLAGS",
    "python3 scripts/tests.py status --json=*",
    "python3 scripts/tests.py status --json=anything",
    "docker exec api python /app/backend/scripts/debug.py trace errors --production=yes",
    "./other/issues.py show synthetic-id --env prod",
    "docker exec api python /app/backend/scripts/debug.py logs --query-json --upload-update",
    "docker exec api python /app/backend/scripts/debug.py logs --query-json=--upload-update",
    "git status --short\ntouch scripts/child-write.py",
    "git status --short # inspect only\ntouch scripts/child-write.py",
    "git status --short\ndocker restart api",
  ]) {
    assert.equal(childMutationDecisionForTest(route, "bash", command).decision, "block");
  }
});
