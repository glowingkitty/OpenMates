/**
 * Spreadsheet formula engine for sheet embeds.
 *
 * A table cell whose raw text starts with "=" is a formula. Cell references use
 * the same coordinates as the fullscreen grid and `#cell=` embed links: columns
 * are A, B, C... and rows count DATA rows (the first row below the header is
 * row 1). Supported: numbers, strings, + - * / ^ & % unary minus, comparisons,
 * A1 / $A$1 refs, A1:B5 ranges and the functions in FUNCTIONS below.
 * Evaluation is pure and recursive with memoisation and cycle detection, so any
 * input change simply re-evaluates the whole grid (grids are small).
 */

export type FormulaError = "#DIV/0!" | "#REF!" | "#NAME?" | "#VALUE!" | "#CIRC!" | "#ERROR!";
type Scalar = number | string | boolean | null;
type Value = Scalar | Scalar[][];

class FormulaFailure extends Error {
  readonly code: FormulaError;
  constructor(code: FormulaError) {
    super(code);
    this.code = code;
  }
}

export function isFormulaText(raw: string): boolean {
  return raw.trimStart().startsWith("=") && raw.trim().length > 1;
}

/** Parse a literal cell text into a number if it looks numeric ("1,200", "$9.50", "12%"). */
export function parseNumericText(raw: string): number | null {
  let text = raw.trim();
  if (!text) return null;
  let percent = false;
  if (text.endsWith("%")) {
    percent = true;
    text = text.slice(0, -1).trim();
  }
  text = text.replace(/^([-+]?)\s*[$€£¥]\s*/, "$1").replace(/\s*[$€£¥]$/, "");
  if (/^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(text)) text = text.replace(/,/g, "");
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(text)) return null;
  const n = Number(text);
  if (!Number.isFinite(n)) return null;
  return percent ? n / 100 : n;
}

export function columnLettersToIndex(letters: string): number {
  return letters.toUpperCase().split("").reduce((acc, ch) => acc * 26 + ch.charCodeAt(0) - 64, 0) - 1;
}

// ── Tokenizer ───────────────────────────────────────────────────────────────

type Token =
  | { t: "num"; v: number }
  | { t: "str"; v: string }
  | { t: "ref"; v: string }
  | { t: "name"; v: string }
  | { t: "op"; v: string };

function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (/\s/.test(ch)) { i++; continue; }
    if (ch === '"') {
      let j = i + 1;
      let out = "";
      while (j < src.length) {
        if (src[j] === '"') {
          if (src[j + 1] === '"') { out += '"'; j += 2; continue; }
          break;
        }
        out += src[j++];
      }
      if (j >= src.length) throw new FormulaFailure("#ERROR!");
      tokens.push({ t: "str", v: out });
      i = j + 1;
      continue;
    }
    const numMatch = /^(\d+\.?\d*|\.\d+)(e[-+]?\d+)?/i.exec(src.slice(i));
    if (numMatch && !/[A-Za-z$]/.test(src[i])) {
      tokens.push({ t: "num", v: Number(numMatch[0]) });
      i += numMatch[0].length;
      continue;
    }
    const refMatch = /^\$?[A-Za-z]{1,3}\$?\d+(?![A-Za-z0-9_(])/.exec(src.slice(i));
    if (refMatch) {
      tokens.push({ t: "ref", v: refMatch[0].replace(/\$/g, "").toUpperCase() });
      i += refMatch[0].length;
      continue;
    }
    const nameMatch = /^[A-Za-z_][A-Za-z0-9_.]*/.exec(src.slice(i));
    if (nameMatch) {
      tokens.push({ t: "name", v: nameMatch[0].toUpperCase() });
      i += nameMatch[0].length;
      continue;
    }
    const two = src.slice(i, i + 2);
    if (["<=", ">=", "<>"].includes(two)) { tokens.push({ t: "op", v: two }); i += 2; continue; }
    if ("+-*/^&%()<>=,:".includes(ch)) { tokens.push({ t: "op", v: ch }); i++; continue; }
    throw new FormulaFailure("#ERROR!");
  }
  return tokens;
}

// ── Parser (AST) ────────────────────────────────────────────────────────────

