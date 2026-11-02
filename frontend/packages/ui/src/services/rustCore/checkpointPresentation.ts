/** Optional rendering only for a closed shared-Rust checkpoint presentation.
 * Rust chooses the checkpoint, decrypts it and decides summary availability.
 * This module never reads storage, restores PII, selects rows or retries crypto.
 * Missing/corrupt/not-loaded summaries stay distinct and retain checkpoint IDs.
 * Labels come from the page's existing i18n layer; content is DOM text only.
 * No production caller, ActiveChat writer or global activation is installed.
 */
import {validCheckpointPresentation} from "./savedReadProtocol";
import type {CheckpointPresentation} from "./savedReadProtocol";
export function renderLocalCheckpointSummary(input:CheckpointPresentation,chatId:string,container:HTMLElement,
  labels:Readonly<{missing:string;unavailable:string;notLoaded:string}>):void{
  if(!validCheckpointPresentation(input,chatId))throw Error("unavailable");
  const row=input.checkpoint;container.replaceChildren();if(!row)return;
  const element=container.ownerDocument.createElement("p");element.dataset.checkpointId=row.id;element.dataset.summaryState=row.summaryState;
  element.textContent=row.summaryState==="loaded"?row.summary:row.summaryState==="missing"?labels.missing:row.summaryState==="not_loaded"?labels.notLoaded:labels.unavailable;
  container.append(element);
}
