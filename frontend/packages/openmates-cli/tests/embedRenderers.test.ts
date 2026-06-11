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
