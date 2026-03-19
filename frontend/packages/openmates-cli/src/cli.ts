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
  type DailyInspiration,
} from "./client.js";
import type { StreamEvent } from "./ws.js";

import {
  parseMentions,
  listMentionOptions,
  type MentionContext,
  type MentionType,
} from "./mentions.js";
import { OutputRedactor } from "./outputRedactor.js";
import { processFiles, formatEmbedsForMessage } from "./fileEmbed.js";
import { encryptEmbed, type EncryptedEmbed } from "./embedCreator.js";
import type { ShareDuration } from "./shareEncryption.js";
import { uploadFile } from "./uploadService.js";
import { toonEncodeContent } from "./embedCreator.js";
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

  // Initialize output redactor with personal data entries from Settings & Memories.
  // This loads user-defined names, addresses, etc. for auto-censoring in terminal output.
  // Safe to call before login — silently skips if no session.
  const redactor = new OutputRedactor();
  if (client.hasSession()) {
    try {
      const memories = await client.listMemories();
      redactor.initializeFromMemories(memories);
    } catch {
      // Not logged in or decryption error — proceed without redaction
    }
  }

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
    if (command === "mentions") {
      printMentionsHelp();
      return;
    }
    if (command === "embeds") {
      printEmbedsHelp();
      return;
    }
    if (command === "inspirations") {
      printInspirationsHelp();
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
    await handleChats(client, subcommand, rest, parsed.flags, redactor);
    return;
  }

  if (command === "apps") {
    await handleApps(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "mentions") {
    await handleMentions(client, subcommand, rest, parsed.flags);
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

  if (command === "inspirations") {
    await handleInspirations(client, parsed.flags);
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
  redactor?: OutputRedactor,
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
    }, redactor);
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
    }, redactor);
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
    }, redactor);
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

  if (subcommand === "delete") {
    // Collect IDs from positional args
    const chatIds = rest.filter((arg) => arg.length > 0);
    if (chatIds.length === 0) {
      throw new Error(
        "Missing chat IDs. Usage: openmates chats delete <id1> [id2] [id3] ...",
      );
    }

    // Resolve short IDs so we can show titles for confirmation
    const resolved: Array<{ input: string; title: string | null }> = [];
    for (const id of chatIds) {
      try {
        const { chat } = await client.getChatMessages(id);
        resolved.push({ input: id, title: chat.title ?? null });
      } catch {
        resolved.push({ input: id, title: null });
      }
    }

    if (flags.yes !== true) {
      // Show what will be deleted and ask for confirmation
      process.stdout.write("\nChats to delete:\n");
      for (const r of resolved) {
        const label = r.title ? `"${r.title}"` : "(unable to resolve title)";
        process.stdout.write(`  \x1b[31m\u2717\x1b[0m ${r.input}  ${label}\n`);
      }
      process.stdout.write("\n");

      const rl = await import("node:readline");
      const iface = rl.createInterface({ input: process.stdin, output: process.stdout });
      const answer = await new Promise<string>((resolve) => {
        iface.question(
          `Delete ${resolved.length} chat(s)? This cannot be undone. [y/N] `,
          resolve,
        );
      });
      iface.close();

      if (answer.trim().toLowerCase() !== "y") {
        console.log("Aborted.");
        return;
      }
    }

    // Delete each chat
    let deleted = 0;
    for (const r of resolved) {
      try {
        await client.deleteChat(r.input);
        const label = r.title ? `"${r.title}"` : r.input;
        process.stdout.write(`  \x1b[32m\u2713\x1b[0m Deleted ${label}\n`);
        deleted++;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        process.stdout.write(`  \x1b[31m\u2717\x1b[0m Failed to delete ${r.input}: ${msg}\n`);
      }
    }
    console.log(`\n${deleted}/${resolved.length} chat(s) deleted.`);
    return;
  }

  if (subcommand === "share") {
    const id = rest[0] || "last";
    const durationSeconds = (
      typeof flags.expires === "string"
        ? parseInt(flags.expires, 10)
        : 0
    ) as ShareDuration;
    const password =
      typeof flags.password === "string" ? flags.password : undefined;

    if (password && password.length > 10) {
      console.error("Password must be at most 10 characters.");
      process.exit(1);
    }

    try {
      const url = await client.createChatShareLink(id, durationSeconds, password);
      if (flags.json === true) {
        printJson({ url, chat_id: id, expires: durationSeconds, password_protected: !!password });
      } else {
        process.stdout.write(`\n[1mChat share link[0m\n`);
        process.stdout.write(`${url}\n\n`);
        if (durationSeconds > 0) {
          process.stdout.write(`[2mExpires in ${humanizeDuration(durationSeconds)}[0m\n`);
        }
        if (password) {
          process.stdout.write(`[2mPassword protected[0m\n`);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`Share link error: ${msg}`);
      process.exit(1);
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

  // ── travel booking-link: resolve a booking URL from a booking_token ────
  // openmates apps travel booking-link --token "..." [--context '{...}']
  if (subcommand === "travel" && rest[0] === "booking-link") {
    const token =
      typeof flags.token === "string" ? flags.token : undefined;
    if (!token) {
      console.error(
        "Missing --token flag.\n\n" +
          "Usage:\n" +
          '  openmates apps travel booking-link --token "<booking_token>" [--context \'<json>\']\n\n' +
          "The booking_token is shown in the output of:\n" +
          "  openmates apps travel search_connections --input '...'\n",
      );
      process.exit(1);
    }
    let bookingContext: Record<string, string> | undefined;
    if (typeof flags.context === "string") {
      try {
        bookingContext = JSON.parse(flags.context) as Record<string, string>;
      } catch {
        console.error("Invalid --context JSON.");
        process.exit(1);
      }
    }
    try {
      const result = await client.getBookingLink({
        bookingToken: token,
        bookingContext,
        apiKey,
      });
      if (flags.json === true) {
        printJson(result);
      } else if (result.success && result.booking_url) {
        header(
          `Travel › Booking Link${result.credits_charged ? `  \x1b[2m(${result.credits_charged} credits)\x1b[0m` : ""}\n`,
        );
        kv("URL", result.booking_url);
        if (result.booking_provider) kv("Provider", result.booking_provider);
        console.log(
          `\n\x1b[2mOpen this URL in your browser to complete the booking.\x1b[0m`,
        );
      } else {
        console.error(
          `\x1b[31m✗ Booking link not found:\x1b[0m ${result.error ?? "no booking URL available for this flight"}`,
        );
        process.exit(1);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`\x1b[31m✗ Booking link request failed:\x1b[0m ${msg}`);
      process.exit(1);
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

  if (subcommand === "share") {
    const id = rest[0];
    if (!id) {
      console.error("Missing embed ID. Usage: openmates embeds share <embed-id>");
      process.exit(1);
    }
    const durationSeconds = (
      typeof flags.expires === "string"
        ? parseInt(flags.expires, 10)
        : 0
    ) as ShareDuration;
    const password =
      typeof flags.password === "string" ? flags.password : undefined;

    if (password && password.length > 10) {
      console.error("Password must be at most 10 characters.");
      process.exit(1);
    }

    try {
      const url = await client.createEmbedShareLink(id, durationSeconds, password);
      if (flags.json === true) {
        printJson({ url, embed_id: id, expires: durationSeconds, password_protected: !!password });
      } else {
        process.stdout.write(`\n[1mEmbed share link[0m\n`);
        process.stdout.write(`${url}\n\n`);
        if (durationSeconds > 0) {
          process.stdout.write(`[2mExpires in ${humanizeDuration(durationSeconds)}[0m\n`);
        }
        if (password) {
          process.stdout.write(`[2mPassword protected[0m\n`);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`Share link error: ${msg}`);
      process.exit(1);
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
  redactor?: OutputRedactor,
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
      // Each segment carries rawLength — the number of characters it
      // consumed in the original string (including ```json\n...\n```
      // delimiters for embed blocks). We track offset in raw-string
      // coordinates so that processedRawLength subtraction works correctly.
      const segments = parseMessageSegments(raw);
      let offset = 0;
      for (const seg of segments) {
        const segEnd = offset + seg.rawLength;
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
            const chunk = clean.slice(alreadyPrinted);
            // Redact personal data and secrets from streamed output
            const safeChunk = redactor?.isInitialized ? redactor.redact(chunk) : chunk;
            process.stdout.write(safeChunk);
          }
        }
        offset = segEnd;
      }
      processedRawLength = raw.length;
    }
  };

  // ── Encrypted embeds array (populated by file processing below) ────
  const encryptedEmbeds: EncryptedEmbed[] = [];

  // ── Mention resolution ─────────────────────────────────────────────
  // Parse @mentions in the message, resolve to backend wire syntax.
  // If any mentions fail to resolve, show error and abort.
  let finalMessage = params.message;
  if (params.message.includes("@")) {
    try {
      const mentionCtx = await client.buildMentionContext();
      const parsed = parseMentions(params.message, mentionCtx);

      // Report unresolved mentions as errors
      if (parsed.unresolved.length > 0) {
        clearTyping();
        for (const u of parsed.unresolved) {
          process.stderr.write(`\x1b[31mError:\x1b[0m Unknown mention ${u.original}\n`);
          if (u.suggestions.length > 0) {
            process.stderr.write(
              `  Did you mean: ${u.suggestions.join(", ")}?\n`,
            );
          }
        }
        process.stderr.write(
          "\nUse \x1b[2mopenmates mentions list\x1b[0m to see all available mentions.\n",
        );
        process.exit(1);
      }

      // Process file @path references into proper encrypted embeds
      if (parsed.filePaths.length > 0) {
        const fileResult = processFiles(parsed.filePaths, redactor ?? null);

        // Report blocked files
        for (const b of fileResult.blocked) {
          clearTyping();
          process.stderr.write(
            `\x1b[31mBlocked:\x1b[0m @${b.path} — ${b.error}\n`,
          );
        }

        // Report file errors
        for (const e of fileResult.errors) {
          clearTyping();
          process.stderr.write(
            `\x1b[31mError:\x1b[0m @${e.path} — ${e.error}\n`,
          );
        }

        // Abort if any blocked or errors
        if (fileResult.blocked.length > 0 || fileResult.errors.length > 0) {
          process.exit(1);
        }

        // Show processed files confirmation
        if (fileResult.embeds.length > 0 && !params.json) {
          clearTyping();
          for (const fe of fileResult.embeds) {
            const suffix = fe.zeroKnowledge
              ? " (zero-knowledge)"
              : fe.secretsRedacted
                ? " (secrets redacted)"
                : fe.requiresUpload
                  ? " (uploading...)"
                  : "";
            process.stderr.write(
              `\x1b[2m  \x1b[36m@${fe.displayName}\x1b[2m${suffix}\x1b[0m\n`,
            );
          }
        }

        // Upload files that require S3 upload (images, PDFs)
        for (const fe of fileResult.embeds) {
          if (fe.requiresUpload && fe.localPath) {
            try {
              const session = client.getSession();
              const uploadResult = await uploadFile(fe.localPath, session);

              // Update the embed with upload server response data
              fe.embed.content = toonEncodeContent({
                type: fe.embed.type === "pdf" ? "pdf" : "image",
                app_id: "images",
                skill_id: "upload",
                status: "finished",
                filename: fe.displayName,
                content_hash: uploadResult.content_hash,
                s3_base_url: uploadResult.s3_base_url,
                files: uploadResult.files,
                aes_key: uploadResult.aes_key,
                aes_nonce: uploadResult.aes_nonce,
                vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
                ai_detection: uploadResult.ai_detection,
              });
              fe.embed.status = fe.embed.type === "pdf" ? "processing" : "finished";
              fe.embed.contentHash = uploadResult.content_hash;

              // Use the server-assigned embed_id
              fe.embed.embedId = uploadResult.embed_id;

              if (!params.json) {
                process.stderr.write(
                  `\x1b[32m  \u2713\x1b[0m \x1b[2m${fe.displayName} uploaded\x1b[0m\n`,
                );
              }
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              process.stderr.write(
                `\x1b[31mUpload failed:\x1b[0m ${fe.displayName} — ${msg}\n`,
              );
              process.exit(1);
            }
          }
        }

        // Remove @path tokens from the message text
        for (const fp of parsed.filePaths) {
          finalMessage = finalMessage.replace(
            new RegExp(`@${fp.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}`, "g"),
            "",
          );
        }
        finalMessage = finalMessage.trim();

        // Append embed reference blocks to the message
        const embedRefs = formatEmbedsForMessage(fileResult.embeds);
        if (embedRefs) {
          finalMessage += embedRefs;
        }

        // Encrypt all embeds for the WebSocket payload
        try {
          const { masterKey, userId } = client.getEmbedEncryptionKeys();
          for (const fe of fileResult.embeds) {
            // Note: chatKey is null for new chats — server assigns it.
            // For existing chats, we'd need to fetch the chat key from cache.
            // For now, only master key wrapping is used (sufficient for owner access).
            const encrypted = await encryptEmbed(
              fe.embed,
              masterKey,
              null, // chatKey — not available in CLI yet for new chats
              params.chatId || "new", // will be replaced by server
              "pending", // messageId set during send
              userId,
            );
            if (encrypted) {
              encryptedEmbeds.push(encrypted);
            }
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          process.stderr.write(
            `\x1b[33mWarning:\x1b[0m Embed encryption failed: ${msg}. Files sent without encryption.\n`,
          );
        }
      }

      // Show resolved mentions as confirmation
      if (parsed.resolved.length > 0 && !params.json) {
        clearTyping();
        for (const r of parsed.resolved) {
          const typeLabel = r.type.replace("_", " ");
          process.stderr.write(
            `\x1b[2m  ${r.original} → ${r.displayName} (${typeLabel})\x1b[0m\n`,
          );
        }
      }

      finalMessage = parsed.processedMessage;
    } catch {
      // If mention resolution fails (e.g., network error), send as-is
      // The backend will receive the raw @tokens and ignore unknown ones
    }
  }

  const result = await client.sendMessage({
    message: finalMessage,
    chatId: params.chatId,
    incognito: params.incognito,
    onStream,
    encryptedEmbeds: encryptedEmbeds.length > 0 ? encryptedEmbeds : undefined,
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
/** Parsed segment from AI message content.
 * rawLength = number of characters this segment consumed in the original string.
 * For text segments, rawLength === value.length.
 * For embed segments, rawLength includes the full \`\`\`json\n...\n\`\`\` delimiters. */
type MessageSegment =
  | { type: "text"; value: string; rawLength: number }
  | { type: "embed"; value: string; meta?: Record<string, unknown>; rawLength: number };

function parseMessageSegments(content: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  // Match both ```json and ```json_embed blocks
  const pattern = /```(?:json_embed|json)\n([\s\S]*?)\n```/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(content)) !== null) {
    // Text before this block
    if (m.index > last) {
      const text = content.slice(last, m.index);
      segments.push({ type: "text", value: text, rawLength: text.length });
    }

    // Try to extract an embed_id from the JSON block.
    // Keep the full parsed JSON as `meta` so we can render a preview
    // even when the embed isn't in the local sync cache (failed/processing).
    // rawLength = length of the entire ```json\n...\n``` block in the original string.
    const blockRawLength = m[0].length;
    try {
      const parsed = JSON.parse(m[1].trim()) as Record<string, unknown>;
      const embedId =
        typeof parsed.embed_id === "string" ? parsed.embed_id : null;
      if (embedId) {
        segments.push({ type: "embed", value: embedId, meta: parsed, rawLength: blockRawLength });
      }
    } catch {
      // Malformed JSON — discard
    }

    last = m.index + m[0].length;
  }

  // Remaining text after last block
  if (last < content.length) {
    const text = content.slice(last);
    segments.push({ type: "text", value: text, rawLength: text.length });
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

  // ── Grouped results: { results: [{ id, results: [...] }] } ──────────────
  // This is the standard shape for all skill responses with request arrays.
  type ResultItem = Record<string, unknown>;
  const topResults = data?.results as ResultItem[] | undefined;
  if (Array.isArray(topResults)) {
    let totalItems = 0;
    for (const group of topResults) {
      const items = group.results as ResultItem[] | undefined;
      if (Array.isArray(items)) totalItems += items.length;
    }
    if (totalItems > 0) {
      header(
        `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${totalItems} result${totalItems !== 1 ? "s" : ""}${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
      );
      let resultNum = 0;
      for (const group of topResults) {
        const items = group.results as ResultItem[] | undefined;
        if (!Array.isArray(items)) continue;
        for (const item of items) {
          resultNum += 1;
          printSkillResultItem(item, resultNum, totalItems);
        }
      }

      // ── Provider info ──────────────────────────────────────────────────
      const provider = str(data.provider);
      if (provider) {
        console.log(`\x1b[2mProvider: ${provider}\x1b[0m`);
      }

      // ── Follow-up suggestions ──────────────────────────────────────────
      const suggestions = data.suggestions_follow_up_requests;
      if (Array.isArray(suggestions) && suggestions.length > 0) {
        console.log(
          `\x1b[2mSuggestions: ${(suggestions as string[]).join(" · ")}\x1b[0m`,
        );
      }
      return;
    }
  }

  // ── AI / text response ───────────────────────────────────────────────────
  const textContent =
    str(data?.content) ??
    str(data?.text) ??
    str(data?.answer) ??
    str(data?.message) ??
    str(data?.response) ??
    str(data?.output);
  if (textContent) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
    );
    console.log(textContent);
    return;
  }

  // ── Generic fallback ─────────────────────────────────────────────────────
  header(
    `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
  );
  printGenericObject(data);
}

/**
 * Print a single skill result item with a numbered header line and full details.
 *
 * For known types (connection, stay, place_result) a compact human-readable
 * header line is printed first, followed by all remaining fields.
 * For unknown types, printGenericObject renders every field.
 *
 * This ensures the CLI always shows the full REST API output — nothing is
 * hidden or summarised away.
 */
function printSkillResultItem(
  item: Record<string, unknown>,
  num: number,
  total: number,
): void {
  const itemType = str(item.type);
  const numLabel = total > 1 ? `\x1b[36m[${num}]\x1b[0m ` : "";

  // ── Connection (travel flights/trains) ─────────────────────────────────
  if (itemType === "connection") {
    const origin = str(item.origin) ?? "?";
    const dest = str(item.destination) ?? "?";
    const dep = str(item.departure) ?? "";
    const arr = str(item.arrival) ?? "";
    const dur = str(item.duration) ?? "";
    const price = str(item.total_price);
    const currency = str(item.currency) ?? "EUR";
    const stops = typeof item.stops === "number" ? item.stops : undefined;
    const carriers = Array.isArray(item.carriers)
      ? (item.carriers as string[]).join(", ")
      : null;
    const stopsLabel =
      stops === 0 ? "direct" : stops === 1 ? "1 stop" : `${stops} stops`;

    // Header: [N] BER → LHR  54 EUR · direct · Eurowings
    const summary: string[] = [];
    if (price) summary.push(`${price} ${currency}`);
    if (stops !== undefined) summary.push(stopsLabel);
    if (carriers) summary.push(carriers);
    console.log(
      `${numLabel}\x1b[1m${origin} → ${dest}\x1b[0m  ${summary.join(" · ")}`,
    );
    // Sub-line: departure → arrival (duration)
    if (dep || arr || dur) {
      const parts: string[] = [];
      if (dep) parts.push(dep);
      if (arr) parts.push(`→ ${arr}`);
      if (dur) parts.push(`(${dur})`);
      console.log(`  ${parts.join("  ")}`);
    }
    // Full details — all remaining fields
    printGenericObject(item, 1);
    // Booking link hint
    if (typeof item.booking_token === "string") {
      const token = item.booking_token as string;
      const ctxFlag =
        item.booking_context && typeof item.booking_context === "object"
          ? ` --context '${JSON.stringify(item.booking_context)}'`
          : "";
      console.log(
        `\x1b[2m  → Get booking URL (25 credits):\x1b[0m`,
      );
      console.log(
        `\x1b[2m    openmates apps travel booking-link --token "${token}"${ctxFlag}\x1b[0m`,
      );
    }
    console.log("");
    return;
  }

  // ── Stay (travel hotels/accommodation) ─────────────────────────────────
  if (itemType === "stay") {
    const name = str(item.name) ?? str(item.property_name) ?? "Unknown";
    const rating = item.overall_rating ?? item.rating;
    const price =
      str(item.rate_per_night) ??
      str(item.price_per_night) ??
      str(item.price);
    const summary: string[] = [];
    if (rating) summary.push(`★ ${rating}`);
    if (price) summary.push(price);
    console.log(
      `${numLabel}\x1b[1m${name}\x1b[0m  ${summary.join(" · ")}`,
    );
    printGenericObject(item, 1);
    console.log("");
    return;
  }

  // ── Place result (maps) ────────────────────────────────────────────────
  if (itemType === "place_result") {
    const name = str(item.name) ?? str(item.displayName) ?? "Unknown";
    const rating = item.rating;
    const addr =
      str(item.formatted_address) ??
      str(item.address) ??
      str(item.vicinity);
    const summary: string[] = [];
    if (rating) summary.push(`★ ${rating}`);
    if (addr) summary.push(addr);
    console.log(
      `${numLabel}\x1b[1m${name}\x1b[0m  ${summary.join(" · ")}`,
    );
    printGenericObject(item, 1);
    console.log("");
    return;
  }

  // ── Generic item — just number + printGenericObject for all fields ─────
  // Works for web/news search results, events, shopping, health, etc.
  const title = str(item.title) ?? str(item.name) ?? str(item.headline);
  if (title) {
    console.log(`${numLabel}\x1b[1m${title}\x1b[0m`);
    printGenericObject(item, 1);
  } else {
    console.log(`${numLabel}Result ${num}`);
    printGenericObject(item, 1);
  }
  console.log("");
}

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
// Inspirations
// ---------------------------------------------------------------------------

/**
 * Handle `openmates inspirations [--lang <code>] [--json]`.
 *
 * Fetches today's daily inspirations.
 * - Logged-in users: personalized encrypted inspirations decrypted locally.
 * - Not logged in: public defaults for the day (cleartext).
 */
async function handleInspirations(
  client: OpenMatesClient,
  flags: Record<string, string | boolean>,
): Promise<void> {
  const lang = typeof flags.lang === "string" ? flags.lang : "en";
  const inspirations = await client.getDailyInspirations(lang);

  if (flags.json === true) {
    printJson(inspirations);
    return;
  }

  if (inspirations.length === 0) {
    console.log("No inspirations available for today.");
    return;
  }

  const isLoggedIn = client.hasSession();
  const source = isLoggedIn ? "personalized" : "public";
  console.log(
    `[1mDaily Inspirations[0m  [2m(${source}${lang !== "en" ? `, ${lang}` : ""})[0m
`,
  );

  for (let i = 0; i < inspirations.length; i++) {
    printInspiration(inspirations[i], i + 1);
  }
}

/** Render a single inspiration to the terminal in human-readable form. */
function printInspiration(ins: DailyInspiration, index: number): void {
  const categoryLabel = ins.category ? ` [2m[${ins.category}][0m` : "";
  const openedBadge = ins.is_opened ? " [2m(opened)[0m" : "";
  console.log(`[1m${index}. ${ins.title || ins.phrase}[0m${categoryLabel}${openedBadge}`);
  if (ins.title && ins.phrase) {
    console.log(`   [3m${ins.phrase}[0m`);
  }
  if (ins.assistant_response) {
    // Wrap long responses at ~80 chars for terminal readability
    const lines = wrapText(ins.assistant_response, 78);
    for (const line of lines) console.log(`   ${line}`);
  }
  if (ins.video) {
    const v = ins.video;
    const duration = v.duration_seconds != null
      ? ` · ${formatDuration(v.duration_seconds)}`
      : "";
    const views = v.view_count != null
      ? ` · ${v.view_count.toLocaleString()} views`
      : "";
    const channel = v.channel_name ? ` · ${v.channel_name}` : "";
    console.log(
      `   [2mVideo: ${v.title || v.youtube_id}${channel}${duration}${views}[0m`,
    );
    if (v.youtube_id) {
      console.log(`   [2mhttps://www.youtube.com/watch?v=${v.youtube_id}[0m`);
    }
  }
  if (ins.follow_up_suggestions.length > 0) {
    console.log(
      `   [2mSuggestions: ${ins.follow_up_suggestions.join(" · ")}[0m`,
    );
  }
  console.log();
}

/** Format seconds into m:ss or h:mm:ss. */
function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Mentions
// ---------------------------------------------------------------------------

/**
 * Handle `openmates mentions` commands.
 * Lists available @mentions that can be used in chat messages.
 *
 * Mirrors: MentionDropdown.svelte (web app)
 */
async function handleMentions(
  client: OpenMatesClient,
  subcommand: string | undefined,
  _rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || subcommand === "list") {
    // Parse optional --type filter
    const typeFilter = typeof flags.type === "string"
      ? flags.type as MentionType
      : undefined;

    const validTypes = ["model", "model_alias", "mate", "skill", "focus_mode", "settings_memory"];
    if (typeFilter && !validTypes.includes(typeFilter)) {
      console.error(
        `Invalid type '${typeFilter}'. Valid types: ${validTypes.join(", ")}`,
      );
      process.exit(1);
    }

    const context = await client.buildMentionContext();
    const options = listMentionOptions(context, typeFilter);

    if (flags.json === true) {
      console.log(JSON.stringify(options, null, 2));
      return;
    }

    if (options.length === 0) {
      console.log("No mentions available" + (typeFilter ? ` for type '${typeFilter}'` : "") + ".");
      return;
    }

    // Group by type for readable output
    const grouped = new Map<string, typeof options>();
    for (const opt of options) {
      const group = grouped.get(opt.type) || [];
      group.push(opt);
      grouped.set(opt.type, group);
    }

    const typeLabels: Record<string, string> = {
      model_alias: "Model Aliases",
      model: "AI Models",
      mate: "Mates",
      skill: "Skills",
      focus_mode: "Focus Modes",
      settings_memory: "Settings & Memories",
    };

    for (const [type, items] of grouped) {
      const label = typeLabels[type] || type;
      process.stdout.write(`\n\x1b[1m${label}\x1b[0m\n`);
      for (const item of items) {
        process.stdout.write(
          `  \x1b[36m${item.displayName.padEnd(35)}\x1b[0m \x1b[2m${item.description}\x1b[0m\n`,
        );
      }
    }
    process.stdout.write("\n");
    return;
  }

  if (subcommand === "search") {
    const query = _rest.join(" ").trim();
    if (!query) {
      console.error("Missing search query. Usage: openmates mentions search <query>");
      process.exit(1);
    }

    const context = await client.buildMentionContext();
    const allOptions = listMentionOptions(context);

    // Fuzzy match against all options
    const normalizedQuery = query.toLowerCase().replace(/[\s_-]+/g, "");
    const matches = allOptions
      .filter((opt) => {
        const normalizedName = opt.displayName.toLowerCase().replace(/[@\s_-]+/g, "");
        const normalizedDesc = opt.description.toLowerCase().replace(/[\s_-]+/g, "");
        return (
          normalizedName.includes(normalizedQuery) ||
          normalizedDesc.includes(normalizedQuery)
        );
      })
      .slice(0, 15);

    if (flags.json === true) {
      console.log(JSON.stringify(matches, null, 2));
      return;
    }

    if (matches.length === 0) {
      console.log(`No mentions matching '${query}'.`);
      return;
    }

    process.stdout.write(`\n\x1b[1mMatches for '${query}':\x1b[0m\n`);
    for (const m of matches) {
      const typeLabel = m.type.replace("_", " ");
      process.stdout.write(
        `  \x1b[36m${m.displayName.padEnd(35)}\x1b[0m \x1b[2m${m.description} (${typeLabel})\x1b[0m\n`,
      );
    }
    process.stdout.write("\n");
    return;
  }

  console.error(`Unknown mentions subcommand '${subcommand}'.\n`);
  printMentionsHelp();
  process.exit(1);
}

// Help text
// ---------------------------------------------------------------------------

/** Format a share duration for display */
function humanizeDuration(seconds: number): string {
  if (seconds === 0) return "never";
  if (seconds < 3600) return `${Math.round(seconds / 60)} minute(s)`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hour(s)`;
  return `${Math.round(seconds / 86400)} day(s)`;
}

function printMentionsHelp(): void {
  console.log(`Mentions commands:
  openmates mentions list [--type <type>] [--json]
  openmates mentions search <query> [--json]

Types:
  model_alias       Model shortcuts (@Best, @Fast)
  model             AI models (@Claude-Opus-4.6, @GPT-5.4)
  mate              AI mates/personas (@Sophia, @Finn)
  skill             App skills (@Web-Search, @Code-Get-Docs)
  focus_mode        Focus modes (@Web-Research)
  settings_memory   Settings & memories (@Code-Projects)

Use @mentions in chat messages:
  openmates chats new "@Sophia tell me about React hooks"
  openmates chats send --chat abc "@best what's the weather?"
  openmates chats new "@Web-Search latest AI news"
  openmates chats new "@Code-Projects review my architecture"`);
}

function printHelp(): void {
  console.log(`OpenMates CLI

Commands:
  openmates login                            Pair-auth login
  openmates logout                           Log out and clear session
  openmates whoami [--json]                  Show account info
  openmates chats [--help]                   Chat commands (list, search, show, ...)
  openmates apps [--help]                    App skill commands (list, run, ...)
  openmates mentions [--help]                List available @mentions
  openmates embeds [--help]                  Embed commands (show)
  openmates settings [--help]                Settings & memories
  openmates inspirations [--lang <code>] [--json]   Daily inspirations

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
  openmates chats delete <id1> [id2] [id3] ... [--yes]
  openmates chats share [<chat-id>] [--expires <seconds>] [--password <pwd>] [--json]
  openmates chats incognito <message> [--json]
  openmates chats incognito-history [--json]
  openmates chats incognito-clear

Options for 'list':
  --limit <n>   Number of chats per page (default: 10)
  --page <n>    Page number (default: 1)

Options for 'delete':
  --yes         Skip confirmation prompt

'show' accepts: full UUID, 8-char short ID, exact/partial title, or "last".

@mentions:
  Use @mentions in messages to invoke models, mates, skills, or attach files:
  @Best, @Fast          Model aliases
  @Claude-Opus-4.6      Specific model
  @Sophia               AI mate/persona
  @Web-Search           App skill
  @Code-Projects        Settings & memories
  @/path/to/file.ts     Attach local file (secrets auto-redacted)

  Sensitive files (.env) use zero-knowledge mode (only names + last 3 chars).
  Private keys (.pem, .key, SSH keys) are blocked by default.

  See all options: openmates mentions list

Examples:
  openmates chats list
  openmates chats show d262cb68
  openmates chats show last
  openmates chats show "Flight Connections Berlin to Bangkok"
  openmates chats search "Madrid"
  openmates chats new "Hello, what can you help me with?"
  openmates chats send --chat d262cb68 "follow-up question"
  openmates chats new "@Sophia help me with @./src/app.ts"
  openmates chats new "@best review @/home/user/project/.env"
  openmates chats delete d262cb68 a1b2c3d4
  openmates chats share d262cb68
  openmates chats share last --expires 604800
  openmates chats share d262cb68 --password mypass`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list [--json]
  openmates apps <app-id> [--json]                    App info
  openmates apps info <app-id> [--json]               App info (explicit)
  openmates apps skill-info <app-id> <skill-id> [--json]
  openmates apps <app-id> <skill-id> "<query>" [--json]
  openmates apps <app-id> <skill-id> --input '<json>' [--json]
  openmates apps travel booking-link --token "<token>" [--context '<json>']

Authentication:
  Uses your logged-in session (run 'openmates login' first).
  Optionally: --api-key <key> or set OPENMATES_API_KEY.

Examples:
  openmates apps list
  openmates apps web
  openmates apps web search "latest AI news"
  openmates apps news search "climate change"
  openmates apps ai ask "Summarise this: ..."
  openmates apps travel search_connections --input '{"requests":[{"legs":[{"origin":"BER","destination":"LHR","date":"2026-04-15"}]}]}'
  openmates apps travel booking-link --token "<booking_token from search result>"
  openmates apps skill-info web search`);
}

function printEmbedsHelp(): void {
  console.log(`Embeds commands:
  openmates embeds show <embed-id> [--json]
  openmates embeds share <embed-id> [--expires <seconds>] [--password <pwd>] [--json]

'show' displays the full decrypted content of an embed.
The embed ID can be the full UUID or just the first 8 characters.
Embed IDs are shown when viewing chat conversations (openmates chats show).

Examples:
  openmates embeds show a3f2b1c4`);
}

function printInspirationsHelp(): void {
  console.log(`Inspirations command:
  openmates inspirations [--lang <code>] [--json]

Fetches today's daily inspirations.
  - Logged in:  personalized inspirations (decrypted from your account).
  - Not logged in: public inspirations for the day (no login required).

Options:
  --lang <code>  ISO 639-1 language code for public inspirations (default: en).
                 Supported: en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi,
                            id, pl, nl, ar, hi, th, cs, sv
  --json         Output raw JSON instead of formatted output.

Examples:
  openmates inspirations
  openmates inspirations --lang de
  openmates inspirations --json`);
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
