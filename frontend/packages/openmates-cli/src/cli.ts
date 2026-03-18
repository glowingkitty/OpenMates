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
  MATE_NAMES,
  deriveAppUrl,
  type ChatListPage,
  type DecryptedMessage,
  type DecryptedEmbed,
} from "./client.js";
import type { StreamEvent } from "./ws.js";
import { renderEmbedPreview, renderEmbedFullscreen } from "./embedRenderers.js";

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
      printSettingsHelp(client);
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
    const result = await sendMessageStreaming(client, {
      message,
      chatId: undefined,
      incognito: false,
      json: flags.json === true,
    });
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "send") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats send [--chat <id>] <message>",
      );
    const chatId = typeof flags.chat === "string" ? flags.chat : undefined;
    const result = await sendMessageStreaming(client, {
      message,
      chatId,
      incognito: flags.incognito === true,
      json: flags.json === true,
    });
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "incognito") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    const result = await sendMessageStreaming(client, {
      message,
      incognito: true,
      json: flags.json === true,
    });
    if (flags.json === true) printJson(result);
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
    // "last" opens the most recently modified chat
    const resolvedId = chatId.toLowerCase() === "last" ? "__last__" : chatId;
    const { chat, messages } = await client.getChatMessages(resolvedId);
    if (flags.json === true) {
      printJson({ chat, messages });
    } else {
      await printChatConversation(client, chat, messages);
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

  if (!subcommand || subcommand === "help") {
    printAppsHelp();
    return;
  }

  // `apps <app> --help` → show app info
  // `apps <app> <skill> --help` → show skill info
  if (
    flags.help === true &&
    subcommand !== "list" &&
    subcommand !== "info" &&
    subcommand !== "skill-info" &&
    subcommand !== "run"
  ) {
    const potentialApp = subcommand;
    const potentialSkill = rest[0];
    if (potentialSkill) {
      // `apps <app> <skill> --help` → skill-level help
      const data = await client.getSkillInfo(
        potentialApp,
        potentialSkill,
        apiKey,
      );
      await printSkillInfo(client, potentialApp, data as SkillMetadata);
    } else {
      const data = await client.getApp(potentialApp);
      await printAppInfo(client, data as AppMetadata);
    }
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
      await printAppInfo(client, data as AppMetadata);
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
      await printSkillInfo(client, appId, data as SkillMetadata);
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
    const inlineTokens = rest.slice(1);
    const hasExplicitInput = typeof flags.input === "string";

    // Fetch schema once — used for both empty-args detection and multi-param validation.
    let schemaParams: Array<{
      name: string;
      type: string;
      description: string;
      required: boolean;
      default?: unknown;
    }> = [];
    try {
      schemaParams = await client.getSkillSchema(app, skill);
    } catch {
      // Schema unavailable — proceed with best-effort execution
    }

    // No args, no --input, and the skill has required params →
    // show skill help instead of sending an empty/partial request that 422s.
    if (!hasExplicitInput && inlineTokens.length === 0) {
      const required = schemaParams.filter((p) => p.required);
      if (required.length > 0) {
        const data = await client.getSkillInfo(app, skill, apiKey);
        await printSkillInfo(client, app, data as SkillMetadata);
        return;
      }
    }

    // Multiple required params but user provided only inline text →
    // enforce --input with a helpful example.
    if (
      !hasExplicitInput &&
      inlineTokens.length > 0 &&
      schemaParams.length > 0
    ) {
      const required = schemaParams.filter((p) => p.required);
      if (required.length > 1) {
        const example: Record<string, unknown> = {};
        for (const p of required) example[p.name] = `<${p.name}>`;
        console.error(
          `This skill requires ${required.length} fields: ${required.map((p) => p.name).join(", ")}\n\n` +
            `Use --input to provide all fields:\n` +
            `  openmates apps ${app} ${skill} --input '{"requests": [${JSON.stringify(example)}]}'\n\n` +
            `Run with --help for full parameter details:\n` +
            `  openmates apps ${app} ${skill} --help\n`,
        );
        process.exit(1);
      }
    }

    const inputData = buildSkillInput(flags, inlineTokens);
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
      await printAppInfo(client, data as AppMetadata);
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
      await renderEmbedFullscreen(embed, client);
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
    printSettingsHelp(client);
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

  // Gift card subcommands
  if (subcommand === "gift-card") {
    const action = rest[0];
    if (action === "redeem") {
      const code = rest[1];
      if (!code) {
        console.error("Missing gift card code.\n");
        console.log("Usage: openmates settings gift-card redeem <CODE>");
        process.exit(1);
      }
      const result = await client.redeemGiftCard(code);
      if (flags.json === true) {
        printJson(result);
      } else {
        if (result.success) {
          process.stdout.write(
            `\x1b[32m✓\x1b[0m Gift card redeemed! +${result.credits_added} credits\n`,
          );
          process.stdout.write(
            `  Balance: ${result.current_credits} credits\n`,
          );
        } else {
          process.stdout.write(`\x1b[31m✗\x1b[0m ${result.message}\n`);
        }
      }
      return;
    }
    if (action === "list") {
      const result = await client.listRedeemedGiftCards();
      if (flags.json === true) {
        printJson(result);
      } else {
        printGenericObject(result);
      }
      return;
    }
    console.log(`Gift card commands:
  openmates settings gift-card redeem <CODE>    Redeem a gift card
  openmates settings gift-card list             List redeemed gift cards`);
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

/**
 * Solid 2-character colored square block — no text, pure color signal.
 * Used as a category indicator in list and conversation views.
 */
function ansiColorBlock(category: string | null): string {
  if (!category || !CATEGORY_ANSI_COLORS[category]) {
    return "\x1b[2m░░\x1b[0m"; // dim placeholder for uncategorized
  }
  const [r, g, b] = CATEGORY_ANSI_COLORS[category];
  return `\x1b[48;2;${r};${g};${b}m  \x1b[0m`;
}

/**
 * Colored block with mate name as text — used in conversation per-message headers.
 */
function ansiMateBlock(
  category: string | null,
  mateName: string | null,
): string {
  const label =
    mateName ??
    (category ? (CATEGORY_LABELS[category] ?? category) : "Assistant");
  if (!category || !CATEGORY_ANSI_COLORS[category]) {
    return `\x1b[2m${label}\x1b[0m`;
  }
  const [r, g, b] = CATEGORY_ANSI_COLORS[category];
  return `\x1b[48;2;${r};${g};${b}m\x1b[97m ${label} \x1b[0m`;
}

/** Keep for backwards compat in non-list contexts */
function ansiCategoryPill(category: string | null): string {
  return ansiColorBlock(category);
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
  process.stdout.write(
    `\x1b[2mChats ${start}–${end} of ${total}  (page ${page}/${totalPages})\x1b[0m\n\n`,
  );

  for (const chat of chats) {
    const block = ansiColorBlock(chat.category);
    const time = formatTimestamp(chat.updatedAt);
    const title = chat.title ?? "(no title)";
    const idStr = chat.shortId;

    // Line 1: colored block + timestamp
    process.stdout.write(`${block}  \x1b[2m${time}\x1b[0m\n`);
    // Line 2: bold title as headline
    process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
    // Line 3: full summary (no truncation)
    if (chat.summary) {
      process.stdout.write(`\x1b[2m${chat.summary}\x1b[0m\n`);
    }
    // Line 4: show command hint
    process.stdout.write(`\x1b[2m→ openmates chats show ${idStr}\x1b[0m\n`);
    // Separator
    process.stdout.write(`\x1b[2m${"─".repeat(60)}\x1b[0m\n`);
  }

  if (hasMore) {
    const nextPage = page + 1;
    const nextCmd = `chats list --page ${nextPage}${limit !== 10 ? ` --limit ${limit}` : ""}`;
    process.stdout.write(`\n\x1b[2mNext page: openmates ${nextCmd}\x1b[0m\n`);
  }
}

/**
 * Send a message with live streaming output.
 *
 * Prints a typing indicator while waiting, streams content as it arrives
 * (diff-printing new characters), and renders inline embeds after completion.
 */
async function sendMessageStreaming(
  client: OpenMatesClient,
  params: {
    message: string;
    chatId?: string;
    incognito?: boolean;
    json?: boolean;
  },
): Promise<{
  chatId: string;
  assistant: string;
  category: string | null;
  modelName: string | null;
  mateName: string | null;
}> {
  let headerPrinted = false;
  let typingShown = false;
  // Track which embed IDs we've already rendered during streaming
  const renderedEmbedIds = new Set<string>();
  // Track how much raw content we've processed (for diff-printing)
  let processedRawLength = 0;
  // Queue of embed IDs to render after streaming, with optional meta
  // from the JSON block for fallback rendering of unsynced embeds
  const pendingEmbedRenders: Array<{
    id: string;
    meta?: Record<string, unknown>;
  }> = [];

  const clearTyping = () => {
    if (typingShown) {
      process.stdout.write("\r\x1b[K");
      typingShown = false;
    }
  };

  const onStream = (event: StreamEvent) => {
    if (params.json) return;

    if (event.kind === "typing") {
      const mateName =
        event.category && MATE_NAMES[event.category]
          ? MATE_NAMES[event.category]
          : "Mate";
      process.stdout.write(`\x1b[2m${mateName} is typing...\x1b[0m`);
      typingShown = true;
      return;
    }

    if (event.kind === "chunk" || event.kind === "done") {
      clearTyping();

      if (!headerPrinted) {
        const mateBlock = ansiMateBlock(event.category, null);
        const modelSuffix = event.modelName
          ? `  \x1b[2m${event.modelName}\x1b[0m`
          : "";
        process.stdout.write(`${SEP}\n`);
        process.stdout.write(`${mateBlock}${modelSuffix}\n`);
        process.stdout.write(`${SEP}\n`);
        headerPrinted = true;
      }

      // Process new content since last chunk using segment parsing.
      // This lets us detect embed JSON blocks as they arrive and queue
      // them for rendering at their natural position in the output.
      const raw = event.content;
      if (raw.length <= processedRawLength) return;

      // Parse the FULL content each time (embed blocks may span multiple
      // chunks), then output only the new segments we haven't printed yet.
      const segments = parseMessageSegments(raw);
      let offset = 0;
      for (const seg of segments) {
        const segEnd = offset + (seg.type === "embed" ? 0 : seg.value.length);
        if (seg.type === "embed") {
          if (!renderedEmbedIds.has(seg.value)) {
            renderedEmbedIds.add(seg.value);
            pendingEmbedRenders.push({ id: seg.value, meta: seg.meta });
          }
        } else {
          // Only print text we haven't printed yet
          const clean = seg.value.replace(/\n{3,}/g, "\n\n");
          const alreadyPrinted = Math.max(0, processedRawLength - offset);
          if (alreadyPrinted < clean.length) {
            process.stdout.write(clean.slice(alreadyPrinted));
          }
        }
        offset = segEnd;
      }
      processedRawLength = raw.length;
    }
  };

  const result = await client.sendMessage({
    message: params.message,
    chatId: params.chatId,
    incognito: params.incognito,
    onStream,
  });

  clearTyping();

  if (!params.json) {
    if (!headerPrinted) {
      const mateBlock = ansiMateBlock(result.category, result.mateName);
      const modelSuffix = result.modelName
        ? `  \x1b[2m${result.modelName}\x1b[0m`
        : "";
      process.stdout.write(`${SEP}\n`);
      process.stdout.write(`${mateBlock}${modelSuffix}\n`);
      process.stdout.write(`${SEP}\n`);
    }

    // Render all embeds that were queued during streaming.
    // They appear after the text for now — the AI writes embed JSON before
    // the prose, so they should have been queued first. We also render
    // any embeds from the final content that weren't seen during streaming.
    const finalSegments = parseMessageSegments(result.assistant);
    const streamed = processedRawLength > 0;

    if (!streamed) {
      // No streaming happened — render everything from final content
      for (const seg of finalSegments) {
        if (seg.type === "embed") {
          try {
            const embed = await client.getEmbed(seg.value);
            await renderEmbedPreview(embed, client);
          } catch {
            renderEmbedFromMeta(seg.value, seg.meta);
          }
        } else {
          const cleaned = seg.value.replace(/\n{3,}/g, "\n\n");
          if (cleaned.trim()) process.stdout.write(cleaned);
        }
      }
      process.stdout.write("\n");
    } else {
      // Streaming happened — render queued embeds + any new ones
      process.stdout.write("\n");
      for (const seg of finalSegments) {
        if (seg.type === "embed" && !renderedEmbedIds.has(seg.value)) {
          pendingEmbedRenders.push({ id: seg.value, meta: seg.meta });
          renderedEmbedIds.add(seg.value);
        }
      }
    }

    // Now render all queued embed previews
    for (const entry of pendingEmbedRenders) {
      try {
        const embed = await client.getEmbed(entry.id);
        await renderEmbedPreview(embed, client);
      } catch {
        renderEmbedFromMeta(entry.id, entry.meta);
      }
    }

    const shortId = result.chatId.slice(0, 8);
    process.stdout.write(`${SEP}\n`);
    process.stdout.write(
      `\x1b[2mContinue: openmates chats send --chat ${shortId} "your message"\x1b[0m\n` +
        `\x1b[2mHistory:  openmates chats show ${shortId}\x1b[0m\n`,
    );
  }

  return result;
}

/**
 * Strip ```json embed blocks from content for clean streaming output.
 * These are rendered separately after the response completes.
 * Also collapses multiple blank lines left after stripping.
 */
function stripEmbedJsonBlocks(content: string): string {
  return content
    .replace(/```(?:json_embed|json)\n[\s\S]*?\n```/g, "")
    .replace(/\n{3,}/g, "\n\n");
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

const SEP = `\x1b[2m${"─".repeat(60)}\x1b[0m`;

/**
 * Parse the inline embed UUID blocks from AI message content.
 *
 * The AI writes embed references as:
 *   ```json
 *   {"type":"app_skill_use","embed_id":"<uuid>","app_id":"...","skill_id":"...","query":"..."}
 *   ```
 * or the legacy:
 *   ```json_embed
 *   {"embed_id":"<uuid>"}
 *   ```
 *
 * Returns the content split into segments: either plain text segments or embed
 * UUID strings prefixed with "EMBED:" so the renderer can fetch them in-place.
 */
/** Parsed segment from AI message content. */
type MessageSegment =
  | { type: "text"; value: string }
  | { type: "embed"; value: string; meta?: Record<string, unknown> };

function parseMessageSegments(content: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  // Match both ```json and ```json_embed blocks
  const pattern = /```(?:json_embed|json)\n([\s\S]*?)\n```/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(content)) !== null) {
    // Text before this block
    if (m.index > last) {
      segments.push({ type: "text", value: content.slice(last, m.index) });
    }

    // Try to extract an embed_id from the JSON block.
    // Keep the full parsed JSON as `meta` so we can render a preview
    // even when the embed isn't in the local sync cache (failed/processing).
    try {
      const parsed = JSON.parse(m[1].trim()) as Record<string, unknown>;
      const embedId =
        typeof parsed.embed_id === "string" ? parsed.embed_id : null;
      if (embedId) {
        segments.push({ type: "embed", value: embedId, meta: parsed });
      }
    } catch {
      // Malformed JSON — discard
    }

    last = m.index + m[0].length;
  }

  // Remaining text after last block
  if (last < content.length) {
    segments.push({ type: "text", value: content.slice(last) });
  }

  return segments;
}

/**
 * Render an embed preview from the inline JSON metadata when the embed
 * is not found in the sync cache (failed, processing, or not yet synced).
 */
function renderEmbedFromMeta(
  embedId: string,
  meta?: Record<string, unknown>,
): void {
  const shortId = embedId.slice(0, 8);
  if (!meta) {
    process.stdout.write(
      `\x1b[2m┌─\x1b[0m \x1b[33m⟳\x1b[0m \x1b[1membed\x1b[0m  \x1b[33mProcessing...\x1b[0m\n`,
    );
    process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
    return;
  }

  const app = typeof meta.app_id === "string" ? meta.app_id : "";
  const skill = typeof meta.skill_id === "string" ? meta.skill_id : "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const query = typeof meta.query === "string" ? `  · "${meta.query}"` : "";
  const provider =
    typeof meta.provider === "string" ? `  via ${meta.provider}` : "";

  // Mark as Processing (not in cache = not finished)
  process.stdout.write(
    `\x1b[2m┌─\x1b[0m \x1b[33m⟳\x1b[0m \x1b[1m${label}\x1b[0m${query}\x1b[2m${provider}\x1b[0m  \x1b[33mProcessing...\x1b[0m\n`,
  );
  process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
}

/**
 * Clean display text: strip unresolvable embed badge refs.
 *
 * - `[!](embed:slug)`  → "" (large preview badge — already shown as embed block above)
 * - `[text](embed:slug)` → "text" (inline text badge — keep the display text only)
 */
function cleanMessageText(text: string): string {
  return text
    .replace(/\[!\]\(embed:[^)]+\)/g, "") // [!](embed:...) → remove
    .replace(/\[([^\]]+)\]\(embed:[^)]+\)/g, "$1") // [text](embed:...) → text
    .replace(/\n{3,}/g, "\n\n") // collapse 3+ blank lines
    .trim();
}

