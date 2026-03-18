#!/usr/bin/env node
/*
 * OpenMates CLI command entry.
 *
 * Purpose: provide pair-auth login, chat, app, and settings/memories commands.
 * Architecture: argument router over the OpenMatesClient SDK.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: login never prompts for account credentials, only pair PIN.
 * Tests: frontend/packages/openmates-cli/tests/
 */

import {
  OpenMatesClient,
  MEMORY_TYPE_REGISTRY,
  type ChatListPage,
  type DecryptedMessage,
  type DecryptedEmbed,
} from "./client.js";

type CliArgs = {
  positionals: string[];
  flags: Record<string, string | boolean>;
};

async function main(): Promise<void> {
  const parsed = parseArgs(process.argv.slice(2));
  const [command, subcommand, ...rest] = parsed.positionals;
  const client = OpenMatesClient.load({
    apiUrl:
      typeof parsed.flags["api-url"] === "string"
        ? parsed.flags["api-url"]
        : undefined,
  });

  if (!command || command === "help") {
    printHelp();
    return;
  }

  // --help with a command shows that command's help, not the global one
  if (parsed.flags.help === true && !subcommand) {
    // e.g. `openmates chats --help` → show chats help
    if (command === "chats") {
      printChatsHelp();
      return;
    }
    if (command === "apps") {
      printAppsHelp();
      return;
    }
    if (command === "settings") {
      printSettingsHelp();
      return;
    }
    if (command === "embeds") {
      printEmbedsHelp();
      return;
    }
    printHelp();
    return;
  }

  if (command === "login") {
    await client.loginWithPairAuth();
    console.log("Login successful.");
    return;
  }

  if (command === "logout") {
    await client.logout();
    console.log("Logged out.");
    return;
  }

  if (command === "whoami") {
    const user = await client.whoAmI();
    if (parsed.flags.json === true) {
      printJson(user);
    } else {
      printWhoAmI(user as Record<string, unknown>);
    }
    return;
  }

  if (command === "chats") {
    await handleChats(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "apps") {
    await handleApps(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "embeds") {
    await handleEmbeds(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "settings") {
    await handleSettings(client, subcommand, rest, parsed.flags);
    return;
  }

  throw new Error(`Unknown command '${command}'. Run 'openmates help'.`);
}

// ---------------------------------------------------------------------------
// Chats
// ---------------------------------------------------------------------------

async function handleChats(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printChatsHelp();
    return;
  }

  if (subcommand === "list") {
    const limit =
      typeof flags.limit === "string" ? parseInt(flags.limit, 10) : 10;
    const page = typeof flags.page === "string" ? parseInt(flags.page, 10) : 1;
    const result = await client.listChats(limit, page);
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatsTable(result);
    }
    return;
  }

  if (subcommand === "search") {
    const query = rest.join(" ").trim();
    if (!query)
      throw new Error(
        "Missing search query. Usage: openmates chats search <query>",
      );
    const result = await client.searchChats(query);
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatsTable({
        chats: result,
        total: result.length,
        page: 1,
        limit: result.length,
        hasMore: false,
      });
    }
    return;
  }

  if (subcommand === "new") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats new <message>",
      );
    const result = await client.sendMessage({
      message,
      chatId: undefined,
      incognito: false,
    });
    if (flags.json === true) {
      printJson({ chat_id: result.chatId, assistant: result.assistant });
    } else {
      printChatResponse(result.chatId, result.assistant);
    }
    return;
  }

  if (subcommand === "send") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats send [--chat <id>] <message>",
      );
    const chatId = typeof flags.chat === "string" ? flags.chat : undefined;
    const result = await client.sendMessage({
      message,
      chatId,
      incognito: flags.incognito === true,
    });
    if (flags.json === true) {
      printJson({ chat_id: result.chatId, assistant: result.assistant });
    } else {
      printChatResponse(result.chatId, result.assistant);
    }
    return;
  }

  if (subcommand === "incognito") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    const result = await client.sendMessage({ message, incognito: true });
    if (flags.json === true) {
      printJson({ chat_id: result.chatId, assistant: result.assistant });
    } else {
      printChatResponse(result.chatId, result.assistant);
    }
    return;
  }

  if (subcommand === "incognito-history") {
    const history = client.getIncognitoHistory();
    if (flags.json === true) {
      printJson(history);
    } else {
      printIncognitoHistory(history);
    }
    return;
  }

  if (subcommand === "incognito-clear") {
    client.clearIncognitoHistory();
    console.log("Incognito history cleared.");
    return;
  }

  if (subcommand === "show") {
    const chatId = rest[0];
    if (!chatId) {
      console.error("Missing chat ID.\n");
      printChatsHelp();
      process.exit(1);
    }
    const { chat, messages } = await client.getChatMessages(chatId);
    if (flags.json === true) {
      printJson({ chat, messages });
    } else {
      printChatConversation(chat, messages);
    }
    return;
  }

  console.error(`Unknown chats subcommand '${subcommand}'.\n`);
  printChatsHelp();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Apps
