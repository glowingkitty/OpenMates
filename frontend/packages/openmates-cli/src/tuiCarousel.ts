/** Shared centered card viewport for the terminal Chats and Apps homes. */
import { cells, padCells, sliceCells, truncateCells, wrapCells, type TuiLine, type TuiSpan } from "./tuiText.js";

export type TuiCarouselCard = { title: string; description: string; footer: string; background: string };

export function renderCardCarousel(cards: TuiCarouselCard[], width: number, selectedIndex: number, focused: boolean): TuiLine[] {
  width = Math.max(1, Math.floor(width));
  if (!cards.length) return [];
  const selected = Math.max(0, Math.min(cards.length - 1, selectedIndex));
  const cardWidth = Math.min(width, 36), inner = Math.max(1, cardWidth - 4), stride = cardWidth + 2;
  const center = Math.floor((width - cardWidth) / 2);
  const reach = Math.ceil(width / stride);
  const visible = cards.slice(Math.max(0, selected - reach), selected + reach + 1).map((card, offset) => {
    const index = Math.max(0, selected - reach) + offset, active = index === selected && focused;
    const title = wrapCells(`${active ? "› " : ""}${card.title}`, inner).slice(0, 2);
    const description = wrapCells(card.description, inner).slice(0, 2);
    while (title.length < 2) title.push("");
    while (description.length < 2) description.push("");
    const rows = cardWidth < 4 ? [truncateCells(card.title, cardWidth)] : [
      `╭${"─".repeat(cardWidth - 2)}╮`,
      ...title.map((line) => `│ ${padCells(line, inner)} │`),
      ...description.map((line) => `│ ${padCells(line, inner)} │`),
      `│ ${padCells(card.footer, inner)} │`,
      `╰${"─".repeat(cardWidth - 2)}╯`,
    ];
    return { rows, left: center + (index - selected) * stride, background: card.background, active };
  });
  return Array.from({ length: visible[0].rows.length }, (_, row) => {
    const spans: TuiSpan[] = []; let column = 0;
    for (const card of visible) {
      const start = Math.max(0, card.left), end = Math.min(width, card.left + cardWidth);
      if (end <= start) continue;
      if (start > column) spans.push({ text: " ".repeat(start - column) });
      spans.push({ text: sliceCells(card.rows[row], Math.max(0, -card.left), end - start), background: card.background, bold: card.active });
      column = end;
    }
    if (column < width) spans.push({ text: " ".repeat(width - column) });
    return { text: spans.map((span) => span.text).join(""), spans };
  });
}

export function centeredCarouselText(text: string, width: number): string {
  const value = truncateCells(text, width);
  return " ".repeat(Math.max(0, Math.floor((width - cells(value)) / 2))) + value;
}
