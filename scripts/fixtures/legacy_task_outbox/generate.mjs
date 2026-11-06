// Writes real npm-CLI Task outbox records (taskMutationDelivery.ts and
// taskActivityDelivery.ts with a failing transport) into one JSON fixture used
// by the native legacy-outbox adoption tests. Synthetic key/account only.
// Run from the repo root:
//   OPENMATES_CLI_NODE_MODULES=<npm cli node_modules> node --import \
//     ./scripts/fixtures/legacy_task_outbox/register.mjs \
//     scripts/fixtures/legacy_task_outbox/generate.mjs <output.json>
import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
const src = new URL("../../../frontend/packages/openmates-cli/src/", import.meta.url);
const tasks = await import(new URL("tasksCli.ts", src).href);
const { taskMutationStore } = await import(new URL("taskMutationDelivery.ts", src).href);
const { activityDeliveryStore } = await import(new URL("taskActivityDelivery.ts", src).href);
const { TaskDeliveryPending } = await import(new URL("taskDelivery.ts", src).href);

const master = new Uint8Array(32).fill(7);
const scope = ["https://api.example.org", "fixture-owner", "personal"];
const root = mkdtempSync(join(tmpdir(), "legacy-outbox-"));
const offline = async () => { throw new TypeError("fetch failed"); };
const client = { createUserTask: offline, updateUserTask: offline, completeUserTask: offline, deleteUserTask: offline, getUserTask: offline };
const pending = async (promise) => { try { await promise; throw new Error("expected pending"); } catch (e) { if (!(e instanceof TaskDeliveryPending)) throw e; } };
const id = (n) => n.repeat(64);

const create = await tasks.buildCreateUserTaskInput(master, { taskId: "aabbccdd-1111-4111-8111-aabbccddeeff", title: "Legacy private title", description: "Legacy private details", assign: "openmates" });
const existing = await tasks.buildCreateUserTaskInput(master, { taskId: "bbbbbbbb-1111-4111-8111-aabbccddeeff", title: "Existing title", description: "Existing details", assign: "user" });
const record = { ...existing, version: 3, status: "todo", source: "user" };
const decrypted = await tasks.decryptUserTask(record, master);
const update = await tasks.buildUpdateUserTaskInput(decrypted, master, { title: "Legacy edited title" });
const store = taskMutationStore(scope, root);
// First delivery reaches transport (uncertain=true); the account cooldown then
// keeps later intents un-attempted (no uncertain flag), like a real outage.
await pending(store.deliver(id("1"), async () => ({ kind: "create", taskId: create.task_id, input: create }), client));
await pending(store.deliver(id("2"), async () => ({ kind: "update", taskId: decrypted.taskId, input: update }), client));
await pending(store.deliver(id("3"), async () => ({ kind: "complete", taskId: decrypted.taskId, input: { version: 3 } }), client));
await pending(store.deliver(id("4"), async () => ({ kind: "create", taskId: "cccccccc-1111-4111-8111-aabbccddeeff", input: { ...existing, task_id: "cccccccc-1111-4111-8111-aabbccddeeff" }, creator: "codex" }), client));
for (const [actor, n] of [["user", "5"], ["assignee", "6"]]) {
  await pending(activityDeliveryStore(JSON.stringify([...scope, decrypted.taskId, actor]), root, () => Date.now() + 10 * 60_000)
    .deliver(id(n), () => tasks.buildCreateTaskActivityInput(decrypted, master, { message: `Legacy ${actor} comment`, entryId: id(n) }), offline));
}
const files = {};
const walk = (dir) => { for (const name of readdirSync(dir)) { const path = join(dir, name); if (statSync(path).isDirectory()) walk(path); else files[relative(root, path)] = readFileSync(path, "utf8"); } };
walk(root);
rmSync(root, { recursive: true, force: true });
writeFileSync(process.argv[2], JSON.stringify({ generator: "scripts/fixtures/legacy_task_outbox/generate.mjs", master_key_byte: 7, scope, existing_task: record, files }, null, 1) + "\n");
