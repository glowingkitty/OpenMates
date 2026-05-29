// frontend/packages/ui/src/components/enter_message/utils/__tests__/fileHelpers.test.ts
//
// Unit tests for message input file type routing. This routing is privacy
// sensitive because code/text/table/email files must stay on the client-side
// PII redaction path before any embed content is sent to the backend or LLM.

import { describe, expect, it } from "vitest";
import {
  getLanguageFromFilename,
  isCodeOrTextFile,
  isDelimitedTableFile,
  isEmailFile,
  isOfficeDocumentFile,
  isOfficeSpreadsheetFile,
} from "../fileHelpers";

describe("fileHelpers", () => {
  it("recognizes common programming and config files as code/text", () => {
    expect(isCodeOrTextFile("main.py")).toBe(true);
    expect(isCodeOrTextFile("component.tsx")).toBe(true);
    expect(isCodeOrTextFile(".env")).toBe(true);
    expect(isCodeOrTextFile("Makefile")).toBe(true);
    expect(isCodeOrTextFile("debug.log")).toBe(true);
  });

  it("routes delimited tables and email separately", () => {
    expect(isDelimitedTableFile("contacts.csv")).toBe(true);
    expect(isDelimitedTableFile("contacts.tsv")).toBe(true);
    expect(isEmailFile("message.eml")).toBe(true);
    expect(isCodeOrTextFile("message.eml")).toBe(false);
  });

  it("routes Office documents to client-side parsers", () => {
    expect(isOfficeDocumentFile("brief.docx")).toBe(true);
    expect(isOfficeSpreadsheetFile("contacts.xlsx")).toBe(true);
    expect(isCodeOrTextFile("brief.docx")).toBe(false);
  });

  it("maps expanded language extensions", () => {
    expect(getLanguageFromFilename("script.ps1")).toBe("powershell");
    expect(getLanguageFromFilename("app.cs")).toBe("csharp");
    expect(getLanguageFromFilename("settings.toml")).toBe("toml");
  });
});