type Node =
  | { k: "num"; v: number }
  | { k: "str"; v: string }
  | { k: "ref"; ref: string }
  | { k: "range"; from: string; to: string }
  | { k: "un"; op: string; a: Node }
  | { k: "pct"; a: Node }
  | { k: "bin"; op: string; a: Node; b: Node }
  | { k: "call"; name: string; args: Node[] };

class Parser {
  private pos = 0;
  private readonly tokens: Token[];
  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  parse(): Node {
    const node = this.comparison();
    if (this.pos < this.tokens.length) throw new FormulaFailure("#ERROR!");
    return node;
  }
  private peekOp(...ops: string[]): string | null {
    const tok = this.tokens[this.pos];
    return tok && tok.t === "op" && ops.includes(tok.v) ? tok.v : null;
  }
  private comparison(): Node {
    let left = this.concat();
    for (let op = this.peekOp("=", "<>", "<", ">", "<=", ">="); op; op = this.peekOp("=", "<>", "<", ">", "<=", ">=")) {
      this.pos++;
      left = { k: "bin", op, a: left, b: this.concat() };
    }
    return left;
  }
  private concat(): Node {
    let left = this.additive();
    while (this.peekOp("&")) { this.pos++; left = { k: "bin", op: "&", a: left, b: this.additive() }; }
    return left;
  }
  private additive(): Node {
    let left = this.term();
    for (let op = this.peekOp("+", "-"); op; op = this.peekOp("+", "-")) {
      this.pos++;
      left = { k: "bin", op, a: left, b: this.term() };
    }
    return left;
  }
  private term(): Node {
    let left = this.power();
    for (let op = this.peekOp("*", "/"); op; op = this.peekOp("*", "/")) {
      this.pos++;
      left = { k: "bin", op, a: left, b: this.power() };
    }
    return left;
  }
  private power(): Node {
    let left = this.unary();
    while (this.peekOp("^")) { this.pos++; left = { k: "bin", op: "^", a: left, b: this.unary() }; }
    return left;
  }
  private unary(): Node {
    const op = this.peekOp("-", "+");
    if (op) { this.pos++; return { k: "un", op, a: this.unary() }; }
    return this.postfix();
  }
  private postfix(): Node {
    let node = this.primary();
    while (this.peekOp("%")) { this.pos++; node = { k: "pct", a: node }; }
    return node;
  }
  private primary(): Node {
    const tok = this.tokens[this.pos++];
    if (!tok) throw new FormulaFailure("#ERROR!");
    if (tok.t === "num") return { k: "num", v: tok.v };
    if (tok.t === "str") return { k: "str", v: tok.v };
    if (tok.t === "ref") {
      if (this.peekOp(":")) {
        this.pos++;
        const end = this.tokens[this.pos++];
        if (!end || end.t !== "ref") throw new FormulaFailure("#ERROR!");
        return { k: "range", from: tok.v, to: end.v };
      }
      return { k: "ref", ref: tok.v };
    }
    if (tok.t === "name") {
      if (!this.peekOp("(")) {
        if (tok.v === "TRUE" || tok.v === "FALSE") return { k: "call", name: tok.v, args: [] };
        throw new FormulaFailure("#NAME?");
      }
      this.pos++;
      const args: Node[] = [];
      if (!this.peekOp(")")) {
        args.push(this.comparison());
        while (this.peekOp(",")) { this.pos++; args.push(this.comparison()); }
      }
      if (!this.peekOp(")")) throw new FormulaFailure("#ERROR!");
      this.pos++;
      return { k: "call", name: tok.v, args };
    }
    if (tok.t === "op" && tok.v === "(") {
      const inner = this.comparison();
      if (!this.peekOp(")")) throw new FormulaFailure("#ERROR!");
      this.pos++;
      return inner;
    }
    throw new FormulaFailure("#ERROR!");
  }
}

// ── Evaluation ──────────────────────────────────────────────────────────────

const MAX_COLS = 702;
const MAX_ROWS = 10000;

export interface EvaluatedSheet {
  /** Display strings, same shape as the input grid. */
  display: string[][];
  /** Whether the raw cell was a formula. */
  isFormula: boolean[][];
}