/**
 * Render a full chat conversation with messages, colored mate blocks, and inline embed content.
 *
 * Layout per message:
 *   ────────────────────────
 *    You   2026-03-16 18:17   (or mate block for assistant)
 *   ────────────────────────
 *   message text
 *   [embed blocks inline at their json block positions]
 *
 * After last message:
 *   ────────────────────────
 */
async function printChatConversation(
  client: OpenMatesClient,
  chat: {
    id: string;
    shortId: string;
    title: string | null;
    category: string | null;
    mateName: string | null;
    updatedAt: number | null;
  },
  messages: DecryptedMessage[],
): Promise<void> {
  const block = ansiColorBlock(chat.category);
  const title = chat.title ?? "(no title)";
  const ts = formatTimestamp(chat.updatedAt);

  // Header: colored block + date + # Title
  process.stdout.write(`${block}  \x1b[2m${chat.shortId}  ${ts}\x1b[0m\n`);
  process.stdout.write(`\x1b[1;4m# ${title}\x1b[0m\n\n`);

  if (messages.length === 0) {
    process.stdout.write("\x1b[2m(no messages)\x1b[0m\n");
    return;
  }

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const msgTs = formatTimestamp(msg.createdAt);

    // ── Separator + sender header ──────────────────────────────────────────
    process.stdout.write(`${SEP}\n`);

    if (msg.role === "user") {
      process.stdout.write(`\x1b[1mYou\x1b[0m  \x1b[2m${msgTs}\x1b[0m\n`);
    } else if (msg.role === "assistant" || msg.role === "ai") {
      const msgCategory = msg.category ?? chat.category;
      const msgMateName = msgCategory
        ? (MATE_NAMES[msgCategory] ?? chat.mateName)
        : chat.mateName;
      const mateBlock = ansiMateBlock(msgCategory, msgMateName);
      const modelSuffix = msg.modelName
        ? `  \x1b[2m${msg.modelName}\x1b[0m`
        : "";
      process.stdout.write(
        `${mateBlock}${modelSuffix}  \x1b[2m${msgTs}\x1b[0m\n`,
      );
    } else {
      process.stdout.write(`\x1b[2m${msg.role}  ${msgTs}\x1b[0m\n`);
    }

    process.stdout.write(`${SEP}\n`);

    // ── Message body: text + inline embeds at their actual positions ───────
    if (msg.content) {
      const segments = parseMessageSegments(msg.content);

      for (const seg of segments) {
        if (seg.type === "embed") {
          try {
            const embed = await client.getEmbed(seg.value);
            await renderEmbedPreview(embed, client);
          } catch {
            // Embed not in cache — render from inline JSON metadata if available.
            // This handles embeds that failed/are processing and weren't synced.
            renderEmbedFromMeta(seg.value, seg.meta);
          }
        } else {
          const cleaned = cleanMessageText(seg.value);
          if (cleaned) process.stdout.write(`${cleaned}\n`);
        }
      }
    }

    // NOTE: Skill embeds (web/search, events/search, etc.) are associated
    // with the user's message via hashed_message_id, but they are rendered
    // inline in the assistant's message where the AI placed the ```json
    // embed reference. We do NOT render msg.embedIds here — that caused
    // the duplicate embed display bug. User-attached files (images, PDFs)
    // are embedded in the user message content itself as json blocks.
  }

  // Final closing separator
  process.stdout.write(`${SEP}\n`);
  process.stdout.write(
    `\x1b[2mContinue: openmates chats send --chat ${chat.shortId} "your message"\x1b[0m\n`,
  );
}

