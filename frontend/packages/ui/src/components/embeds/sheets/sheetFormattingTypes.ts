/** Formatting transported with an existing sheet. A1 addresses include its header row. */
export type SheetNumberFormat =
  | { kind: "number" | "percent"; decimals?: number }
  | { kind: "currency"; currency: string; decimals?: number }
  | { kind: "date"; pattern: SheetDatePattern };

export type SheetDatePattern = "yyyy-mm-dd" | "mm/dd/yyyy" | "dd/mm/yyyy" | "mmm d, yyyy";
export type SheetBorderSide = "top" | "right" | "bottom" | "left";

export interface SheetBorder {
  style: "thin" | "medium" | "thick" | "dashed" | "dotted" | "double";
  color: string;
}

export interface SheetCellStyle {
  backgroundColor?: string;
  textColor?: string;
  fontFamily?: string;
  fontSize?: number;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  horizontalAlign?: "left" | "center" | "right";
  verticalAlign?: "top" | "middle" | "bottom";
  wrap?: boolean;
  numberFormat?: SheetNumberFormat;
  borders?: Partial<Record<SheetBorderSide, SheetBorder>>;
}

export interface SheetFormatting {
  columnWidths?: Record<string, number>;
  rowHeights?: Record<string, number>;
  cells?: Record<string, SheetCellStyle>;
  merges?: Array<{ start: string; end: string }>;
  frozenRows?: number;
  frozenColumns?: number;
}