export function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return "#VALUE!";
  const rounded = Number(n.toPrecision(12));
  if (Math.abs(rounded) >= 1e15 || (rounded !== 0 && Math.abs(rounded) < 1e-6)) return String(rounded);
  const fixed = rounded.toFixed(4);
  return String(Number(fixed));
}

function toNumber(v: Value): number {
  if (Array.isArray(v)) v = v[0]?.[0] ?? null;
  if (v === null || v === "") return 0;
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? 1 : 0;
  const n = parseNumericText(v);
  if (n === null) throw new FormulaFailure("#VALUE!");
  return n;
}

function toText(v: Value): string {
  if (Array.isArray(v)) v = v[0]?.[0] ?? null;
  if (v === null) return "";
  if (typeof v === "number") return formatNumber(v);
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  return v;
}

function toBool(v: Value): boolean {
  if (Array.isArray(v)) v = v[0]?.[0] ?? null;
  if (typeof v === "boolean") return v;
  if (typeof v === "string") {
    if (v.toUpperCase() === "TRUE") return true;
    if (v.toUpperCase() === "FALSE") return false;
  }
  return toNumber(v) !== 0;
}

/** Numbers found in args; direct args are coerced, range cells only count if numeric. */
function collectNumbers(args: Value[]): number[] {
  const out: number[] = [];
  for (const arg of args) {
    if (Array.isArray(arg)) {
      for (const row of arg) for (const cell of row) {
        if (typeof cell === "number") out.push(cell);
        else if (typeof cell === "string") { const n = parseNumericText(cell); if (n !== null) out.push(n); }
      }
    } else out.push(toNumber(arg));
  }
  return out;
}

function roundTo(value: number, digits: number, mode: "round" | "up" | "down"): number {
  const f = Math.pow(10, Math.trunc(digits));
  const x = value * f;
  const eps = Math.abs(x) * 1e-12;
  let r: number;
  if (mode === "round") r = Math.sign(x) * Math.round(Math.abs(x) + eps);
  else if (mode === "up") r = Math.sign(x) * Math.ceil(Math.abs(x) - eps);
  else r = Math.sign(x) * Math.floor(Math.abs(x) + eps);
  return r / f;
}

type Fn = (args: Value[], rawArgs: Node[], ev: (n: Node) => Value) => Value;

const FUNCTIONS: Record<string, Fn> = {
  SUM: (a) => collectNumbers(a).reduce((s, n) => s + n, 0),
  AVERAGE: (a) => {
    const n = collectNumbers(a);
    if (!n.length) throw new FormulaFailure("#DIV/0!");
    return n.reduce((s, x) => s + x, 0) / n.length;
  },
  MIN: (a) => { const n = collectNumbers(a); return n.length ? Math.min(...n) : 0; },
  MAX: (a) => { const n = collectNumbers(a); return n.length ? Math.max(...n) : 0; },
  COUNT: (a) => collectNumbers(a.map((x) => (Array.isArray(x) ? x : [[x]]))).length,
  ABS: (a) => Math.abs(toNumber(a[0])),
  SQRT: (a) => { const n = toNumber(a[0]); if (n < 0) throw new FormulaFailure("#VALUE!"); return Math.sqrt(n); },
  POWER: (a) => Math.pow(toNumber(a[0]), toNumber(a[1])),
  MOD: (a) => {
    const d = toNumber(a[1]);
    if (d === 0) throw new FormulaFailure("#DIV/0!");
    const n = toNumber(a[0]);
    return n - d * Math.floor(n / d);
  },
  ROUND: (a) => roundTo(toNumber(a[0]), a[1] === undefined ? 0 : toNumber(a[1]), "round"),
  ROUNDUP: (a) => roundTo(toNumber(a[0]), a[1] === undefined ? 0 : toNumber(a[1]), "up"),
  ROUNDDOWN: (a) => roundTo(toNumber(a[0]), a[1] === undefined ? 0 : toNumber(a[1]), "down"),
  CEILING: (a) => {
    const sig = a[1] === undefined ? 1 : toNumber(a[1]);
    return sig === 0 ? 0 : Math.ceil(Number((toNumber(a[0]) / sig).toPrecision(12))) * sig;
  },
  FLOOR: (a) => {
    const sig = a[1] === undefined ? 1 : toNumber(a[1]);
    return sig === 0 ? 0 : Math.floor(Number((toNumber(a[0]) / sig).toPrecision(12))) * sig;
  },
  AND: (a) => a.every((x) => (Array.isArray(x) ? x.flat().every((c) => toBool(c)) : toBool(x))),
  OR: (a) => a.some((x) => (Array.isArray(x) ? x.flat().some((c) => toBool(c)) : toBool(x))),
  NOT: (a) => !toBool(a[0]),
  TRUE: () => true,
  FALSE: () => false,
  CONCAT: (a) => a.map((x) => (Array.isArray(x) ? x.flat().map(toText).join("") : toText(x))).join(""),
  IF: (_a, raw, ev) => {
    if (raw.length < 2) throw new FormulaFailure("#ERROR!");
    if (toBool(ev(raw[0]))) return ev(raw[1]);
    return raw.length > 2 ? ev(raw[2]) : false;
  },
  IFERROR: (_a, raw, ev) => {
    if (raw.length !== 2) throw new FormulaFailure("#ERROR!");
    try { return ev(raw[0]); } catch (e) {
      if (e instanceof FormulaFailure) return ev(raw[1]);
      throw e;
    }
  },
};
// IF / IFERROR evaluate lazily; others get pre-evaluated args.
const LAZY = new Set(["IF", "IFERROR"]);
FUNCTIONS.PRODUCT = (a) => collectNumbers(a).reduce((s, n) => s * n, 1);
FUNCTIONS.COUNTA = (a) => a.reduce<number>((s, x) => s + (Array.isArray(x)
  ? x.flat().filter((c) => c !== null && c !== "").length : 1), 0);
