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

  if (!command || command === "help" || parsed.flags.help === true) {
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
    printOutput(user, parsed.flags.json === true);
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
  if (!subcommand || subcommand === "help") {
    printChatsHelp();
    return;
  }

  if (subcommand === "list") {
    const limit =
      typeof flags.limit === "string" ? parseInt(flags.limit, 10) : 10;
    const page = typeof flags.page === "string" ? parseInt(flags.page, 10) : 1;
    const result = await client.listChats(limit, page);
    if (flags.json === true) {
      printOutput(result, true);
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
    printOutput(result, flags.json === true);
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
    printOutput(
      { chat_id: result.chatId, assistant: result.assistant },
      flags.json === true,
    );
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
    printOutput(
      { chat_id: result.chatId, assistant: result.assistant },
      flags.json === true,
    );
    return;
  }

  if (subcommand === "incognito") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    const result = await client.sendMessage({ message, incognito: true });
    printOutput(
      { chat_id: result.chatId, assistant: result.assistant },
      flags.json === true,
    );
    return;
  }

  if (subcommand === "incognito-history") {
    printOutput(client.getIncognitoHistory(), flags.json === true);
    return;
  }

  if (subcommand === "incognito-clear") {
    client.clearIncognitoHistory();
    console.log("Incognito history cleared.");
    return;
  }

  throw new Error(`Unknown chats subcommand '${subcommand}'.`);
}

// ---------------------------------------------------------------------------
// Chats table display
// ---------------------------------------------------------------------------

