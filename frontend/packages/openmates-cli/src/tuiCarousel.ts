/** Shared centered card viewport for the terminal Chats and Apps homes. */
import { cells, lineText, padCells, sliceCells, truncateCells, wrapCells, type TuiLine, type TuiSpan } from "./tuiText.js";

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

/** The same centered viewport for rich embed cards, retaining their own colors. */
export function renderLineCarousel(cards:TuiLine[][],width:number,selectedIndex:number,focused:boolean,cardWidth:number):TuiLine[] {
  if(!cards.length)return [];
  width=Math.max(1,Math.floor(width));cardWidth=Math.min(width,cardWidth);
  const selected=Math.max(0,Math.min(cards.length-1,selectedIndex));
  const stride=cardWidth+2,center=Math.floor((width-cardWidth)/2);
  const visible=cards.map((rows,index)=>({rows,left:center+(index-selected)*stride,active:focused&&index===selected}))
    .filter(card=>card.left<width&&card.left+cardWidth>0);
  const height=Math.max(...visible.map(card=>card.rows.length));
  return Array.from({length:height},(_,row)=>{
    const spans:TuiSpan[]=[];let column=0;
    for(const card of visible){
      const start=Math.max(0,card.left),end=Math.min(width,card.left+cardWidth);
      if(start>column)spans.push({text:' '.repeat(start-column)});
      let line=card.rows[row]??'';
      if(card.active&&row===1){
        const raw=lineText(line),text=raw.startsWith('│ ')?`│ › ${padCells(raw.slice(2,-2),Math.max(0,cardWidth-6))} │`:padCells('› '+raw,cardWidth);
        line=typeof line==='string'?{text,bold:true,color:'#ff553b'}:{...line,text,bold:true,spans:line.spans?[{...line.spans[0],text,bold:true}]:undefined};
      }
      const source=typeof line==='string'?[{text:line}]:line.spans??[{text:line.text,color:line.color,background:line.background,bold:line.bold}];
      let offset=0,used=0;
      const cropStart=Math.max(0,-card.left),cropEnd=cropStart+end-start;
      for(const part of source){
        const size=cells(part.text),from=Math.max(cropStart,offset),to=Math.min(cropEnd,offset+size);
        if(to>from){spans.push({...part,text:sliceCells(part.text,from-offset,to-from)});used+=to-from;}
        offset+=size;
      }
      if(used<end-start)spans.push({text:' '.repeat(end-start-used)});
      column=end;
    }
    if(column<width)spans.push({text:' '.repeat(width-column)});
    return {text:spans.map(part=>part.text).join(''),spans};
  });
}