// Legacy renderInlineEmbed and printEmbedDetail removed — replaced by
// renderEmbedPreview() and renderEmbedFullscreen() in embedRenderers.ts.

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

async function printAppInfo(
  client: OpenMatesClient,
  data: AppMetadata,
): Promise<void> {
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
      // Show required input parameters inline (compact) — use --help for full detail
      const params = await client
        .getSkillSchema(data.id, skill.id)
        .catch(() => []);
      const required = params.filter((p) => p.required);
      if (required.length > 0) {
        // Show name + a short type hint (strip "array of {...}" to just "array")
        const reqStr = required
          .map((p) => {
            const shortType = p.type.startsWith("array of") ? "array" : p.type;
            return `${p.name} \x1b[2m(${shortType})\x1b[0m`;
          })
          .join("  ");
        process.stdout.write(`    \x1b[2mRequired:\x1b[0m ${reqStr}\n`);
        process.stdout.write(
          `    \x1b[2mopenmates apps ${data.id} ${skill.id} --help  for details\x1b[0m\n`,
        );
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
  console.log(
    `\x1b[2mDetails: openmates apps skill-info ${data.id} <skill-id>\x1b[0m`,
  );
}

async function printSkillInfo(
  client: OpenMatesClient,
  appId: string,
  data: SkillMetadata,
): Promise<void> {
  header(`${data.name ?? data.id}  \x1b[2m(${appId}/${data.id})\x1b[0m`);
  if (data.description) {
    console.log(`\n${data.description}\n`);
  } else {
    console.log();
  }

  // Providers
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
        const pr = p.pricing as Record<string, unknown>;
        const perReq = pr.per_request_credits ?? pr.credits;
        if (perReq !== undefined)
          process.stdout.write(
            `    \x1b[2m${perReq} credits per request\x1b[0m\n`,
          );
      }
    }
    console.log();
  }

  // Fetch input parameter schema from OpenAPI spec
  const params = await client.getSkillSchema(appId, data.id).catch(() => []);
  const requiredParams = params.filter((p) => p.required);
  const optionalParams = params.filter((p) => !p.required);

  if (params.length > 0) {
    // ── Required parameters ──────────────────────────────────────────────
    if (requiredParams.length > 0) {
      process.stdout.write(`\x1b[1mRequired parameters\x1b[0m\n`);
      for (const p of requiredParams) {
        process.stdout.write(
          `  \x1b[33m*\x1b[0m \x1b[1m${p.name}\x1b[0m  \x1b[2m(${p.type})\x1b[0m\n`,
        );
        if (p.description) {
          // Wrap long descriptions at ~72 chars
          const lines = wrapText(p.description, 68);
          for (const l of lines)
            process.stdout.write(`      \x1b[2m${l}\x1b[0m\n`);
        }
      }
      console.log();
    }

    // ── Optional parameters ──────────────────────────────────────────────
    if (optionalParams.length > 0) {
      process.stdout.write(`\x1b[1mOptional parameters\x1b[0m\n`);
      for (const p of optionalParams) {
        const defStr =
          p.default !== undefined && p.default !== null
            ? `  \x1b[2m[default: ${JSON.stringify(p.default)}]\x1b[0m`
            : "";
        process.stdout.write(
          `    \x1b[36m${p.name}\x1b[0m  \x1b[2m(${p.type})\x1b[0m${defStr}\n`,
        );
        if (p.description) {
          const lines = wrapText(p.description, 68);
          for (const l of lines)
            process.stdout.write(`      \x1b[2m${l}\x1b[0m\n`);
        }
      }
      console.log();
    }

    // ── Example --input JSON ─────────────────────────────────────────────
    // Build a minimal example showing required fields + first 2 optional
    const exampleItem: Record<string, unknown> = {};
    for (const p of requiredParams) {
      exampleItem[p.name] = buildExampleValue(p.name, p.type, p.description);
    }
    // Show up to 2 optional params to give context
    for (const p of optionalParams.slice(0, 2)) {
      exampleItem[p.name] =
        p.default ?? buildExampleValue(p.name, p.type, p.description);
    }
    process.stdout.write(`\x1b[1mExample\x1b[0m\n`);
    const exampleJson = JSON.stringify({ requests: [exampleItem] }, null, 2)
      .split("\n")
      .map((l) => `  ${l}`)
      .join("\n");
    process.stdout.write(
      `  \x1b[2mopenmates apps ${appId} ${data.id} --input '\x1b[0m\n`,
    );
    process.stdout.write(`${exampleJson}\n`);
    process.stdout.write(`  \x1b[2m'\x1b[0m\n`);
    console.log();
  } else {
    // Skill takes no input — simple invocation
    console.log(`\x1b[2mRun: openmates apps ${appId} ${data.id}\x1b[0m`);
  }
}

