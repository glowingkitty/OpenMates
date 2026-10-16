import assert from "node:assert/strict";
import { test } from "node:test";
import type { MentionContext } from "../src/mentions.js";
import type { TuiModelEntry } from "../src/tuiModelSelector.js";
import { buildTuiMentionCatalog, extractTuiMention, searchTuiMentionCatalog, type TuiMentionProject } from "../src/tuiMentionCatalog.js";

const models: TuiModelEntry[] = [
  { id: "openai/gpt-6-astra", name: "GPT-6 Astra", providerId: "openai", providerName: "OpenAI", description: "reasoning", available: true },
  { id: "qwen/qwen3-235b-a22b-2507", name: "Qwen 3", providerId: "qwen", providerName: "Qwen", description: "fast", available: true },
  { id: "openai/gpt-6-sol", name: "GPT-6 Sol", providerId: "openai", providerName: "OpenAI", description: "coding", available: true },
  { id: "openai/hidden", name: "Hidden", providerId: "openai", providerName: "OpenAI", description: "hidden", available: false },
];
const context: MentionContext = {
  models: [], mates: { software_development: "Sophia" },
  apps: [
    { id: "ai", name: "AI", skills: [{ id: "ask", name: "Ask" }] },
    { id: "web", name: "Web", skills: [{ id: "search", name: "Search" }], focus_modes: [{ id: "research", name: "Research" }] },
    { id: "code", name: "Code", settings_and_memories: [
      { id: "projects", name: "Projects", type: "list" }, { id: "empty", name: "Empty", type: "list" },
    ] },
  ],
  memoryEntries: [{ id: "entry-1", app_id: "code", item_type: "projects", title: "My App" }],
};
const projects: TuiMentionProject[] = [
  { id: "p1", name: "Alpha Project", accessMode: "read_write", files: [{ path: "docs/readme.md", name: "Readme" }], folders: [{ path: "/src", sourceId: "source1" }] },
  { id: "p2", name: "Read Only Project", accessMode: "read" },
];

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("@ trigger follows web whitespace and caret rules", () => {
  assert.deepEqual(extractTuiMention("@web", 4), { start: 0, end: 4, query: "web" });
  assert.deepEqual(extractTuiMention("hi\n@web text", 7), { start: 3, end: 7, query: "web" });
  assert.equal(extractTuiMention("mail@example.com", 16), null);
  assert.equal(extractTuiMention("@web search", 11), null);
  assert.equal(extractTuiMention("@one@two", 8), null);
  assert.equal(extractTuiMention("@web", 5), null);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,ai-model-routing.surface.semantic-parity
test("catalog uses live available models and emits backend wire tokens", () => {
  const catalog = buildTuiMentionCatalog(context, models, projects, false);
  const byId = (id: string) => catalog.find(item => item.id === id);
  assert.equal(byId("model:openai/gpt-6-astra")?.wireSyntax, "@ai-model:gpt-6-astra:openai");
  assert.equal(byId("alias:best")?.wireSyntax, "@best-model:best");
  assert.equal(byId("alias:fast")?.modelId, "qwen/qwen3-235b-a22b-2507");
  assert.equal(byId("model:openai/hidden"), undefined);
  assert.equal(byId("skill:ai:ask"), undefined);
  assert.equal(byId("mate:software_development")?.wireSyntax, "@mate:software_development");
  assert.equal(byId("skill:web:search")?.wireSyntax, "@skill:web:search");
  assert.equal(byId("focus:web:research")?.wireSyntax, "@focus:web:research");
  assert.equal(byId("memory:code:projects")?.wireSyntax, "@memory:code:projects:list");
  assert.equal(byId("memory-entry:code:projects:entry-1")?.wireSyntax, "@memory-entry:code:projects:entry-1");
  assert.equal(byId("memory:code:empty"), undefined);
  assert.equal(byId("project:p1")?.wireSyntax, "@project:p1:read_write");
  assert.equal(byId("project:p2")?.wireSyntax, "@project:p2:read");
  assert.equal(byId("project_file:p1::docs/readme.md")?.wireSyntax, "@project-file:p1:docs%2Freadme.md:read_write");
  assert.equal(byId("project_folder:p1:source1:/src")?.wireSyntax, "@project-folder:p1:source1:%2Fsrc:read_write");
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,teams.chat.encrypted-until-invoked
test("defaults and query ranking include Team AI only in Team mode", () => {
  const personal = buildTuiMentionCatalog(context, models, projects, false);
  const team = buildTuiMentionCatalog(context, models, projects, true);
  assert.deepEqual(searchTuiMentionCatalog(personal, "").map(item => item.type),
    ["wikipedia_source", "model_alias", "model_alias", "model", "model"]);
  assert.equal(searchTuiMentionCatalog(team, "")[1]?.wireSyntax, "@openmates");
  assert.equal(searchTuiMentionCatalog(personal, "alpha")[0]?.wireSyntax, "@project:p1:read_write");
  assert.equal(searchTuiMentionCatalog(personal, "wiki")[0]?.wireSyntax, "@wiki:");
  assert.ok(searchTuiMentionCatalog(personal, "").every(item => item.label !== "@Hidden"));
  assert.ok(searchTuiMentionCatalog(personal, "a").length <= 8);
});
