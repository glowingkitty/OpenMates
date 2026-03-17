#!/usr/bin/env node
/*
 * OpenMates CLI command entry.
 *
 * Purpose: provide pair-auth login, chat, app, and settings commands.
 * Architecture: argument router over the OpenMatesClient SDK.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: login never prompts for account credentials, only pair PIN.
 * Tests: validated by package-level node tests and manual smoke checks.
 */

import { OpenMatesClient } from "./client.js";

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
    if (!query) {
      throw new Error(
        "Missing search query. Usage: openmates chats search <query>",
      );
    }
    const result = await client.searchChats(query);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "new") {
    const message = rest.join(" ").trim();
    if (!message) {
      throw new Error(
        "Missing message text. Usage: openmates chats new <message>",
      );
    }
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
    if (!message) {
      throw new Error(
        "Missing message text. Usage: openmates chats send [--chat <id>] <message>",
      );
    }
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
    if (!message) {
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    }
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
    if (!apiKey) {
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
    }
    const apps = await client.listApps(apiKey);
    printOutput(apps, flags.json === true);
    return;
  }

  if (subcommand === "run") {
    if (!apiKey) {
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
    }
    const [app, skill] = rest;
    if (!app || !skill) {
      throw new Error(
        "Usage: openmates apps run <app> <skill> --input '<json>'",
      );
    }
    const inputRaw = typeof flags.input === "string" ? flags.input : "{}";
    const inputData = JSON.parse(inputRaw) as Record<string, unknown>;
    const result = await client.runSkill({ app, skill, inputData, apiKey });
    printOutput(result, flags.json === true);
    return;
  }

  // Sugar aliases: openmates apps <app> <skill> ...
  const app = subcommand;
  const skill = rest[0];
  if (app && skill) {
    if (!apiKey) {
      throw new Error(
        "Missing API key. Set OPENMATES_API_KEY or pass --api-key.",
      );
    }
    let inputData: Record<string, unknown> = {};
    const explicitInput = typeof flags.input === "string" ? flags.input : null;
    if (explicitInput) {
      inputData = JSON.parse(explicitInput);
    } else {
      const inlineText = rest.slice(1).join(" ").trim();
      if (inlineText) {
        inputData = { requests: [{ query: inlineText }] };
      }
    }
    const result = await client.runSkill({ app, skill, inputData, apiKey });
    printOutput(result, flags.json === true);
    return;
  }

  throw new Error(`Unknown apps subcommand '${subcommand}'.`);
}

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
    if (!path) {
      throw new Error("Usage: openmates settings get <path>");
    }
    const result = await client.settingsGet(path);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "post") {
    const path = rest[0];
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    if (!path) {
      throw new Error("Usage: openmates settings post <path> --data '<json>'");
    }
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPost(path, data);
    printOutput(result, flags.json === true);
    return;
  }

  if (subcommand === "memories") {
    const action = rest[0];
    if (action === "list") {
      const result = await client.listMemories();
      printOutput(result, flags.json === true);
      return;
    }
    if (action === "create") {
      const appId = String(flags["app-id"] ?? "");
      const itemKey = String(flags["item-key"] ?? "");
      const itemType = String(flags["item-type"] ?? "");
      const content = String(flags.content ?? "");
      if (!appId || !itemKey || !itemType || !content) {
        throw new Error(
          "Usage: openmates settings memories create --app-id <id> --item-key <key> --item-type <type> --content <text>",
        );
      }
      const result = await client.createMemory({
        appId,
        itemKey,
        itemType,
        content,
      });
      printOutput(result, flags.json === true);
      return;
    }
    throw new Error("Usage: openmates settings memories <list|create>");
  }

  throw new Error(`Unknown settings subcommand '${subcommand}'.`);
}

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
  if (process.env.OPENMATES_API_KEY) {
    return process.env.OPENMATES_API_KEY;
  }
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

function printHelp(): void {
  console.log(
    `OpenMates CLI\n\nCommands:\n  openmates login\n  openmates logout\n  openmates whoami\n  openmates chats <list|search|new|send|incognito|incognito-history|incognito-clear>\n  openmates apps <list|run|<app> <skill>>\n  openmates settings <get|post|memories>\n\nFlags:\n  --json\n  --api-url <url>\n  --help`,
  );
}

function printChatsHelp(): void {
  console.log(
    `Chats commands:\n  openmates chats list [--json]\n  openmates chats search <query> [--json]\n  openmates chats new <message> [--json]\n  openmates chats send [--chat <id>] [--incognito] <message> [--json]\n  openmates chats incognito <message> [--json]\n  openmates chats incognito-history [--json]\n  openmates chats incognito-clear`,
  );
}

function printAppsHelp(): void {
  console.log(
    `Apps commands:\n  openmates apps list --api-key <key> [--json]\n  openmates apps run <app> <skill> --input '<json>' --api-key <key> [--json]\n  openmates apps <app> <skill> [text] --api-key <key> [--input '<json>'] [--json]`,
  );
}

function printSettingsHelp(): void {
  console.log(
    `Settings commands:\n  openmates settings get <path> [--json]\n  openmates settings post <path> --data '<json>' [--json]\n  openmates settings memories list [--json]\n  openmates settings memories create --app-id <id> --item-key <key> --item-type <type> --content <text> [--json]\n\nBlocked for safety:\n  - API key creation\n  - Password setup/update\n  - 2FA setup provider changes`,
  );
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
