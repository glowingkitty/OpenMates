// frontend/packages/ui/src/services/anonymousChatPromotionPlan.ts
// Decision part of anonymous chat promotion after signup: which messages are
// uploaded, which system rows are dropped, which rows are re-saved as synced and
// the version/timestamp numbers of the promoted chat row. With
// VITE_OPENMATES_RUST_CORE=1 the shared Rust core (web_guest, crypto unit)
// decides; flag-off builds run the original TypeScript rules below. The service
// (anonymousChatPromotionService.ts) only performs the IO the plan describes.

import { rustWebCrypto } from "./rustCore/crypto/webCryptoClient";
import { guestPromotionPlan } from "./rustCore/crypto/guestOps";
import type { Chat, Message } from "../types/chat";

export interface PromotionPlan {
  promotable: Message[];
  toDelete: Message[];
  toResave: Message[];
  messagesV: number;
  createdAt: number | undefined;
  lastEditedAt: number | undefined;
}

export function isPromotableMessage(message: Message): boolean {
  return (
    message.status !== "failed" &&
    message.role !== "system" &&
    typeof message.content === "string" &&
    message.content.trim().length > 0
  );
}

function planInTypeScript(chat: Chat, messages: Message[]): PromotionPlan {
  const promotable = messages.filter(isPromotableMessage);
  return {
    promotable,
    toDelete: messages.filter((message) => message.role === "system"),
    toResave: promotable.filter((message) => message.status !== "synced"),
    messagesV: promotable.length,
    createdAt: chat.created_at ?? promotable[0]?.created_at,
    lastEditedAt: promotable[promotable.length - 1]?.created_at ?? chat.updated_at,
  };
}

export async function planPromotion(chat: Chat, messages: Message[]): Promise<PromotionPlan> {
  const rust = import.meta.env.VITE_OPENMATES_RUST_CORE === "1" ? rustWebCrypto() : null;
  if (!rust) return planInTypeScript(chat, messages);
  const plan = await guestPromotionPlan(rust, chat, messages);
  const pick = (indexes: number[]) => indexes.map((index) => messages[index]);
  return {
    promotable: pick(plan.promotable),
    toDelete: pick(plan.delete),
    toResave: pick(plan.resave),
    messagesV: plan.messages_v,
    createdAt: plan.created_at ?? undefined,
    lastEditedAt: plan.last_edited ?? undefined,
  };
}
