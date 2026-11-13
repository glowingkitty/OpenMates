/**
 * Routing coverage for office and unsupported uploads in processFiles: spreadsheet
 * conversions report removed features, PowerPoint shows the "coming soon" notice,
 * and unreadable or unsupported files are no longer skipped silently. Conversion
 * itself is covered in utils/__tests__/fileContentParsers.test.ts.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  warning: vi.fn(),
  sheets: vi.fn(),
  doc: vi.fn(),
  insert: vi.fn(),
}));

vi.mock("../../stores/notificationStore", () => ({ notificationStore: { warning: mocks.warning } }));
vi.mock("../../i18n/translations", async () => {
  const { readable } = await import("svelte/store");
  const translate = (key: string, options?: { values?: Record<string, string> }) =>
    `${key}${options?.values ? ` ${JSON.stringify(options.values)}` : ""}`;
  return { text: readable(translate) };
});
vi.mock("./embedHandlers", () => ({
  createCodeFileEmbedNode: vi.fn(),
  createDelimitedTableFileEmbedNode: vi.fn(),
  createEmailFileEmbedNode: vi.fn(),
  createOfficeDocumentFileEmbedNode: mocks.doc,
  createOfficeSpreadsheetFileEmbedNodes: mocks.sheets,
  insertFileEmbedNodes: mocks.insert,
  insertImage: vi.fn(),
  insertMindMapFile: vi.fn(),
  insertPDF: vi.fn(),
}));
vi.mock("./services/codeEmbedService", () => ({ createDiagramHtmlEmbed: vi.fn() }));

import { processFiles } from "./fileHandlers";

const editor = { commands: { focus: vi.fn() } } as unknown as Parameters<typeof processFiles>[1];

describe("processFiles office and unsupported files", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("inserts every converted worksheet and reports removed Excel features", async () => {
    const nodes = [
      { type: "embed", attrs: { id: "a", type: "sheets-sheet" } },
      { type: "embed", attrs: { id: "b", type: "sheets-sheet" } },
    ];
    mocks.sheets.mockResolvedValue({ nodes, removed: ["charts", "unsupported_formulas"] });

    await processFiles([new File(["x"], "budget.xlsx")], editor, true);

    expect(mocks.insert).toHaveBeenCalledWith(editor, nodes);
    expect(mocks.warning).toHaveBeenCalledTimes(1);
    const [message] = mocks.warning.mock.calls[0];
    expect(message).toContain("enter_message.xlsx_features_removed");
    expect(message).toContain("enter_message.xlsx_feature_charts, enter_message.xlsx_feature_unsupported_formulas");
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("stays quiet when nothing was removed from the workbook", async () => {
    mocks.sheets.mockResolvedValue({ nodes: [{ type: "embed", attrs: { id: "a" } }], removed: [] });

    await processFiles([new File(["x"], "clean.xlsx")], editor, true);

    expect(mocks.warning).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("tells the user PowerPoint slides support is coming soon", async () => {
    await processFiles([new File(["x"], "deck.pptx")], editor, true);

    expect(mocks.insert).not.toHaveBeenCalled();
    expect(mocks.warning).toHaveBeenCalledWith(
      expect.stringContaining("enter_message.file_pptx_coming_soon"),
      expect.any(Number),
    );
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("shows notices for unsupported types and unreadable Word or Excel files", async () => {
    mocks.doc.mockResolvedValue(null);
    mocks.sheets.mockResolvedValue(null);

    await processFiles(
      [new File(["x"], "clip.mov"), new File(["x"], "broken.docx"), new File(["x"], "broken.xlsx")],
      editor,
      false,
    );

    expect(mocks.insert).not.toHaveBeenCalled();
    const messages = mocks.warning.mock.calls.map(([message]) => message as string);
    expect(messages.filter((m) => m.includes("enter_message.file_unsupported_type"))).toHaveLength(1);
    expect(messages.filter((m) => m.includes("enter_message.file_import_failed"))).toHaveLength(2);
  });
});
