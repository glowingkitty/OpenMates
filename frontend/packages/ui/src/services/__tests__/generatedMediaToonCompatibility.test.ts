import { beforeEach, expect, it, vi } from "vitest";
import { authStore } from "../../stores/authState";
import { decodeToonContent } from "../embedResolver";

vi.mock("../websocketService", () => ({
  webSocketService: { sendMessage: vi.fn() },
}));

beforeEach(() => {
  authStore.set({ isAuthenticated: true, isInitialized: true });
});

// contract-test: direct surface=gui.web assertions=app-skills.media.parent-children-and-attribution,app-skills.media.visible-assistant-results
it("decodes generated-media variants without absorbing their table into status", async () => {
  const decoded = await decodeToonContent(
    "type: generated_image\nstatus: finished\n" +
    "files[2:]{s3_key,width,height,format}:\n" +
    "  original: unit/original.png,1024,1024,png\n" +
    "  preview: unit/preview.webp,512,512,webp\n" +
    "prompt: A sunflower illustration\nmodel: unit-image-model",
  );
  expect(decoded).toMatchObject({
    type: "generated_image", status: "finished",
    files: {
      original: { s3_key: "unit/original.png", width: 1024, height: 1024, format: "png" },
      preview: { s3_key: "unit/preview.webp", width: 512, height: 512, format: "webp" },
    },
    prompt: "A sunflower illustration", model: "unit-image-model",
  });
});