// ---------------------------------------------------------------------------

async function handleApps(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  // API key is optional — session cookies are used when absent
  const apiKey = resolveApiKey(flags) ?? undefined;

  if (!subcommand || subcommand === "help" || flags.help === true) {
    printAppsHelp();
    return;
  }

  if (subcommand === "list") {
    const data = await client.listApps(apiKey);
    if (flags.json === true) {
      printJson(data);
    } else {
      printAppsList(data as AppsListResponse);
    }
    return;
  }

  if (subcommand === "info") {
    const appId = rest[0];
    if (!appId) {
      console.error("Missing app ID.\n");
      printAppsHelp();
      process.exit(1);
    }
    const data = await client.getApp(appId);
    if (flags.json === true) {
      printJson(data);
    } else {
      printAppInfo(data as AppMetadata);
    }
    return;
  }

  if (subcommand === "skill-info") {
    const [appId, skillId] = rest;
    if (!appId || !skillId) {
      console.error(`Missing ${!appId ? "app ID" : "skill ID"}.\n`);
      printAppsHelp();
      process.exit(1);
    }
    const data = await client.getSkillInfo(appId, skillId, apiKey);
    if (flags.json === true) {
      printJson(data);
    } else {
      printSkillInfo(appId, data as SkillMetadata);
    }
    return;
  }

  // `apps run` is removed — the sugar alias `apps <app> <skill> [text]` is
  // the canonical way to run skills. Catch it explicitly so users get a
  // helpful redirect instead of a confusing "unknown subcommand" error.
  if (subcommand === "run") {
    const [app, skill, ...inlineTokens] = rest;
    if (!app || !skill) {
      console.error(
        "The 'run' subcommand has been replaced by the shorter sugar syntax.\n",
      );
      printAppsHelp();
      process.exit(1);
    }
    // Silently forward to the sugar alias execution path
    const inputData = buildSkillInput(flags, inlineTokens);
    const data = await client.runSkill({ app, skill, inputData, apiKey });
    if (flags.json === true) {
      printJson(data);
    } else {
      printSkillResult(app, skill, data);
    }
    return;
  }

  // Sugar alias: openmates apps <app> <skill> [inline text]
  const app = subcommand;
  const skill = rest[0];
  if (app && skill) {
    const inputData = buildSkillInput(flags, rest.slice(1));
    const data = await client.runSkill({ app, skill, inputData, apiKey });
    if (flags.json === true) {
      printJson(data);
    } else {
      printSkillResult(app, skill, data);
    }
    return;
  }

  // `apps <app>` with no skill — treat as `apps info <app>`
  if (app && !skill) {
    const data = await client.getApp(app);
    if (flags.json === true) {
      printJson(data);
    } else {
      printAppInfo(data as AppMetadata);
    }
    return;
  }

  console.error(`Unknown apps subcommand '${subcommand}'.\n`);
  printAppsHelp();
  process.exit(1);
}

/**
 * Build skill input data from --input flag or inline positional text.
 * Inline text is wrapped as { requests: [{ query: text }] } which matches
 * the tool_schema convention used by most query-based skills (web, news, etc.).
 * For skills with different schemas use --input '<json>' explicitly.
 */
function buildSkillInput(
  flags: Record<string, string | boolean>,
  inlineTokens: string[],
): Record<string, unknown> {
  if (typeof flags.input === "string") {
    return JSON.parse(flags.input) as Record<string, unknown>;
  }
  const inlineText = inlineTokens.join(" ").trim();
  if (inlineText) return { requests: [{ query: inlineText }] };
  return {};
}

// ---------------------------------------------------------------------------
// Embeds
// ---------------------------------------------------------------------------

async function handleEmbeds(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printEmbedsHelp();
    return;
  }

  if (subcommand === "show") {
    const embedId = rest[0];
    if (!embedId) {
      console.error("Missing embed ID.\n");
      printEmbedsHelp();
      process.exit(1);
    }
    const embed = await client.getEmbed(embedId);
    if (flags.json === true) {
      printJson(embed);
    } else {
      printEmbedDetail(embed);
    }
    return;
  }

  console.error(`Unknown embeds subcommand '${subcommand}'.\n`);
  printEmbedsHelp();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function handleSettings(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printSettingsHelp();
    return;
  }

  if (subcommand === "get") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const result = await client.settingsGet(path);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "post") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPost(path, data);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "delete") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const result = await client.settingsDelete(path);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "patch") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPatch(path, data);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "memories") {
    await handleMemories(client, rest, flags);
    return;
  }

  console.error(`Unknown settings subcommand '${subcommand}'.\n`);
  printSettingsHelp();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Memories