/** Wrap text at `width` chars, preserving existing sentence structure. */
function wrapText(text: string, width: number): string[] {
  const words = text.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const w of words) {
    if (current.length + w.length + 1 > width && current.length > 0) {
      lines.push(current);
      current = w;
    } else {
      current = current.length > 0 ? `${current} ${w}` : w;
    }
  }
  if (current.length > 0) lines.push(current);
  return lines;
}

/** Build a placeholder example value for a param based on name/type/description. */
function buildExampleValue(
  name: string,
  type: string,
  description: string,
): unknown {
  // Common patterns
  if (name === "query" || name.endsWith("_query")) return "Berlin AI meetups";
  if (name === "location") return "Berlin, Germany";
  if (name === "url") return "https://example.com";
  if (name === "date" || name.includes("_date")) return "2026-04-15";
  if (name === "check_in_date") return "2026-04-15";
  if (name === "check_out_date") return "2026-04-18";
  if (name === "legs") {
    return [{ origin: "BER", destination: "LHR", date: "2026-04-15" }];
  }
  if (type.startsWith("array")) {
    // Try to infer item structure from description
    if (
      description.toLowerCase().includes("origin") &&
      description.toLowerCase().includes("destination")
    ) {
      return [
        {
          origin: "<IATA>",
          destination: "<IATA>",
          date: "YYYY-MM-DD",
        },
      ];
    }
    return ["<value>"];
  }
  if (type === "integer" || type === "number") return 1;
  if (type === "boolean") return false;
  return `<${name}>`;
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

        // ── Type-specific renderers ──────────────────────────────────────
        const itemType = str(item.type);

        if (itemType === "connection") {
          // Travel flight/train connection result
          const origin = str(item.origin);
          const dest = str(item.destination);
          const dep = str(item.departure);
          const arr = str(item.arrival);
          const dur = str(item.duration);
          const price = str(item.total_price);
          const currency = str(item.currency) ?? "EUR";
          const stops = item.stops as number | undefined;
          const carriers = Array.isArray(item.carriers)
            ? (item.carriers as string[]).join(", ")
            : null;
          const stopsLabel =
            stops === 0 ? "direct" : stops === 1 ? "1 stop" : `${stops} stops`;

          if (origin && dest) lines.push(`\x1b[1m${origin} → ${dest}\x1b[0m`);
          const meta: string[] = [];
          if (dep) meta.push(dep);
          if (arr) meta.push(`→ ${arr}`);
          if (dur) meta.push(`(${dur})`);
          if (meta.length) lines.push(meta.join("  "));
          const detail: string[] = [];
          if (price) detail.push(`${price} ${currency}`);
          if (stops !== undefined) detail.push(stopsLabel);
          if (carriers) detail.push(carriers);
          if (detail.length) lines.push(`\x1b[2m${detail.join(" · ")}\x1b[0m`);
          lines.push("");
          continue;
        }

        if (itemType === "stay") {
          // Travel hotel/accommodation result
          const name = str(item.name) ?? str(item.property_name);
          const addr = str(item.address) ?? str(item.location);
          const price =
            str(item.price_per_night) ??
            str(item.price) ??
            str(item.rate_per_night);
          const currency = str(item.currency) ?? "EUR";
          const rating = item.rating ?? item.overall_rating;
          const stars = item.hotel_class ?? item.stars;
          const link = str(item.link) ?? str(item.url);

          if (name) lines.push(`\x1b[1m${name}\x1b[0m`);
          const meta: string[] = [];
          if (rating) meta.push(`★ ${rating}`);
          if (stars) meta.push(`${stars}★ hotel`);
          if (price) meta.push(`${price} ${currency}/night`);
          if (meta.length) lines.push(meta.join("  "));
          if (addr) lines.push(`\x1b[2m${addr}\x1b[0m`);
          if (link) lines.push(`\x1b[2m${link}\x1b[0m`);
          lines.push("");
          continue;
        }

        if (itemType === "place") {
          // Maps place result
          const name = str(item.name);
          const addr =
            str(item.formatted_address) ??
            str(item.address) ??
            str(item.vicinity);
          const rating = item.rating;
          const phone = str(item.phone) ?? str(item.formatted_phone_number);
          const website = str(item.website) ?? str(item.url);

          if (name) lines.push(`\x1b[1m${name}\x1b[0m`);
          const meta: string[] = [];
          if (rating) meta.push(`★ ${rating}`);
          if (meta.length) lines.push(meta.join("  "));
          if (addr) lines.push(`\x1b[2m${addr}\x1b[0m`);
          if (phone) lines.push(`\x1b[2m${phone}\x1b[0m`);
          if (website) lines.push(`\x1b[2m${website}\x1b[0m`);
          lines.push("");
          continue;
        }

        // ── Generic fallback (web/news search, events, images, etc.) ────
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

/**
 * Human-readable structured output for any API response.
 * Arrays of objects are printed as separated blocks.
 * Nested objects are recursively formatted with indentation.
 * Known response types (billing, invoices) get specialized formatting.
 */
function printGenericObject(value: unknown, indent = 0): void {
  const pad = "  ".repeat(indent);
  if (value === null || value === undefined) {
    console.log(`${pad}(empty)`);
    return;
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    console.log(`${pad}${value}`);
    return;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      console.log(`${pad}(empty list)`);
      return;
    }
    for (let i = 0; i < value.length; i++) {
      const item = value[i];
      if (item && typeof item === "object") {
        printGenericObject(item, indent);
        if (i < value.length - 1) {
          process.stdout.write(`${pad}\x1b[2m${"─".repeat(40)}\x1b[0m\n`);
        }
      } else {
        console.log(`${pad}${String(item)}`);
      }
    }
    return;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;

    // ── Billing response: specialized formatting ──
    if ("payment_tier" in obj && "invoices" in obj) {
      printBillingResponse(obj);
      return;
    }

    for (const [k, v] of Object.entries(obj)) {
      if (v === null || v === undefined) continue;
      if (Array.isArray(v)) {
        if (v.length === 0) {
          process.stdout.write(
            `${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m (none)\n`,
          );
        } else if (v.length > 0 && typeof v[0] === "object") {
          process.stdout.write(
            `\n${pad}  \x1b[1m${k}\x1b[0m  \x1b[2m(${v.length})\x1b[0m\n`,
          );
          printGenericObject(v, indent + 1);
        } else {
          process.stdout.write(
            `${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m ${v.join(", ")}\n`,
          );
        }
      } else if (typeof v === "object") {
        process.stdout.write(`${pad}  \x1b[1m${k}\x1b[0m\n`);
        printGenericObject(v, indent + 1);
      } else {
        process.stdout.write(`${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m ${v}\n`);
      }
    }
    return;
  }
  console.log(`${pad}${String(value)}`);
}

