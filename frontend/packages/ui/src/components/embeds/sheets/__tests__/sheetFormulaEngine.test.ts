import { describe, expect, it } from "vitest";
import { evaluateSheet, parseNumericText } from "../sheetFormulaEngine";
import {
  computeTableFormulas,
  parseSheetEmbedContent,
  parseMarkdownTable,
  setMarkdownTableCell,
} from "../sheetEmbedContent";

const ev = (grid: string[][]) => evaluateSheet(grid).display;

describe("sheetFormulaEngine", () => {
  // contract-test: infrastructure
  it("evaluates cell refs, arithmetic and precedence", () => {
    expect(ev([["2", "3", "=A1+B1*2"]])[0][2]).toBe("8");
    expect(ev([["10"], ["=A1/4"]])[1][0]).toBe("2.5");
  });

  // contract-test: infrastructure
  it("supports ranges with SUM/AVERAGE/MIN/MAX/COUNT", () => {
    const grid = [["1"], ["2"], ["x"], ["$3.50"], ["=SUM(A1:A4)"], ["=AVERAGE(A1:A2)"], ["=MAX(A1:A4)"], ["=COUNT(A1:A4)"]];
    const out = ev(grid).map((r) => r[0]);
    expect(out.slice(4)).toEqual(["6.5", "1.5", "3.5", "3"]);
  });

  // contract-test: infrastructure
  it("supports IF, ROUND, ROUNDUP and comparison", () => {
    expect(ev([["7"], ['=IF(A1>5,"high","low")'], ["=ROUND(A1/3,2)"], ["=ROUNDUP(A1/3,0)"]]).map((r) => r[0]))
      .toEqual(["7", "high", "2.33", "3"]);
  });

  // contract-test: infrastructure
  it("recalculates dependents when an input changes (chains)", () => {
    const make = (price: string) => [["Price", price], ["Cost", "4"], ["Profit", "=B1-B2"], ["Units", "=ROUNDUP(100/B3,0)"]];
    expect(ev(make("10"))[3][1]).toBe("17");
    expect(ev(make("14"))[3][1]).toBe("10");
  });

  // contract-test: infrastructure
  it("reports errors instead of throwing", () => {
    const out = ev([["0", "=1/A1", "=A1+", "=NOPE(1)", "=C1", "=SUM(", '=IFERROR(1/A1,"n/a")']]);
    expect(out[0].slice(1)).toEqual(["#DIV/0!", "#ERROR!", "#NAME?", "#ERROR!", "#ERROR!", "n/a"]);
  });

  // contract-test: infrastructure
  it("detects circular references", () => {
    const out = ev([["=B1", "=A1"]]);
    expect(out[0]).toEqual(["#CIRC!", "#CIRC!"]);
  });

  // contract-test: infrastructure
  it("parses numeric text forms", () => {
    expect(parseNumericText("1,200.50")).toBe(1200.5);
    expect(parseNumericText("€12")).toBe(12);
    expect(parseNumericText("25%")).toBe(0.25);
    expect(parseNumericText("abc")).toBeNull();
  });

  // contract-test: infrastructure
  it("avoids floating point noise", () => {
    expect(ev([["0.1", "0.2", "=A1+B1"]])[0][2]).toBe("0.3");
  });
});

const MD = [
  "| Item | Value | Note |",
  "| --- | --- | --- |",
  "| INPUTS | | |",
  "| Material cost | 4 | Assumption |",
  "| Selling price | 10 | |",
  "| FORMULAS | | |",
  "| Profit per item | =B3-B2 | |",
  "| Margin | =ROUND(B5/B3*100,1) | |",
].join("\n");

describe("sheet markdown formulas", () => {
  // contract-test: infrastructure
  it("keeps formula cells verbatim (no markdown stripping of * or _)", () => {
    const raw = parseMarkdownTable("| a | b |\n| - | - |\n| 2 | =A1*A1*A1 |");
    expect(raw.rows[0][1].content).toBe("=A1*A1*A1");
  });

  // contract-test: infrastructure
  it("computes display values and keeps the formula source", () => {
    const { parsedTable } = parseSheetEmbedContent(MD);
    expect(parsedTable.rows[4][1].content).toBe("6");
    expect(parsedTable.rows[4][1].formula).toBe("=B3-B2");
    expect(parsedTable.rows[5][1].content).toBe("60");
  });

  // contract-test: infrastructure
  it("edit of an input updates dependents and leaves other lines verbatim", () => {
    const next = setMarkdownTableCell(MD, 2, 1, "20");
    expect(next.split("\n")[4]).toBe("| Selling price | 20 |  |");
    expect(next.split("\n")[0]).toBe(MD.split("\n")[0]);
    const { parsedTable } = parseSheetEmbedContent(next);
    expect(parsedTable.rows[4][1].content).toBe("16");
    expect(parsedTable.rows[5][1].content).toBe("80");
  });

  // contract-test: infrastructure
  it("rejects pipes and out of range edits", () => {
    expect(() => setMarkdownTableCell(MD, 0, 1, "a|b")).toThrow();
    expect(() => setMarkdownTableCell(MD, 99, 1, "1")).toThrow();
    expect(() => setMarkdownTableCell(MD, 0, 9, "1")).toThrow();
  });

  // contract-test: infrastructure
  it("returns tables without formulas unchanged", () => {
    const t = parseMarkdownTable("| a |\n| - |\n| 1 |");
    expect(computeTableFormulas(t)).toBe(t);
  });
});
