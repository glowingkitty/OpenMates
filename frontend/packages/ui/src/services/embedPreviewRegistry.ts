/**
 * embedPreviewRegistry.ts
 *
 * Unified registry for resolving embed preview components and their props.
 *
 * This is the single source of truth for the mapping:
 *   (embedId, embedData, decodedContent) → { component: SvelteComponent, props: Record<string, unknown> }
 *
 * Modelled after embedFullscreenResolver.ts (which does the same for fullscreen components).
 * Previously, AppEmbedsPanel.svelte and SettingsShare.svelte each maintained independent
 * copy-paste if/else chains with subtle divergences (wrong field names, missing embed types).
 * This registry fixes all of that and ensures a single addition registers a new embed type
 * everywhere it is shown (My Embeds panel, Share settings panel, etc.).
 *
 * ── Adding a new embed type ────────────────────────────────────────────────────────────────
 * 1. Add a new entry to the `resolvers` Map below (key = canonical embed type string or a
 *    synthetic key like "app:web:search" for app-skill-use embeds).
 * 2. Inside the resolver, dynamic-import the Preview component and return { component, props }.
 * 3. That's it. Both AppEmbedsPanel and SettingsShare will automatically pick it up.
 * ──────────────────────────────────────────────────────────────────────────────────────────
 */

import type { Component } from "svelte";

// ── Types ────────────────────────────────────────────────────────────────────

/**
 * All the data available when resolving a preview component.
 * Every field is optional so callers don't have to pad missing data.
 */
export interface EmbedPreviewContext {
  /** Embed UUID (without "embed:" prefix) */
  embedId: string;
  /**
   * Raw embed entry from the store (e.g. from embedStore.get() or resolveEmbed()).
   * Has `.status`, `.type`, `.app_id`, `.skill_id`, `.content`.
   */
  embedData: Record<string, unknown>;
  /**
   * TOON-decoded content object — the canonical field source.
   * Callers must decode before calling the registry.
   */
  decodedContent: Record<string, unknown>;
  /**
   * Callback invoked when the user clicks the preview card to open the fullscreen.
   * Pass a no-op `() => {}` when fullscreen is not supported (e.g. share preview).
   */
  onFullscreen: () => void;
}

type PreviewResolver = (
  ctx: EmbedPreviewContext,
) => Promise<{ component: Component; props: Record<string, unknown> } | null>;

// ── Helper ────────────────────────────────────────────────────────────────────

/**
 * Narrow the raw status string from the embed store to the union accepted by
 * most preview components.  Defaults to 'finished' because preview panels only
 * show already-stored (completed) embeds — 'processing' is the right default
 * only for the live in-chat renderer (AppSkillUseRenderer).
 */
function normalizeStatus(
  raw: unknown,
): "processing" | "finished" | "error" | "cancelled" {
  if (
    raw === "processing" ||
    raw === "finished" ||
    raw === "error" ||
    raw === "cancelled"
  ) {
    return raw;
  }
  return "finished";
}

// ── Registry ──────────────────────────────────────────────────────────────────

/**
 * Keys in this Map follow two conventions:
 *
 *  • App-skill-use embeds:  "app:<appId>:<skillId>"
 *    e.g. "app:web:search", "app:images:generate"
 *
 *  • Direct / auto-converted embeds:  the canonical `embedData.type` string
 *    e.g. "code-code", "docs-doc", "sheets-sheet", "math-plot"
 *    Aliases (legacy type strings) are registered as separate Map entries
 *    pointing to the same resolver so old stored embeds still resolve.
 */
const resolvers = new Map<string, PreviewResolver>();

// ── App-skill-use: web ────────────────────────────────────────────────────────