/** Specialized billing overview renderer */
function printBillingResponse(obj: Record<string, unknown>): void {
  header("Billing\n");
  const credits = obj.credits ?? obj.current_credits;
  if (credits !== undefined) kv("Credits", String(credits));
  if (obj.payment_tier !== undefined)
    kv("Payment tier", String(obj.payment_tier));

  // Auto top-up
  const atEnabled = obj.auto_topup_enabled;
  if (atEnabled !== undefined) {
    kv("Auto top-up", atEnabled ? "enabled" : "disabled");
    if (atEnabled) {
      if (obj.auto_topup_threshold !== undefined)
        kv("  Threshold", `${obj.auto_topup_threshold} credits`);
      if (obj.auto_topup_amount !== undefined)
        kv("  Amount", `${obj.auto_topup_amount} credits`);
      if (obj.auto_topup_currency !== undefined)
        kv("  Currency", String(obj.auto_topup_currency).toUpperCase());
    }
  }

  // Invoices
  const invoices = obj.invoices as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(invoices) && invoices.length > 0) {
    process.stdout.write(
      `\n  \x1b[1mInvoices\x1b[0m  \x1b[2m(${invoices.length})\x1b[0m\n\n`,
    );
    for (const inv of invoices) {
      const date = str(inv.date) ?? "—";
      const amt = str(inv.amount) ?? "—";
      const creditsP = inv.credits_purchased ?? "—";
      const refund = str(inv.refund_status);
      const refundTag =
        refund && refund !== "none" ? `  \x1b[33m[${refund}]\x1b[0m` : "";
      const giftTag = inv.is_gift_card ? "  \x1b[35m[gift card]\x1b[0m" : "";
      process.stdout.write(
        `    ${date}  \x1b[2m€${amt}\x1b[0m  ${creditsP} credits${refundTag}${giftTag}\n`,
      );
    }
  }

  // Print remaining unknown keys
  const shown = new Set([
    "credits",
    "current_credits",
    "payment_tier",
    "auto_topup_enabled",
    "auto_topup_threshold",
    "auto_topup_amount",
    "auto_topup_currency",
    "invoices",
  ]);
  for (const [k, v] of Object.entries(obj)) {
    if (!shown.has(k) && v !== null && v !== undefined) {
      kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    }
  }
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