FUNCTIONS.SUMPRODUCT = (a) => {
  const arrays = a.map((x) => (Array.isArray(x) ? x.flat() : [x]));
  const len = arrays[0]?.length ?? 0;
  if (arrays.some((arr) => arr.length !== len)) throw new FormulaFailure("#VALUE!");
  let sum = 0;
  for (let i = 0; i < len; i++) {
    let prod = 1;
    for (const arr of arrays) {
      const c = arr[i];
      const n = typeof c === "number" ? c : typeof c === "string" ? (parseNumericText(c) ?? 0) : 0;
      prod *= n;
    }
    sum += prod;
  }
  return sum;
};

function compare(op: string, a: Scalar, b: Scalar): boolean {
  const an = typeof a === "string" ? parseNumericText(a) : a;
  const bn = typeof b === "string" ? parseNumericText(b) : b;
  let l: number | string | boolean | null = a;
  let r: number | string | boolean | null = b;
  if (an !== null && bn !== null && typeof an !== "string" && typeof bn !== "string") {
    l = Number(an); r = Number(bn);
  } else {
    l = toText(a).toLowerCase(); r = toText(b).toLowerCase();
  }
  switch (op) {
    case "=": return l === r;
    case "<>": return l !== r;
    case "<": return l! < r!;
    case ">": return l! > r!;
    case "<=": return l! <= r!;
    default: return l! >= r!;
  }
}

/**
 * Evaluate a grid of raw cell strings (data rows only; row 1 = first row).
 * Never throws: failures become Excel-style error strings in `display`.
 */
