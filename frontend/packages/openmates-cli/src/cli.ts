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

import { OpenMatesClient, MEMORY_TYPE_REGISTRY } from "./client.js";

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
    const chats = await client.listChats();
    printOutput(chats, flags.json === true);
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
// Apps
// ---------------------------------------------------------------------------

async function handleApps(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  const apiKey = resolveApiKey(flags);

  if (!subcommand || subcommand === "help") {
    printAppsHelp();
    return;
  }

  if (subcommand === "list") {
    if (!apiKey)
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
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
      throw new Error(
        "Usage: openmates apps skill-info <app-id> <skill-id> --api-key <key>",
      );
    if (!apiKey)
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
    const skill = await client.getSkillInfo(appId, skillId, apiKey);
    printOutput(skill, flags.json === true);
    return;
  }

  if (subcommand === "run") {
    if (!apiKey)
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
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
    if (!apiKey)
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
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
  --api-key <key> API key for apps commands (or set OPENMATES_API_KEY env var)
  --help          Show this help`);
}

function printChatsHelp(): void {
  console.log(`Chats commands:
  openmates chats list [--json]
  openmates chats search <query> [--json]
  openmates chats new <message> [--json]
  openmates chats send [--chat <id>] [--incognito] <message> [--json]
  openmates chats incognito <message> [--json]
  openmates chats incognito-history [--json]
  openmates chats incognito-clear`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list --api-key <key> [--json]
  openmates apps info <app-id> [--json]
  openmates apps skill-info <app-id> <skill-id> --api-key <key> [--json]
  openmates apps run <app> <skill> --input '<json>' --api-key <key> [--json]
  openmates apps <app> <skill> [text] --api-key <key> [--input '<json>'] [--json]

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
