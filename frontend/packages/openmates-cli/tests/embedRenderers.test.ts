/**
 * CLI embed renderer tests.
 *
 * These cover terminal-only rendering contracts that are not exercised by web
 * Playwright specs, including Remotion videos.create share-link output.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { renderEmbedPreview, renderEmbedFullscreen } from "../src/embedRenderers.ts";
import type { DecryptedEmbed } from "../src/client.ts";

function captureStdout(run: () => Promise<void>): Promise<string> {
  let output = "";
  const originalWrite = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((chunk: string | Uint8Array) => {
    output += chunk.toString();
    return true;
  }) as typeof process.stdout.write;
  return run().then(
    () => output,
    (error) => {
      throw error;
    },
  ).finally(() => {
    process.stdout.write = originalWrite;
  });
}

function remotionEmbed(): DecryptedEmbed {
  return {
    id: "embed-remotion-1",
    embedId: "12345678-1234-4234-9234-123456789abc",
    type: "app_skill_use",
    textPreview: "Product announcement video",
    appId: "videos",
    skillId: "create",
    createdAt: 1_700_000_000,
    content: {
      app_id: "videos",
      skill_id: "create",
      status: "finished",
      filename: "ProductAnnouncement.tsx",
      current_source_version: 2,
      remotion_source: `
        export const RemotionVideo = () => <AbsoluteFill><TitleSlide /><LogoOutro /></AbsoluteFill>;
        export const config = { durationInFrames: 180, fps: 30, width: 1280, height: 720 };
      `,
      files: {
        original: { s3_key: "video.mp4", mime_type: "video/mp4" },
      },
    },
  };
}

function mockClient(): { createEmbedShareLink: (embedId: string) => Promise<string> } {
  return {
    async createEmbedShareLink(embedId: string): Promise<string> {
      assert.equal(embedId, "12345678-1234-4234-9234-123456789abc");
      return "https://openmates.org/share/embed/12345678-1234-4234-9234-123456789abc#key=test-key";
    },
  };
}

describe("Remotion videos.create CLI renderer", () => {
  it("prints a rendered video link and QR code in preview output", async () => {
    const output = await captureStdout(async () => {
      await renderEmbedPreview(remotionEmbed(), mockClient() as never);
    });

    assert.match(output, /videos\/create/);
    assert.match(output, /Rendered video ready/);
    assert.match(output, /Rendered video link: https:\/\/openmates\.org\/share\/embed\/12345678/);
    assert.match(output, /QR code:/);
    assert.match(output, /ProductAnnouncement\.tsx/);
  });

  it("prints source, timeline, link, and QR code in fullscreen output", async () => {
    const output = await captureStdout(async () => {
      await renderEmbedFullscreen(remotionEmbed(), mockClient() as never);
    });

    assert.match(output, /Timeline:/);
    assert.match(output, /TitleSlide/);
    assert.match(output, /LogoOutro/);
    assert.match(output, /```tsx/);
    assert.match(output, /Rendered video link:/);
    assert.match(output, /QR code:/);
  });
});

describe("Direct content embed CLI renderers", () => {
  it("renders Mermaid diagrams as text previews and fenced source", async () => {
    const embed: DecryptedEmbed = {
      id: "embed-mermaid-1",
      embedId: "42345678-1234-4234-9234-123456789abc",
      type: "diagrams-mermaid",
      textPreview: "Signup sequence",
      appId: "diagrams",
      skillId: "mermaid",
      createdAt: 1_700_000_000,
      content: {
        type: "mermaid",
        app_id: "diagrams",
        skill_id: "mermaid",
        title: "Signup Flow",
        diagram_kind: "sequenceDiagram",
        diagram_code: "sequenceDiagram\n    User->>API: Submit email\n    API-->>User: Send code",
        status: "finished",
      },
    };

    const preview = await captureStdout(async () => {
      await renderEmbedPreview(embed, mockClient() as never);
    });

    assert.match(preview, /Mermaid diagram/);
    assert.match(preview, /Signup Flow/);
    assert.match(preview, /sequenceDiagram/);
    assert.match(preview, /User->>API: Submit email/);
    assert.doesNotMatch(preview, /encrypted_content/);

    const fullscreen = await captureStdout(async () => {
      await renderEmbedFullscreen(embed, mockClient() as never);
    });

    assert.match(fullscreen, /Mermaid diagram/);
    assert.match(fullscreen, /Signup Flow/);
    assert.match(fullscreen, /```mermaid/);
    assert.match(fullscreen, /API-->>User: Send code/);
    assert.doesNotMatch(fullscreen, /encrypted_content/);
  });

  it("renders backend Mermaid aliases as Diagrams Mermaid embeds", async () => {
    const output = await captureStdout(async () => {
      await renderEmbedPreview(
        {
          id: "embed-mermaid-2",
          embedId: "52345678-1234-4234-9234-123456789abc",
          type: "mermaid",
          textPreview: "Support flow",
          appId: "diagrams",
          skillId: "mermaid",
          createdAt: 1_700_000_000,
          content: {
            type: "mermaid",
            title: "Support Flow",
            diagram_kind: "flowchart",
            diagram_code: "flowchart TD\n    A[Ticket] --> B[Reply]",
            status: "finished",
          },
        },
        mockClient() as never,
      );
    });

    assert.match(output, /Mermaid diagram/);
    assert.match(output, /Support Flow/);
    assert.match(output, /flowchart/);
  });

  it("renders backend document aliases as document embeds", async () => {
    const output = await captureStdout(async () => {
      await renderEmbedPreview(
        {
          id: "embed-document-1",
          embedId: "22345678-1234-4234-9234-123456789abc",
          type: "document",
          textPreview: "Trip checklist",
          appId: "docs",
          skillId: "document",
          createdAt: 1_700_000_000,
          content: {
            type: "document",
            title: "Berlin to Prague Trip Preparation",
            word_count: 89,
          },
        },
        mockClient() as never,
      );
    });

    assert.match(output, /document/);
    assert.match(output, /Berlin to Prague Trip Preparation/);
    assert.match(output, /89 words/);
  });

  it("renders generated application embeds as application content", async () => {
    const output = await captureStdout(async () => {
      await renderEmbedPreview(
        {
          id: "embed-application-1",
          embedId: "32345678-1234-4234-9234-123456789abc",
          type: "code-application",
          textPreview: "Habit Garden",
          appId: "code",
          skillId: "application",
          createdAt: 1_700_000_000,
          content: {
            type: "application",
            name: "Habit Garden",
            framework: "Vite",
            runtime: "node",
          },
        },
        mockClient() as never,
      );
    });

    assert.match(output, /application/);
    assert.match(output, /Habit Garden/);
    assert.match(output, /Vite/);
  });
});