export function evaluateSheet(rawGrid: string[][]): EvaluatedSheet {
  const rowCount = rawGrid.length;
  const colCount = rawGrid.reduce((m, r) => Math.max(m, r.length), 0);
  const cache = new Map<string, Scalar | FormulaFailure>();
  const active = new Set<string>();
  const astCache = new Map<string, Node | FormulaFailure>();

  function parseFormula(raw: string): Node {
    const cached = astCache.get(raw);
    if (cached instanceof FormulaFailure) throw cached;
    if (cached) return cached;
    try {
      const ast = new Parser(tokenize(raw.trim().slice(1))).parse();
      astCache.set(raw, ast);
      return ast;
    } catch (e) {
      const failure = e instanceof FormulaFailure ? e : new FormulaFailure("#ERROR!");
      astCache.set(raw, failure);
      throw failure;
    }
  }

  function refToCoords(ref: string): { row: number; col: number } {
    const m = /^([A-Z]+)(\d+)$/.exec(ref);
    if (!m) throw new FormulaFailure("#REF!");
    const col = columnLettersToIndex(m[1]);
    const row = Number(m[2]) - 1;
    if (row < 0 || col < 0 || row >= MAX_ROWS || col >= MAX_COLS) throw new FormulaFailure("#REF!");
    return { row, col };
  }

  function cellValue(row: number, col: number): Scalar {
    if (row >= rowCount || col >= colCount) return null;
    const key = `${row}:${col}`;
    const hit = cache.get(key);
    if (hit instanceof FormulaFailure) throw hit;
    if (hit !== undefined) return hit;
    const raw = rawGrid[row]?.[col] ?? "";
    if (!isFormulaText(raw)) {
      const n = parseNumericText(raw);
      const value: Scalar = n !== null ? n : raw === "" ? null : raw;
      cache.set(key, value);
      return value;
    }
    if (active.has(key)) throw new FormulaFailure("#CIRC!");
    active.add(key);
    try {
      const result = evalNode(parseFormula(raw));
      const scalar: Scalar = Array.isArray(result) ? (result[0]?.[0] ?? null) : result;
      cache.set(key, scalar);
      return scalar;
    } catch (e) {
      const failure = e instanceof FormulaFailure ? e : new FormulaFailure("#ERROR!");
      cache.set(key, failure);
      throw failure;
    } finally {
      active.delete(key);
    }
  }

  function evalNode(node: Node): Value {
    switch (node.k) {
      case "num": return node.v;
      case "str": return node.v;
      case "ref": { const { row, col } = refToCoords(node.ref); return cellValue(row, col); }
      case "range": {
        const a = refToCoords(node.from);
        const b = refToCoords(node.to);
        const out: Scalar[][] = [];
        const lastRow = Math.min(Math.max(a.row, b.row), rowCount - 1);
        const lastCol = Math.min(Math.max(a.col, b.col), colCount - 1);
        for (let r = Math.min(a.row, b.row); r <= lastRow; r++) {
          const line: Scalar[] = [];
          for (let c = Math.min(a.col, b.col); c <= lastCol; c++) line.push(cellValue(r, c));
          out.push(line);
        }
        return out;
      }
      case "un": { const n = toNumber(evalNode(node.a)); return node.op === "-" ? -n : n; }
      case "pct": return toNumber(evalNode(node.a)) / 100;
      case "bin": {
        if (node.op === "&") return toText(evalNode(node.a)) + toText(evalNode(node.b));
        const l = evalNode(node.a);
        const r = evalNode(node.b);
        if (["=", "<>", "<", ">", "<=", ">="].includes(node.op)) {
          const ls = Array.isArray(l) ? (l[0]?.[0] ?? null) : l;
          const rs = Array.isArray(r) ? (r[0]?.[0] ?? null) : r;
          return compare(node.op, ls, rs);
        }
        const x = toNumber(l);
        const y = toNumber(r);
        switch (node.op) {
          case "+": return x + y;
          case "-": return x - y;
          case "*": return x * y;
          case "/": if (y === 0) throw new FormulaFailure("#DIV/0!"); return x / y;
          default: {
            const p = Math.pow(x, y);
            if (!Number.isFinite(p)) throw new FormulaFailure("#VALUE!");
            return p;
          }
        }
      }
      case "call": {
        const fn = FUNCTIONS[node.name];
        if (!fn) throw new FormulaFailure("#NAME?");
        const args = LAZY.has(node.name) ? [] : node.args.map(evalNode);
        return fn(args, node.args, evalNode);
      }
    }
  }

  const display: string[][] = [];
  const isFormula: boolean[][] = [];
  for (let r = 0; r < rowCount; r++) {
    const line: string[] = [];
    const flags: boolean[] = [];
    for (let c = 0; c < (rawGrid[r]?.length ?? 0); c++) {
      const raw = rawGrid[r][c] ?? "";
      const formula = isFormulaText(raw);
      flags.push(formula);
      if (!formula) { line.push(raw); continue; }
      try {
        const v = cellValue(r, c);
        line.push(typeof v === "number" ? formatNumber(v) : toText(v));
      } catch (e) {
        line.push(e instanceof FormulaFailure ? e.code : "#ERROR!");
      }
    }
    display.push(line);
    isFormula.push(flags);
  }
  return { display, isFormula };
}