/**
 * ANSI 24-bit color escape sequences — rendered in most modern terminals.
 * We use the start color of each category's gradient (from categoryUtils.ts)
 * as the background for the colored category pill.
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

    process.stdout.write(
      `${pill}  ${title}  ${idStr}  \x1b[2m${time}\x1b[0m\n`,
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

  if (!subcommand || subcommand === "help") {
    printAppsHelp();
    return;
  }

  if (subcommand === "list") {
    const apps = await client.listApps(apiKey);
    printOutput(apps, flags.json === true);
    return;
  }

  if (subcommand === "info") {
    const appId = rest[0];
    if (!appId) throw new Error("Usage: openmates apps info <app-id>");
    const app = await client.getApp(appId);
    printOutput(app, flags.json === true);
    return;
  }

  if (subcommand === "skill-info") {
    const [appId, skillId] = rest;
    if (!appId || !skillId)
      throw new Error("Usage: openmates apps skill-info <app-id> <skill-id>");
    const skill = await client.getSkillInfo(appId, skillId, apiKey);
    printOutput(skill, flags.json === true);
    return;
  }

  if (subcommand === "run") {
    const [app, skill] = rest;
    if (!app || !skill)
      throw new Error(
        "Usage: openmates apps run <app> <skill> --input '<json>'",
      );
    const inputRaw = typeof flags.input === "string" ? flags.input : "{}";
    const inputData = JSON.parse(inputRaw) as Record<string, unknown>;
    const result = await client.runSkill({ app, skill, inputData, apiKey });
    printOutput(result, flags.json === true);
    return;
  }

  // Sugar aliases: openmates apps <app> <skill> [text]
  const app = subcommand;
  const skill = rest[0];
  if (app && skill) {
    let inputData: Record<string, unknown> = {};
    const explicitInput = typeof flags.input === "string" ? flags.input : null;
    if (explicitInput) {
      inputData = JSON.parse(explicitInput);
    } else {
      const inlineText = rest.slice(1).join(" ").trim();
      if (inlineText) inputData = { requests: [{ query: inlineText }] };
    }
    const result = await client.runSkill({ app, skill, inputData, apiKey });
    printOutput(result, flags.json === true);
    return;
  }

  throw new Error(`Unknown apps subcommand '${subcommand}'.`);
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
  if (!subcommand || subcommand === "help") {
    printSettingsHelp();
    return;
  }

  if (subcommand === "get") {
    const path = rest[0];
    if (!path) throw new Error("Usage: openmates settings get <path>");
    const result = await client.settingsGet(path);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "post") {
    const path = rest[0];
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    if (!path)
      throw new Error("Usage: openmates settings post <path> --data '<json>'");
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPost(path, data);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "delete") {
    const path = rest[0];
    if (!path) throw new Error("Usage: openmates settings delete <path>");
    const result = await client.settingsDelete(path);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "patch") {
    const path = rest[0];
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    if (!path)
      throw new Error("Usage: openmates settings patch <path> --data '<json>'");
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPatch(path, data);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "memories") {
    await handleMemories(client, rest, flags);
    return;
  }

  throw new Error(`Unknown settings subcommand '${subcommand}'.`);
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
    printOutput(result, flags.json === true);
    return;
  }

  if (action === "types") {
    // List all available memory types and their required fields
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
    printOutput(filtered, flags.json === true);
    return;
  }

  if (action === "create") {
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : "";
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : "";
    const dataRaw = typeof flags.data === "string" ? flags.data : null;

    if (!appId || !itemType) {
      throw new Error(
        "Usage: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\n\n" +
          "Run 'openmates settings memories types' to see all available types.",
      );
    }
    if (!dataRaw) {
      throw new Error(
        "Missing --data '<json>'. Provide the memory field values as a JSON object.\n\n" +
          `Example: --data '{"name":"Python","proficiency":"advanced"}'`,
      );
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.createMemory({ appId, itemType, itemValue });
    printOutput(result, flags.json === true);
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
      throw new Error(
        "Usage: openmates settings memories update --id <entry-id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]",
      );
    }
    if (!dataRaw) {
      throw new Error("Missing --data '<json>'.");
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.updateMemory({
      entryId,
      appId,
      itemType,
      itemValue,
      currentVersion,
    });
    printOutput(result, flags.json === true);
    return;
  }

  if (action === "delete") {
    const entryId = typeof flags.id === "string" ? flags.id : (rest[1] ?? "");
    if (!entryId) {
      throw new Error(
        "Usage: openmates settings memories delete --id <entry-id>",
      );
    }
    const result = await client.deleteMemory(entryId);
    printOutput(result, flags.json === true);
    return;
  }

  throw new Error(
    `Unknown memories action '${action}'. Usage: openmates settings memories <list|types|create|update|delete>`,
  );
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

function printOutput(value: unknown, asJson: boolean): void {
  if (asJson) {
    console.log(JSON.stringify(value, null, 2));
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      console.log(typeof item === "string" ? item : JSON.stringify(item));
    }
    return;
  }
  if (value && typeof value === "object") {
    console.log(JSON.stringify(value, null, 2));
    return;
  }
  console.log(String(value));
}

// ---------------------------------------------------------------------------
// Help text
// ---------------------------------------------------------------------------

function printHelp(): void {
  console.log(`OpenMates CLI

Commands:
  openmates login
  openmates logout
  openmates whoami [--json]
  openmates chats <list|search|new|send|incognito|incognito-history|incognito-clear>
  openmates apps <list|info|skill-info|run|<app> <skill>>
  openmates settings <get|post|delete|patch|memories>

Flags:
  --json          Output as JSON
  --api-url <url> Override API base URL (default: https://api.openmates.org)
  --api-key <key> Optional API key override for apps commands (or set OPENMATES_API_KEY)
  --help          Show this help`);
}

function printChatsHelp(): void {
  console.log(`Chats commands:
  openmates chats list [--limit <n>] [--page <n>] [--json]
  openmates chats search <query> [--json]
  openmates chats new <message> [--json]
  openmates chats send [--chat <id>] [--incognito] <message> [--json]
  openmates chats incognito <message> [--json]
  openmates chats incognito-history [--json]
  openmates chats incognito-clear

Options for 'list':
  --limit <n>   Number of chats to show (default: 10)
  --page <n>    Page number for pagination (default: 1)
  --json        Output raw JSON instead of the formatted table`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list [--json]
  openmates apps info <app-id> [--json]
  openmates apps skill-info <app-id> <skill-id> [--json]
  openmates apps run <app> <skill> --input '<json>' [--json]
  openmates apps <app> <skill> [text] [--input '<json>'] [--json]

Authentication:
  Uses your logged-in session by default (run 'openmates login' first).
  Alternatively, pass --api-key <key> or set OPENMATES_API_KEY.

Examples:
  openmates apps list
  openmates apps info ai
  openmates apps skill-info ai ask
  openmates apps ai ask "What is Docker?"`);
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
  openmates settings memories create --app-id <id> --item-type <type> --data '<json>' [--json]
  openmates settings memories update --id <entry-id> --app-id <id> --item-type <type> --data '<json>' [--version <n>] [--json]
  openmates settings memories delete --id <entry-id> [--json]

Examples:
  openmates settings memories types --app-id code
  openmates settings memories list --app-id code --json
  openmates settings memories create --app-id code --item-type preferred_tech --data '{"name":"Python","proficiency":"advanced"}'
  openmates settings memories delete --id <uuid>`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