// ---------------------------------------------------------------------------

async function handleMemories(
  client: OpenMatesClient,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  const action = rest[0];

  if (!action || action === "help") {
    printMemoriesHelp();
    return;
  }

  if (action === "list") {
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : null;
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : null;
    let result = await client.listMemories();
    if (appId) result = result.filter((m) => m.app_id === appId);
    if (itemType) result = result.filter((m) => m.item_type === itemType);
    if (flags.json === true) {
      printJson(result);
    } else {
      printMemoriesList(result);
    }
    return;
  }

  if (action === "types") {
    const types = Object.entries(MEMORY_TYPE_REGISTRY).map(([key, def]) => ({
      key,
      app_id: def.appId,
      item_type: def.itemType,
      entry_type: def.entryType,
      required: def.required,
      properties: Object.keys(def.properties),
    }));
    const appFilter =
      typeof flags["app-id"] === "string" ? flags["app-id"] : null;
    const filtered = appFilter
      ? types.filter((t) => t.app_id === appFilter)
      : types;
    if (flags.json === true) {
      printJson(filtered);
    } else {
      printMemoryTypes(filtered);
    }
    return;
  }

  if (action === "create") {
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : "";
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : "";
    const dataRaw = typeof flags.data === "string" ? flags.data : null;

    if (!appId || !itemType) {
      console.error(
        "Missing required flags.\n\n" +
          "Usage: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\n\n" +
          "Run 'openmates settings memories types' to see all available types.",
      );
      process.exit(1);
    }
    if (!dataRaw) {
      console.error(
        "Missing --data '<json>'. Provide the memory field values as a JSON object.\n\n" +
          `Example: --data '{"name":"Python","proficiency":"advanced"}'`,
      );
      process.exit(1);
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.createMemory({ appId, itemType, itemValue });
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(
        `\x1b[32m✓\x1b[0m Memory created  \x1b[2mid: ${result.id}\x1b[0m`,
      );
    }
    return;
  }

  if (action === "update") {
    const entryId = typeof flags.id === "string" ? flags.id : "";
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : "";
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : "";
    const dataRaw = typeof flags.data === "string" ? flags.data : null;
    const currentVersion =
      typeof flags.version === "string" ? parseInt(flags.version, 10) : 1;

    if (!entryId || !appId || !itemType) {
      console.error(
        "Missing required flags.\n\n" +
          "Usage: openmates settings memories update --id <entry-id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]",
      );
      process.exit(1);
    }
    if (!dataRaw) {
      console.error("Missing --data '<json>'.");
      process.exit(1);
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.updateMemory({
      entryId,
      appId,
      itemType,
      itemValue,
      currentVersion,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(
        `\x1b[32m✓\x1b[0m Memory updated  \x1b[2mid: ${result.id}\x1b[0m`,
      );
    }
    return;
  }

  if (action === "delete") {
    const entryId = typeof flags.id === "string" ? flags.id : (rest[1] ?? "");
    if (!entryId) {
      console.error(
        "Missing entry ID.\n\nUsage: openmates settings memories delete --id <entry-id>",
      );
      process.exit(1);
    }
    const result = await client.deleteMemory(entryId);
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(`\x1b[32m✓\x1b[0m Memory deleted`);
    }
    return;
  }

  console.error(
    `Unknown memories action '${action}'.\n\nUsage: openmates settings memories <list|types|create|update|delete>`,
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

function parseArgs(argv: string[]): CliArgs {
  const positionals: string[] = [];
  const flags: Record<string, string | boolean> = {};

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const keyValue = arg.slice(2).split("=", 2);
    const key = keyValue[0];
    const valueFromEquals = keyValue[1];

    if (valueFromEquals !== undefined) {
      flags[key] = valueFromEquals;
      continue;
    }

    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      flags[key] = next;
      i += 1;
    } else {
      flags[key] = true;
    }
  }

  return { positionals, flags };
}

function resolveApiKey(flags: Record<string, string | boolean>): string | null {
  if (typeof flags["api-key"] === "string" && flags["api-key"].length > 0) {
    return flags["api-key"];
  }
  if (process.env.OPENMATES_API_KEY) return process.env.OPENMATES_API_KEY;
  return null;
}

// ---------------------------------------------------------------------------
// Output primitives
// ---------------------------------------------------------------------------

/** Raw JSON output for --json flag */
function printJson(value: unknown): void {
  console.log(JSON.stringify(value, null, 2));
}

/** Dim separator line */
function hr(): void {
  process.stdout.write("\x1b[2m" + "─".repeat(60) + "\x1b[0m\n");
}

/** Bold section header */
function header(text: string): void {
  process.stdout.write(`\x1b[1m${text}\x1b[0m\n`);
}

/** Key-value row: "  key   value" */
function kv(key: string, value: string, keyWidth = 16): void {
  const padded = key.padEnd(keyWidth);
  process.stdout.write(`  \x1b[2m${padded}\x1b[0m ${value}\n`);
}

// ---------------------------------------------------------------------------
// Chats renderers
// ---------------------------------------------------------------------------

/**
 * Category gradient colors — start color of each gradient from categoryUtils.ts
 */
const CATEGORY_ANSI_COLORS: Record<string, [number, number, number]> = {
  software_development: [21, 93, 145],
  business_development: [0, 64, 64],
  medical_health: [253, 80, 160],
  legal_law: [35, 156, 255],
  openmates_official: [99, 102, 241],
  maker_prototyping: [234, 118, 0],
  marketing_sales: [255, 140, 0],
  finance: [17, 145, 6],
  design: [16, 16, 16],
  electrical_engineering: [35, 56, 136],
  movies_tv: [0, 194, 197],
  history: [73, 137, 242],
  science: [206, 91, 6],
  life_coach_psychology: [253, 178, 80],
  cooking_food: [253, 132, 80],
  activism: [245, 61, 0],
  general_knowledge: [222, 30, 102],
  onboarding_support: [99, 100, 255],
};

const CATEGORY_LABELS: Record<string, string> = {
  software_development: "Software Dev",
  business_development: "Business",
  medical_health: "Health",
  legal_law: "Legal",
  openmates_official: "OpenMates",
  maker_prototyping: "Maker",
  marketing_sales: "Marketing",
  finance: "Finance",
  design: "Design",
  electrical_engineering: "Electrical",
  movies_tv: "Movies & TV",
  history: "History",
  science: "Science",
  life_coach_psychology: "Psychology",
  cooking_food: "Cooking",
  activism: "Activism",
  general_knowledge: "General",
  onboarding_support: "Support",
};

function ansiCategoryPill(category: string | null): string {
  const label = category
    ? (CATEGORY_LABELS[category] ?? category.replace(/_/g, " "))
    : "—";
  if (!category || !CATEGORY_ANSI_COLORS[category]) {
    return `\x1b[2m${label}\x1b[0m`;
  }
  const [r, g, b] = CATEGORY_ANSI_COLORS[category];
  return `\x1b[48;2;${r};${g};${b}m\x1b[97m ${label} \x1b[0m`;
}

function formatTimestamp(ts: number | null): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function printChatsTable(result: ChatListPage): void {
  const { chats, total, page, limit, hasMore } = result;
  const start = (page - 1) * limit + 1;
  const end = start + chats.length - 1;

  if (chats.length === 0) {
    console.log("No chats found.");
    return;
  }

  const totalPages = Math.ceil(total / limit);
  console.log(
    `\x1b[1mChats\x1b[0m  (${start}–${end} of ${total}, page ${page}/${totalPages})\n`,
  );

  for (const chat of chats) {
    const pill = ansiCategoryPill(chat.category);
    const time = formatTimestamp(chat.updatedAt);
    const title = chat.title ?? "\x1b[2m(no title)\x1b[0m";
    const idStr = `\x1b[2m${chat.shortId}\x1b[0m`;

    const mate = chat.mateName ? `  \x1b[36m${chat.mateName}\x1b[0m` : "";
    process.stdout.write(
      `${pill}${mate}  ${title}  ${idStr}  \x1b[2m${time}\x1b[0m\n`,
    );

    if (chat.summary) {
      const maxWidth = 80;
      const summary =
        chat.summary.length > maxWidth
          ? chat.summary.slice(0, maxWidth - 1) + "…"
          : chat.summary;
      process.stdout.write(`    \x1b[2m${summary}\x1b[0m\n`);
    }

    process.stdout.write("\n");
  }

  if (hasMore) {
    const nextPage = page + 1;
    const nextCmd = `chats list --page ${nextPage}${limit !== 10 ? ` --limit ${limit}` : ""}`;
    console.log(`\x1b[2mNext page: openmates ${nextCmd}\x1b[0m`);
  }
}

function printChatResponse(chatId: string, assistant: string): void {
  console.log(`\x1b[2mchat: ${chatId.slice(0, 8)}\x1b[0m\n`);
  console.log(assistant);
}

function printIncognitoHistory(
  history: Array<{ role: string; content: string; createdAt: number }>,
): void {
  if (history.length === 0) {
    console.log("No incognito history.");
    return;
  }
  header(`Incognito history  (${history.length} messages)`);
  console.log();
  for (const msg of history) {
    const ts = formatTimestamp(Math.floor(msg.createdAt / 1000));
    const roleLabel =
      msg.role === "user" ? "\x1b[1mYou\x1b[0m" : "\x1b[36mAssistant\x1b[0m";
    process.stdout.write(`${roleLabel}  \x1b[2m${ts}\x1b[0m\n`);
    console.log(msg.content);
    console.log();
  }
}

/**
 * Render a full chat conversation with messages, mate names, and embed refs.
 */
function printChatConversation(
  chat: {
    id: string;
    shortId: string;
    title: string | null;
    category: string | null;
    mateName: string | null;
    updatedAt: number | null;
  },
  messages: DecryptedMessage[],
): void {
  const pill = ansiCategoryPill(chat.category);
  const title = chat.title ?? "(no title)";
  const ts = formatTimestamp(chat.updatedAt);
  header(`${title}  ${pill}  \x1b[2m${chat.shortId}  ${ts}\x1b[0m`);
  console.log();

  if (messages.length === 0) {
    console.log("\x1b[2m(no messages)\x1b[0m");
    return;
  }

  for (const msg of messages) {
    const msgTs = formatTimestamp(msg.createdAt);
    let roleLabel: string;
    if (msg.role === "user") {
      roleLabel = "\x1b[1mYou\x1b[0m";
    } else if (msg.role === "assistant" || msg.role === "ai") {
      const mate = chat.mateName ?? "Assistant";
      roleLabel = `\x1b[36m${mate}\x1b[0m`;
      if (msg.modelName) {
        roleLabel += `  \x1b[2m(${msg.modelName})\x1b[0m`;
      }
    } else {
      roleLabel = `\x1b[2m${msg.role}\x1b[0m`;
    }

    process.stdout.write(`${roleLabel}  \x1b[2m${msgTs}\x1b[0m\n`);

    if (msg.content) {
      // Strip markdown embed blocks for cleaner CLI display
      const content = msg.content
        .replace(/```json_embed\n[\s\S]*?\n```/g, "[embed]")
        .replace(/```json\n[\s\S]*?\n```/g, "[embed]");
      console.log(content);
    }

    // Show embed references
    if (msg.embedIds.length > 0) {
      for (const eid of msg.embedIds) {
        process.stdout.write(
          `  \x1b[2m📎 embed: ${eid.slice(0, 8)}  (openmates embeds show ${eid.slice(0, 8)})\x1b[0m\n`,
        );
      }
    }
    console.log();
  }
}

/**
 * Render embed detail view.
 */
function printEmbedDetail(embed: DecryptedEmbed): void {
  header(`Embed  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m`);
  console.log();

  if (embed.type) kv("Type", embed.type);
  if (embed.appId) kv("App", embed.appId);
  if (embed.skillId) kv("Skill", embed.skillId);
  if (embed.createdAt) kv("Created", formatTimestamp(embed.createdAt));
  console.log();

  if (embed.textPreview) {
    header("Preview");
    console.log(embed.textPreview);
    console.log();
  }

  if (embed.content) {
    header("Content");
    // Render content fields in a readable way
    for (const [k, v] of Object.entries(embed.content)) {
      if (v === null || v === undefined) continue;
      if (typeof v === "string") {
        if (v.length > 200) {
          kv(k, v.slice(0, 200) + "…", 20);
        } else {
          kv(k, v, 20);
        }
      } else if (Array.isArray(v)) {
        kv(k, `[${v.length} items]`, 20);
        // Show first 3 items briefly
        for (const item of v.slice(0, 3)) {
          if (item && typeof item === "object") {
            const label =
              (item as Record<string, unknown>).title ??
              (item as Record<string, unknown>).name ??
              (item as Record<string, unknown>).url ??
              JSON.stringify(item).slice(0, 80);
            process.stdout.write(`    \x1b[2m• ${String(label)}\x1b[0m\n`);
          } else {
            process.stdout.write(`    \x1b[2m• ${String(item)}\x1b[0m\n`);
          }
        }
        if (v.length > 3) {
          process.stdout.write(
            `    \x1b[2m  ... and ${v.length - 3} more\x1b[0m\n`,
          );
        }
      } else if (typeof v === "object") {
        kv(k, JSON.stringify(v).slice(0, 120), 20);
      } else {
        kv(k, String(v), 20);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Apps renderers
// ---------------------------------------------------------------------------

interface SkillMetadata {
  id: string;
  name: string;
  description?: string;
  providers?: Array<{
    provider: string;
    name?: string;
    description?: string;
    pricing?: unknown;
  }>;
}

interface AppMetadata {
  id: string;
  name: string;
  description?: string;
  skills?: SkillMetadata[];
  focus_modes?: Array<{ id: string; name: string; description?: string }>;
  settings_and_memories?: Array<{
    id: string;
    name: string;
    description?: string;
  }>;
}

interface AppsListResponse {
  apps?: AppMetadata[];
}

function printAppsList(data: AppsListResponse): void {
  const apps =
    data?.apps ?? (Array.isArray(data) ? (data as AppMetadata[]) : []);
  if (apps.length === 0) {
    console.log("No apps available.");
    return;
  }
  header(`Apps  (${apps.length})\n`);
  for (const app of apps) {
    const skillCount = app.skills?.length ?? 0;
    process.stdout.write(
      `\x1b[1m${app.name ?? app.id}\x1b[0m  \x1b[2m${app.id}\x1b[0m  ` +
        `\x1b[2m${skillCount} skill${skillCount !== 1 ? "s" : ""}\x1b[0m\n`,
    );
    if (app.description) {
      process.stdout.write(`  \x1b[2m${app.description}\x1b[0m\n`);
    }
    if (app.skills && app.skills.length > 0) {
      for (const skill of app.skills) {
        process.stdout.write(
          `    \x1b[36m${app.id} ${skill.id}\x1b[0m` +
            (skill.name !== skill.id ? `  \x1b[2m${skill.name}\x1b[0m` : "") +
            "\n",
        );
      }
    }
    console.log();
  }
  console.log(
    `\x1b[2mRun: openmates apps <app-id> <skill-id> "<query>"\x1b[0m`,
  );
}

function printAppInfo(data: AppMetadata): void {
  header(`${data.name ?? data.id}  \x1b[2m(${data.id})\x1b[0m`);
  if (data.description) {
    console.log(`\n${data.description}\n`);
  } else {
    console.log();
  }

  const skills = data.skills ?? [];
  if (skills.length > 0) {
    process.stdout.write(`\x1b[1mSkills\x1b[0m\n`);
    for (const skill of skills) {
      process.stdout.write(
        `  \x1b[36m${skill.id}\x1b[0m  ${skill.name ?? skill.id}\n`,
      );
      if (skill.description) {
        process.stdout.write(`    \x1b[2m${skill.description}\x1b[0m\n`);
      }
      const providers = skill.providers ?? [];
      if (providers.length > 0) {
        const names = providers.map((p) => p.name ?? p.provider).join(", ");
        process.stdout.write(`    \x1b[2mProviders: ${names}\x1b[0m\n`);
      }
    }
    console.log();
  }

  const focuses = data.focus_modes ?? [];
  if (focuses.length > 0) {
    process.stdout.write(`\x1b[1mFocus modes\x1b[0m\n`);
    for (const f of focuses) {
      process.stdout.write(`  \x1b[36m${f.id}\x1b[0m  ${f.name}\n`);
      if (f.description) {
        process.stdout.write(`    \x1b[2m${f.description}\x1b[0m\n`);
      }
    }
    console.log();
  }

  console.log(
    `\x1b[2mRun: openmates apps ${data.id} <skill-id> "<query>"\x1b[0m`,
  );
}

function printSkillInfo(appId: string, data: SkillMetadata): void {
  header(`${data.name ?? data.id}  \x1b[2m(${appId}/${data.id})\x1b[0m`);
  if (data.description) {
    console.log(`\n${data.description}\n`);
  } else {
    console.log();
  }

  const providers = data.providers ?? [];
  if (providers.length > 0) {
    process.stdout.write(`\x1b[1mProviders\x1b[0m\n`);
    for (const p of providers) {
      process.stdout.write(
        `  \x1b[36m${p.provider}\x1b[0m  ${p.name ?? p.provider}\n`,
      );
      if (p.description) {
        process.stdout.write(`    \x1b[2m${p.description}\x1b[0m\n`);
      }
      if (p.pricing) {
        process.stdout.write(
          `    \x1b[2mPricing: ${JSON.stringify(p.pricing)}\x1b[0m\n`,
        );
      }
    }
    console.log();
  }

  console.log(
    `\x1b[2mRun: openmates apps ${appId} ${data.id} "<query>"\x1b[0m`,
  );
}

/**
 * Smart skill result renderer.
 * Handles the common { success, data, credits_charged } envelope and extracts
 * the inner content into a readable format.  Falls back to a generic key-value
 * display for shapes it doesn't recognise.
 */
function printSkillResult(app: string, skill: string, raw: unknown): void {
  const res = raw as Record<string, unknown>;

  // Top-level error
  if (res.success === false) {
    console.error(
      `\x1b[31m✗ Skill failed:\x1b[0m ${res.error ?? "unknown error"}`,
    );
    return;
  }

  const data = (res.data ?? res) as Record<string, unknown>;
  const credits =
    typeof res.credits_charged === "number" ? res.credits_charged : null;

  // ── Web / news search-style: { results: [{ results: [...] }] } ──────────
  type SearchItem = Record<string, unknown>;
  const topResults = data?.results as SearchItem[] | undefined;
  if (Array.isArray(topResults)) {
    let totalItems = 0;
    const lines: string[] = [];

    for (const group of topResults) {
      const items = group.results as SearchItem[] | undefined;
      if (!Array.isArray(items)) continue;
      for (const item of items) {
        totalItems += 1;
        const title = str(item.title) ?? str(item.name) ?? str(item.headline);
        const url = str(item.url) ?? str(item.link);
        const desc =
          str(item.description) ?? str(item.snippet) ?? str(item.summary);

        if (title) lines.push(`\x1b[1m${title}\x1b[0m`);
        if (url) lines.push(`\x1b[2m${url}\x1b[0m`);
        if (desc) lines.push(desc);
        lines.push("");
      }
    }

    if (totalItems > 0) {
      header(
        `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${totalItems} results${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
      );
      for (const l of lines) console.log(l);
      return;
    }
  }

  // ── Flat array of items (e.g. shopping results) ──────────────────────────
  if (Array.isArray(data)) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${(data as unknown[]).length} items${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
    );
    for (const item of data as SearchItem[]) {
      const title = str(item.title) ?? str(item.name);
      const url = str(item.url) ?? str(item.link);
      const desc = str(item.description) ?? str(item.snippet);
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) process.stdout.write(`\x1b[2m${url}\x1b[0m\n`);
      if (desc) process.stdout.write(`${desc}\n`);
      console.log();
    }
    return;
  }

  // ── AI / text response ───────────────────────────────────────────────────
  const content =
    str(data?.content) ??
    str(data?.text) ??
    str(data?.answer) ??
    str(data?.message) ??
    str(data?.response) ??
    str(data?.output);
  if (content) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
    );
    console.log(content);
    return;
  }

  // ── Generic fallback ─────────────────────────────────────────────────────
  header(
    `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
  );
  printGenericObject(data);
}

// ---------------------------------------------------------------------------
// Settings / generic renderers
// ---------------------------------------------------------------------------

function printWhoAmI(user: Record<string, unknown>): void {
  header("Account\n");
  const show = (k: string, label?: string) => {
    const v = user[k];
    if (v !== undefined && v !== null && v !== "") kv(label ?? k, String(v));
  };
  show("username", "Username");
  show("id", "User ID");
  show("is_admin", "Admin");
  show("credits", "Credits");
  show("language", "Language");
  show("subscription_status", "Subscription");
  // Any remaining keys
  const shown = new Set([
    "username",
    "id",
    "is_admin",
    "credits",
    "language",
    "subscription_status",
  ]);
  for (const [k, v] of Object.entries(user)) {
    if (!shown.has(k) && v !== null && v !== undefined && v !== "") {
      kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    }
  }
}

function printGenericObject(value: unknown): void {
  if (value === null || value === undefined) {
    console.log("(empty)");
    return;
  }
  if (typeof value === "string") {
    console.log(value);
    return;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      console.log("(empty list)");
      return;
    }
    for (const item of value) {
      if (item && typeof item === "object") {
        printGenericObject(item);
        hr();
      } else {
        console.log(String(item));
      }
    }
    return;
  }
  if (typeof value === "object") {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (v !== null && v !== undefined) {
        kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
      }
    }
    return;
  }
  console.log(String(value));
}

function printMemoriesList(
  memories: Array<{
    id: string;
    app_id: string;
    item_type: string;
    item_version: number;
    updated_at: number;
    data: Record<string, unknown>;
  }>,
): void {
  if (memories.length === 0) {
    console.log("No memories found.");
    return;
  }
  header(`Memories  (${memories.length})\n`);
  for (const mem of memories) {
    const ts = formatTimestamp(mem.updated_at);
    process.stdout.write(
      `\x1b[1m${mem.app_id}/${mem.item_type}\x1b[0m  \x1b[2mv${mem.item_version}  ${ts}  id:${mem.id.slice(0, 8)}\x1b[0m\n`,
    );
    // Show top-level data fields (skip internal _ fields)
    for (const [k, v] of Object.entries(mem.data)) {
      if (!k.startsWith("_") && v !== null && v !== undefined) {
        kv(k, String(v), 20);
      }
    }
    console.log();
  }
}

function printMemoryTypes(
  types: Array<{
    key: string;
    app_id: string;
    item_type: string;
    entry_type: string;
    required: string[];
    properties: string[];
  }>,
): void {
  if (types.length === 0) {
    console.log("No memory types found.");
    return;
  }
  header(`Memory types  (${types.length})\n`);
  let lastApp = "";
  for (const t of types) {
    if (t.app_id !== lastApp) {
      if (lastApp !== "") console.log();
      process.stdout.write(`\x1b[1m${t.app_id}\x1b[0m\n`);
      lastApp = t.app_id;
    }
    process.stdout.write(
      `  \x1b[36m${t.item_type}\x1b[0m  \x1b[2m${t.entry_type}\x1b[0m\n`,
    );
    kv("required", t.required.join(", ") || "none", 12);
    kv("fields", t.properties.join(", "), 12);
  }
  console.log();
  console.log(
    `\x1b[2mCreate: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\x1b[0m`,
  );
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function str(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Help text
// ---------------------------------------------------------------------------

function printHelp(): void {
  console.log(`OpenMates CLI

Commands:
  openmates login                            Pair-auth login
  openmates logout                           Log out and clear session
  openmates whoami [--json]                  Show account info
  openmates chats [--help]                   Chat commands (list, search, show, ...)
  openmates apps [--help]                    App skill commands (list, run, ...)
  openmates embeds [--help]                  Embed commands (show)
  openmates settings [--help]                Settings & memories

Flags:
  --json          Output raw JSON instead of formatted output
  --api-url <url> Override API base URL (default: https://api.openmates.org)
  --api-key <key> Optional API key override (or set OPENMATES_API_KEY)
  --help          Show contextual help for any command`);
}

function printChatsHelp(): void {
  console.log(`Chats commands:
  openmates chats list [--limit <n>] [--page <n>] [--json]
  openmates chats show <chat-id> [--json]
  openmates chats search <query> [--json]
  openmates chats new <message> [--json]
  openmates chats send [--chat <id>] [--incognito] <message> [--json]
  openmates chats incognito <message> [--json]
  openmates chats incognito-history [--json]
  openmates chats incognito-clear

Options for 'list':
  --limit <n>   Number of chats per page (default: 10)
  --page <n>    Page number (default: 1)

'show' displays the full decrypted conversation for a chat.
The chat ID can be the full UUID or just the first 8 characters.

Examples:
  openmates chats list
  openmates chats show d262cb68
  openmates chats search "Madrid"
  openmates chats new "Hello, what can you help me with?"`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list [--json]
  openmates apps <app-id> [--json]                    App info
  openmates apps info <app-id> [--json]               App info (explicit)
  openmates apps skill-info <app-id> <skill-id> [--json]
  openmates apps <app-id> <skill-id> "<query>" [--json]
  openmates apps <app-id> <skill-id> --input '<json>' [--json]

Authentication:
  Uses your logged-in session (run 'openmates login' first).
  Optionally: --api-key <key> or set OPENMATES_API_KEY.

Examples:
  openmates apps list
  openmates apps web
  openmates apps web search "latest AI news"
  openmates apps news search "climate change"
  openmates apps ai ask "Summarise this: ..."
  openmates apps skill-info web search`);
}

function printEmbedsHelp(): void {
  console.log(`Embeds commands:
  openmates embeds show <embed-id> [--json]

'show' displays the full decrypted content of an embed.
The embed ID can be the full UUID or just the first 8 characters.
Embed IDs are shown when viewing chat conversations (openmates chats show).

Examples:
  openmates embeds show a3f2b1c4`);
}

function printSettingsHelp(): void {
  console.log(`Settings commands:
  openmates settings get <path> [--json]
  openmates settings post <path> --data '<json>' [--json]
  openmates settings delete <path> [--json]
  openmates settings patch <path> --data '<json>' [--json]
  openmates settings memories <list|types|create|update|delete>

Blocked for safety (never executed from CLI):
  - API key creation
  - Password setup/update
  - 2FA setup/provider changes`);
}

function printMemoriesHelp(): void {
  console.log(`Memories commands:
  openmates settings memories list [--app-id <id>] [--item-type <type>] [--json]
  openmates settings memories types [--app-id <id>] [--json]
  openmates settings memories create --app-id <id> --item-type <type> --data '<json>'
  openmates settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]
  openmates settings memories delete --id <entry-id>

Examples:
  openmates settings memories types --app-id code
  openmates settings memories list --app-id code
  openmates settings memories create --app-id code --item-type preferred_tech --data '{"name":"Python","proficiency":"advanced"}'
  openmates settings memories delete --id <uuid>`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