resolvers.set(
  "app:web:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/web/WebSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: images / search ────────────────────────────────────────────

resolvers.set(
  "app:images:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/images/ImagesSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: news ───────────────────────────────────────────────────────

resolvers.set(
  "app:news:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/news/NewsSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: videos / search ────────────────────────────────────────────

resolvers.set(
  "app:videos:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/videos/VideosSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: videos / get_transcript ────────────────────────────────────

const videoTranscriptResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/videos/VideoTranscriptEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      results: decodedContent.results || [],
      status: normalizeStatus(embedData.status),
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:videos:get_transcript", videoTranscriptResolver);
resolvers.set("app:videos:get-transcript", videoTranscriptResolver); // hyphen alias

// ── App-skill-use: maps / search ──────────────────────────────────────────────

resolvers.set(
  "app:maps:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/maps/MapsSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: code / get_docs ────────────────────────────────────────────

const codeGetDocsResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/code/CodeGetDocsEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      library: decodedContent.library || "",
      question: decodedContent.question || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:code:get_docs", codeGetDocsResolver);
resolvers.set("app:code:get-docs", codeGetDocsResolver); // hyphen alias

// ── App-skill-use: travel / search_connections ────────────────────────────────

const travelSearchResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelSearchEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      query: decodedContent.query || "",
      provider: decodedContent.provider || "Google",
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:travel:search_connections", travelSearchResolver);
resolvers.set("app:travel:search-connections", travelSearchResolver); // hyphen alias

// ── App-skill-use: travel / price_calendar ────────────────────────────────────

const travelPriceCalResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelPriceCalendarEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      query: decodedContent.query || "",
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:travel:price_calendar", travelPriceCalResolver);
resolvers.set("app:travel:price-calendar", travelPriceCalResolver); // hyphen alias

// ── App-skill-use: reminder / set_reminder ────────────────────────────────────

const reminderResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/reminder/ReminderEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      reminderId: decodedContent.reminder_id,
      triggerAtFormatted: decodedContent.trigger_at_formatted,
      triggerAt: decodedContent.trigger_at,
      targetType: decodedContent.target_type,
      isRepeating: decodedContent.is_repeating || false,
      message: decodedContent.message,
      emailNotificationWarning: decodedContent.email_notification_warning,
      status: normalizeStatus(embedData.status),
      error: decodedContent.error,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:reminder:set_reminder", reminderResolver);
resolvers.set("app:reminder:set-reminder", reminderResolver); // hyphen alias

// ── App-skill-use: images / generate ─────────────────────────────────────────

const imageGenerateResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/images/ImageGenerateEmbedPreview.svelte");
  const skillId =
    (decodedContent.skill_id as string) ||
    (embedData.skill_id as string) ||
    "generate";
  return {
    component,
    props: {
      id: embedId,
      skillId: skillId as "generate" | "generate_draft",
      prompt: decodedContent.prompt || "",
      model: decodedContent.model || embedData.model || "",
      s3BaseUrl: decodedContent.s3_base_url || embedData.s3_base_url || "",
      files: decodedContent.files || embedData.files || undefined,
      aesKey: decodedContent.aes_key || embedData.aes_key || "",
      aesNonce: decodedContent.aes_nonce || embedData.aes_nonce || "",
      status: normalizeStatus(embedData.status),
      error: decodedContent.error || embedData.error || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:images:generate", imageGenerateResolver);
resolvers.set("app:images:generate_draft", imageGenerateResolver);

// ── Direct / auto-converted: code ─────────────────────────────────────────────

const codeResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/code/CodeEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      language: decodedContent.language || "",
      filename: decodedContent.filename,
      lineCount: decodedContent.line_count || decodedContent.lineCount || 0,
      codeContent: decodedContent.code || decodedContent.content || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
// All known type strings that mean "code embed"
resolvers.set("code-code", codeResolver);
resolvers.set("code", codeResolver); // legacy server type
resolvers.set("code-block", codeResolver); // legacy client alias
resolvers.set("code_embed", codeResolver); // legacy alias used in AppEmbedsPanel
// Also reachable via app-skill routing when app_id === 'code' and no specific skill matched:
resolvers.set("app:code:*", codeResolver);

// ── Direct / auto-converted: sheets ──────────────────────────────────────────

const sheetResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/sheets/SheetEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status) as
        | "processing"
        | "finished"
        | "error",
      title: decodedContent.title || "",
      rowCount: decodedContent.row_count || 0,
      colCount: decodedContent.col_count || 0,
      // Canonical field is `table`; keep `table_content` and `content` as fallbacks
      // for any embeds stored before field was standardised.
      tableContent: (decodedContent.table ||
        decodedContent.table_content ||
        decodedContent.content ||
        "") as string,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("sheets-sheet", sheetResolver);
resolvers.set("sheet", sheetResolver); // legacy server type
// App-skill route for sheets app (skill = "sheet")
resolvers.set("app:sheets:sheet", sheetResolver);

// ── Direct / auto-converted: math-plot ───────────────────────────────────────

const mathPlotResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/math/MathPlotEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      // plot_spec is the canonical field; expression is the legacy name (pre-rename)
      plotSpec: decodedContent.plot_spec || decodedContent.expression || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("math-plot", mathPlotResolver);
// App-skill route for math app
resolvers.set("app:math:plot", mathPlotResolver);

// ── Direct / auto-converted: docs (document_html) ────────────────────────────

const docsResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/docs/DocsEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status) as
        | "processing"
        | "finished"
        | "error",
      title: decodedContent.title || "",
      wordCount: decodedContent.word_count || 0,
      htmlContent: decodedContent.html || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("docs-doc", docsResolver);
resolvers.set("document", docsResolver); // legacy server type
// App-skill route for docs app
resolvers.set("app:docs:doc", docsResolver);

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Derive the registry key from the embed context.
 *
 * Resolution order (first match wins):
 *  1. Specific app-skill key:  "app:<appId>:<skillId>"
 *  2. Wildcard app key:        "app:<appId>:*"   (catches code embeds via app_id only)
 *  3. Direct type key:         embedData.type    (e.g. "docs-doc", "math-plot")
 *
 * Returns null if no key matches — the caller should fall back to a text summary.
 */
function deriveKey(ctx: EmbedPreviewContext): string | null {
  const d = ctx.decodedContent;
  const e = ctx.embedData;

  const appId = (d.app_id as string) || (e.app_id as string) || "";
  const skillId = (d.skill_id as string) || (e.skill_id as string) || "";
  const type = (e.type as string) || "";

  // 1. Specific app:skill key
  if (appId && skillId) {
    const appSkillKey = `app:${appId}:${skillId}`;
    if (resolvers.has(appSkillKey)) return appSkillKey;
  }

  // 2. Wildcard app key (e.g. "app:code:*" catches plain code embeds)
  if (appId) {
    const wildcardKey = `app:${appId}:*`;
    if (resolvers.has(wildcardKey)) return wildcardKey;
  }

  // 3. Direct type key
  if (type && resolvers.has(type)) return type;

  return null;
}

/**
 * Resolve the preview component and props for an embed.
 *
 * @param ctx - The embed context (id, raw data, decoded content, fullscreen callback).
 * @returns `{ component, props }` ready to mount, or `null` if no resolver is registered.
 *
 * @example
 * ```ts
 * const result = await embedPreviewRegistry.resolve({
 *   embedId,
 *   embedData,
 *   decodedContent,
 *   onFullscreen: () => openEmbedFullscreen(embedId, embedData, embedEntry),
 * });
 * if (result) {
 *   mount(result.component, { target, props: result.props });
 * }
 * ```
 */
async function resolve(
  ctx: EmbedPreviewContext,
): Promise<{ component: Component; props: Record<string, unknown> } | null> {
  const key = deriveKey(ctx);

  if (!key) {
    console.warn("[embedPreviewRegistry] No resolver found for embed:", {
      embedId: ctx.embedId,
      app_id: ctx.decodedContent.app_id || ctx.embedData.app_id,
      skill_id: ctx.decodedContent.skill_id || ctx.embedData.skill_id,
      type: ctx.embedData.type,
    });
    return null;
  }

  try {
    const resolver = resolvers.get(key)!;
    return await resolver(ctx);
  } catch (error) {
    console.error(
      "[embedPreviewRegistry] Error resolving preview for key:",
      key,
      error,
    );
    return null;
  }
}

/**
 * Check whether a resolver exists for the given embed context without loading any component.
 * Useful to pre-filter embeds before attempting a full resolve.
 */
function canResolve(ctx: Omit<EmbedPreviewContext, "onFullscreen">): boolean {
  return deriveKey({ ...ctx, onFullscreen: () => {} }) !== null;
}

export const embedPreviewRegistry = { resolve, canResolve };
