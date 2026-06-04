// frontend/packages/ui/src/components/enter_message/utils/__tests__/fileContentParsers.test.ts
//
// Unit tests for lightweight client-side file parsers used before embed PII
// redaction. These parsers intentionally avoid heavy document dependencies and
// must preserve enough structure for sheet/mail embeds to stay useful.

import { describe, expect, it } from "vitest";
import JSZip from "jszip";
import { delimitedTextToMarkdownTable, docxArrayBufferToHtml, parseEmlText, xlsxArrayBufferToMarkdownTable } from "../fileContentParsers";

describe("delimitedTextToMarkdownTable", () => {
  it("converts CSV rows and preserves quoted commas", () => {
    const markdown = delimitedTextToMarkdownTable(
      'Name,Email,Note\nAda,ada@example.com,"Hello, team"',
      ",",
    );

    expect(markdown).toContain("| Name | Email | Note |");
    expect(markdown).toContain("| Ada | ada@example.com | Hello, team |");
  });

  it("converts TSV rows", () => {
    const markdown = delimitedTextToMarkdownTable("Name\tScore\nGrace\t9", "\t");

    expect(markdown).toContain("| Name | Score |");
    expect(markdown).toContain("| Grace | 9 |");
  });
});

describe("parseEmlText", () => {
  it("extracts standard email headers and body", () => {
    const parsed = parseEmlText([
      "From: Ada <ada@example.com>",
      "To: Grace <grace@example.com>",
      "Subject: Launch notes",
      "Date: Fri, 29 May 2026 10:00:00 +0000",
      "",
      "Please call +1 555 123 4567 before launch.",
    ].join("\n"));

    expect(parsed.receiver).toBe("Grace <grace@example.com>");
    expect(parsed.subject).toBe("Launch notes");
    expect(parsed.content).toContain("Please call");
    expect(parsed.footer).toContain("ada@example.com");
  });
});

describe("Office Open XML parsers", () => {
  it("extracts paragraph text from a basic DOCX", async () => {
    const zip = new JSZip();
    zip.file("word/document.xml", [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
      '<w:body>',
      '<w:p><w:r><w:t>Ada private launch notes</w:t></w:r></w:p>',
      '<w:p><w:r><w:t>Contact ada.private@example.com before launch.</w:t></w:r></w:p>',
      '</w:body></w:document>',
    ].join(""));
    const buffer = await zip.generateAsync({ type: "arraybuffer" });

    const html = await docxArrayBufferToHtml(buffer);

    expect(html).toContain("<p>Ada private launch notes</p>");
    expect(html).toContain("ada.private@example.com");
  });

  it("extracts shared-string cells from a basic XLSX", async () => {
    const zip = new JSZip();
    zip.file("xl/workbook.xml", [
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
      '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
    ].join(""));
    zip.file("xl/_rels/workbook.xml.rels", [
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>',
      '</Relationships>',
    ].join(""));
    zip.file("xl/sharedStrings.xml", [
      '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
      '<si><t>Name</t></si><si><t>Email</t></si><si><t>Ada</t></si><si><t>ada.private@example.com</t></si>',
      '</sst>',
    ].join(""));
    zip.file("xl/worksheets/sheet1.xml", [
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
      '<sheetData>',
      '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>',
      '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>',
      '</sheetData></worksheet>',
    ].join(""));
    const buffer = await zip.generateAsync({ type: "arraybuffer" });

    const markdown = await xlsxArrayBufferToMarkdownTable(buffer);

    expect(markdown).toContain("| Name | Email |");
    expect(markdown).toContain("| Ada | ada.private@example.com |");
  });
});
