// frontend/packages/ui/src/components/enter_message/utils/__tests__/fileContentParsers.test.ts
//
// Unit tests for lightweight client-side file parsers used before embed PII
// redaction. These parsers intentionally avoid heavy document dependencies and
// must preserve enough structure for sheet/mail embeds to stay useful.

import { describe, expect, it } from "vitest";
import JSZip from "jszip";
import { delimitedTextToMarkdownTable, docxArrayBufferToHtml, parseEmlText, xlsxArrayBufferToMarkdownTable } from "../fileContentParsers";
import { convertXlsxWorkbook } from "../xlsxSheetConverter";
import { computeTableFormulas, parseMarkdownTable } from "../../../embeds/sheets/sheetEmbedContent";

describe("delimitedTextToMarkdownTable", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("converts CSV rows and preserves quoted commas", () => {
    const markdown = delimitedTextToMarkdownTable(
      'Name,Email,Note\nAda,ada@example.com,"Hello, team"',
      ",",
    );

    expect(markdown).toContain("| Name | Email | Note |");
    expect(markdown).toContain("| Ada | ada@example.com | Hello, team |");
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("converts TSV rows", () => {
    const markdown = delimitedTextToMarkdownTable("Name\tScore\nGrace\t9", "\t");

    expect(markdown).toContain("| Name | Score |");
    expect(markdown).toContain("| Grace | 9 |");
  });
});

describe("parseEmlText", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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
  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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

const WB_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';

async function buildWorkbook(options: {
  sheets: Array<{ name: string; xml: string; hidden?: boolean }>;
  sharedStrings?: string[];
  styles?: string;
  extraFiles?: Record<string, string>;
}): Promise<ArrayBuffer> {
  const zip = new JSZip();
  zip.file("xl/workbook.xml", `<workbook ${WB_NS}><sheets>${options.sheets
    .map((s, i) => `<sheet name="${s.name}" sheetId="${i + 1}"${s.hidden ? ' state="hidden"' : ""} r:id="rId${i + 1}"/>`)
    .join("")}</sheets></workbook>`);
  zip.file("xl/_rels/workbook.xml.rels", `<Relationships>${options.sheets
    .map((_s, i) => `<Relationship Id="rId${i + 1}" Type="worksheet" Target="worksheets/sheet${i + 1}.xml"/>`)
    .join("")}</Relationships>`);
  options.sheets.forEach((s, i) => zip.file(`xl/worksheets/sheet${i + 1}.xml`, `<worksheet ${WB_NS}>${s.xml}</worksheet>`));
  if (options.sharedStrings) {
    zip.file("xl/sharedStrings.xml", `<sst>${options.sharedStrings.map((t) => `<si><t>${t}</t></si>`).join("")}</sst>`);
  }
  if (options.styles) zip.file("xl/styles.xml", options.styles);
  for (const [name, content] of Object.entries(options.extraFiles ?? {})) zip.file(name, content);
  return zip.generateAsync({ type: "arraybuffer" });
}

describe("convertXlsxWorkbook", () => {
  const strings = ["Item", "Qty", "Price", "Total", "Pen", "Book"];
  const salesSheet = [
    "<sheetData>",
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>',
    '<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2"><v>2</v></c><c r="C2"><v>1.5</v></c><c r="D2"><f>B2*C2</f><v>3</v></c></row>',
    '<row r="3"><c r="A3" t="s"><v>5</v></c><c r="B3"><v>3</v></c><c r="C3"><v>10</v></c><c r="D3"><f>B3*C3</f><v>30</v></c></row>',
    '<row r="5"><c r="A5" t="str"><v>Sum</v></c><c r="D5"><f>SUM(D1:D3)</f><v>33</v></c></row>',
    "</sheetData>",
  ].join("");

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("keeps supported formulas rewritten to data-row coordinates and computes them", async () => {
    const workbook = await convertXlsxWorkbook(await buildWorkbook({
      sheets: [{ name: "Sales", xml: salesSheet }],
      sharedStrings: strings,
    }));

    expect(workbook.sheets).toHaveLength(1);
    const markdown = workbook.sheets[0].markdown;
    expect(markdown).toContain("| Item | Qty | Price | Total |");
    expect(markdown).toContain("| Pen | 2 | 1.5 | =B1*C1 |");
    expect(markdown).toContain("| Sum |  |  | =SUM(D1:D2) |");
    expect(workbook.removed).toEqual([]);

    const computed = computeTableFormulas(parseMarkdownTable(markdown));
    expect(computed.rows[0][3].content).toBe("3");
    expect(computed.rows[1][3].content).toBe("30");
    expect(computed.rows[3][3].content).toBe("33");
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("converts every visible sheet, skips hidden ones and reports them", async () => {
    const simple = (value: string) =>
      `<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>H</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>${value}</t></is></c></row></sheetData>`;
    const workbook = await convertXlsxWorkbook(await buildWorkbook({
      sheets: [
        { name: "One", xml: simple("a") },
        { name: "Secret", xml: simple("b"), hidden: true },
        { name: "Two", xml: simple("c") },
      ],
    }));

    expect(workbook.sheets.map((s) => s.name)).toEqual(["One", "Two"]);
    expect(workbook.sheets[1].markdown).toContain("| c |");
    expect(workbook.removed).toContain("hidden_sheets");
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("keeps cached values for unsupported formulas and reports them", async () => {
    const workbook = await convertXlsxWorkbook(await buildWorkbook({
      sheets: [{
        name: "S",
        xml: '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>K</t></is></c><c r="B1" t="inlineStr"><is><t>V</t></is></c></row>'
          + '<row r="2"><c r="A2"><v>7</v></c><c r="B2"><f>VLOOKUP(A2,Other!A:B,2,FALSE)</f><v>42</v></c></row>'
          + '<row r="3"><c r="A3"><v>8</v></c><c r="B3"><f>A3*2</f><v>16</v></c></row></sheetData>',
      }],
    }));

    expect(workbook.sheets[0].markdown).toContain("| 7 | 42 |");
    expect(workbook.sheets[0].markdown).toContain("| 8 | =A2*2 |");
    expect(workbook.removed).toEqual(["unsupported_formulas"]);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("expands shared formulas relative to each cell", async () => {
    const workbook = await convertXlsxWorkbook(await buildWorkbook({
      sheets: [{
        name: "S",
        xml: '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>N</t></is></c><c r="B1" t="inlineStr"><is><t>Dbl</t></is></c></row>'
          + '<row r="2"><c r="A2"><v>1</v></c><c r="B2"><f t="shared" ref="B2:B3" si="0">A2*2</f><v>2</v></c></row>'
          + '<row r="3"><c r="A3"><v>5</v></c><c r="B3"><f t="shared" si="0"/><v>10</v></c></row></sheetData>',
      }],
    }));

    expect(workbook.sheets[0].markdown).toContain("| 1 | =A1*2 |");
    expect(workbook.sheets[0].markdown).toContain("| 5 | =A2*2 |");
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("renders dates and percentages as text and never executes or keeps macros", async () => {
    const styles = '<styleSheet><numFmts><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>'
      + '<cellXfs><xf numFmtId="0" fillId="0"/><xf numFmtId="164" fillId="0"/><xf numFmtId="9" fillId="0"/><xf numFmtId="0" fillId="3"/></cellXfs></styleSheet>';
    const workbook = await convertXlsxWorkbook(await buildWorkbook({
      sheets: [{
        name: "S",
        xml: '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>When</t></is></c><c r="B1" t="inlineStr"><is><t>Rate</t></is></c><c r="C1" t="inlineStr"><is><t>Note</t></is></c></row>'
          + '<row r="2"><c r="A2" s="1"><v>46000</v></c><c r="B2" s="2"><v>0.125</v></c><c r="C2" s="3" t="inlineStr"><is><t>x</t></is></c></row></sheetData>'
          + '<mergeCells count="1"><mergeCell ref="A5:B5"/></mergeCells>',
      }],
      styles,
      extraFiles: { "xl/vbaProject.bin": "binary", "xl/charts/chart1.xml": "<c/>" },
    }));

    expect(workbook.sheets[0].markdown).toContain("| 2025-12-09 | 12.5% | x |");
    expect(workbook.removed).toEqual(expect.arrayContaining(["macros", "charts", "merged_cells", "formatting"]));
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("uses the first sheet for the legacy markdown helper", async () => {
    const markdown = await xlsxArrayBufferToMarkdownTable(await buildWorkbook({
      sheets: [{ name: "Sales", xml: salesSheet }],
      sharedStrings: strings,
    }));
    expect(markdown.split("\n")[0]).toBe("| Item | Qty | Price | Total |");
  });
});

describe("docxArrayBufferToHtml structure", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("keeps headings, emphasis, lists and tables", async () => {
    const zip = new JSZip();
    zip.file("word/document.xml", [
      '<w:document xmlns:w="w"><w:body>',
      '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Report</w:t></w:r></w:p>',
      '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r><w:r><w:t xml:space="preserve"> and plain &amp; more</w:t></w:r></w:p>',
      '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>First</w:t></w:r></w:p>',
      '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Second</w:t></w:r></w:p>',
      '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>H1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>H2</w:t></w:r></w:p></w:tc></w:tr>',
      '<w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc></w:tr></w:tbl>',
      '</w:body></w:document>',
    ].join(""));
    zip.file("word/numbering.xml", '<w:numbering xmlns:w="w"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>');

    const html = await docxArrayBufferToHtml(await zip.generateAsync({ type: "arraybuffer" }));

    expect(html).toContain("<h1>Report</h1>");
    expect(html).toContain("<strong>Bold</strong> and plain &amp; more");
    expect(html).toContain("<ol><li>First</li><li>Second</li></ol>");
    expect(html).toContain("<table><tr><th>H1</th><th>H2</th></tr><tr><td>a</td><td>b</td></tr></table>");
  });
});