'show' accepts: full UUID, 8-char short ID, exact/partial title, or "last".

Examples:
  openmates chats list
  openmates chats show d262cb68
  openmates chats show last
  openmates chats show "Flight Connections Berlin to Bangkok"
  openmates chats search "Madrid"
  openmates chats new "Hello, what can you help me with?"
  openmates chats send --chat d262cb68 "follow-up question"`);
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

function printSettingsHelp(client?: OpenMatesClient): void {
  const appUrl = client ? deriveAppUrl(client.apiUrl) : "https://openmates.org";
  const s = (path: string) => `${appUrl}/#settings/${path}`;

  // Section heading helper
  const h = (title: string) => `\n  \x1b[1m${title}\x1b[0m`;

  console.log(`\x1b[1mSettings\x1b[0m
${h("Account")}
    openmates settings post user/username --data '{"encrypted_username":"..."}'
    openmates settings post user/timezone --data '{"timezone":"Europe/Berlin"}'
    openmates settings get export-account-manifest      GDPR data export manifest
    openmates settings get export-account-data          GDPR data export
    openmates settings post import-chat --data '<json>' Import a chat
    openmates settings get storage [--json]             Storage overview
    openmates settings get chats [--json]               Chat statistics
    openmates settings get delete-account-preview       Preview account deletion
    \x1b[2mSecurity (passkeys, password, 2FA, sessions): ${s("account/security")}\x1b[0m
    \x1b[2mDelete account: ${s("account/delete")}\x1b[0m
${h("Billing")}
    openmates settings get billing [--json]             Balance & billing overview
    openmates settings post auto-topup/low-balance --data '{"enabled":true,"amount":1000,"currency":"eur"}'
    openmates settings get usage [--json]               Full usage history
    openmates settings get usage/summaries [--json]     Usage summaries by type
    openmates settings get usage/daily-overview [--json]
    openmates settings get usage/export [--json]        Export usage as CSV
    openmates settings gift-card redeem <CODE>          Redeem a gift card
    openmates settings gift-card list                   List redeemed gift cards
    \x1b[2mBuy credits: ${s("billing/buy-credits")}\x1b[0m
    \x1b[2mMonthly auto top-up: ${s("billing/auto-topup/monthly")}\x1b[0m
    \x1b[2mInvoices: ${s("billing/invoices")}\x1b[0m
    \x1b[2mGift cards (buy/manage): ${s("billing/gift-cards")}\x1b[0m
${h("Privacy")}
    openmates settings post auto-delete-chats --data '{"period":"90d"}'
    openmates settings post auto-delete-usage --data '{"period":"1y"}'
    \x1b[2mHide personal data / anonymization: ${s("privacy/hide-personal-data")}\x1b[0m
${h("Notifications")}
    openmates settings get reminders [--json]           Active reminders
    \x1b[2mChat notifications: ${s("notifications/chat")}\x1b[0m
    \x1b[2mBackup reminders: ${s("notifications/backup")}\x1b[0m
${h("Interface")}
    openmates settings post user/language --data '{"language":"en"}'
    openmates settings post user/darkmode --data '{"dark_mode":true}'
    openmates settings post ai-model-defaults --data '{"simple":"...","complex":"..."}'
${h("App Store")}
    openmates apps list                                 Same as App Store
    openmates apps <app-id>                             App details
    \x1b[2mWeb: ${s("app_store")}\x1b[0m
${h("Mates")}
    \x1b[2m${s("mates")}\x1b[0m
${h("Memories & app settings")}
    openmates settings memories list [--app-id <id>] [--item-type <type>] [--json]
    openmates settings memories types [--app-id <id>] [--json]
    openmates settings memories create --app-id <id> --item-type <type> --data '<json>'
    openmates settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>'
    openmates settings memories delete --id <entry-id>
${h("Developers")}
    openmates settings get api-keys [--json]            List API keys
    openmates settings delete api-keys/<key-id>         Revoke API key
    \x1b[2mCreate API key (shows secret once): ${s("developers/api-keys")}\x1b[0m
    \x1b[2mManage devices: ${s("developers/devices")}\x1b[0m
${h("Support")}
    openmates settings post issues --data '<json>'      Report an issue

\x1b[2mWeb app only (security — manage in browser):\x1b[0m
  \x1b[2mPasskeys:   ${s("account/security/passkeys")}\x1b[0m
  \x1b[2mPassword:   ${s("account/security/password")}\x1b[0m
  \x1b[2m2FA:        ${s("account/security/2fa")}\x1b[0m
  \x1b[2mSessions:   ${s("account/security/sessions")}\x1b[0m`);
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
