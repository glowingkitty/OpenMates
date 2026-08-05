// frontend/packages/ui/src/services/__tests__/embedRefIndex.test.ts
// Verifies that the in-memory encrypted embed-ref index publishes only changes.
// Repeated decrypt reads may register identical mappings and must stay silent.
// Changed aliases or metadata still notify rendering subscribers.
// The index remains process-local and stores no decrypted embed content.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearEmbedRefIndexEntries,
  embedRefIndexVersion,
  registerEmbedRefIndex,
  resolveEmbedRefIndexEntry,
} from "../embedRefIndex";

describe("embedRefIndexVersion", () => {
  beforeEach(clearEmbedRefIndexEntries);
  afterEach(clearEmbedRefIndexEntries);

  it("does not publish identical ref registrations", () => {
    let notifications = 0;
    const unsubscribe = embedRefIndexVersion.subscribe(() => {
      notifications += 1;
    });
    const baseline = notifications;
    const entry = {
      embedId: "event-1",
      appId: "events",
      skillId: "search",
      type: "event",
    };

    registerEmbedRefIndex("event-one-A1b", entry);
    registerEmbedRefIndex("event-one-A1b", { ...entry });

    expect(notifications).toBe(baseline + 1);
    unsubscribe();
  });

  it("publishes and resolves new aliases", () => {
    let notifications = 0;
    const unsubscribe = embedRefIndexVersion.subscribe(() => {
      notifications += 1;
    });
    const baseline = notifications;
    const entry = {
      embedId: "event-1",
      appId: "events",
      skillId: "search",
      type: "event",
    };

    registerEmbedRefIndex("event-one-A1b", entry);
    registerEmbedRefIndex("event-one-alias", entry);

    expect(notifications).toBe(baseline + 2);
    expect(resolveEmbedRefIndexEntry("event-one-alias")).toEqual(entry);
    expect(resolveEmbedRefIndexEntry("event-1")).toEqual(entry);
    unsubscribe();
  });

  it("publishes changes to each metadata field", () => {
    let notifications = 0;
    const unsubscribe = embedRefIndexVersion.subscribe(() => {
      notifications += 1;
    });
    const baseline = notifications;

    registerEmbedRefIndex("event-one-A1b", {
      embedId: "event-1",
      appId: "events",
      skillId: "search",
      type: "event",
    });
    registerEmbedRefIndex("event-one-A1b", {
      embedId: "event-1",
      appId: "calendar",
      skillId: "search",
      type: "event",
    });
    registerEmbedRefIndex("event-one-A1b", {
      embedId: "event-1",
      appId: "calendar",
      skillId: "lookup",
      type: "event",
    });
    const finalEntry = {
      embedId: "event-1",
      appId: "calendar",
      skillId: "lookup",
      type: "event-result",
    };
    registerEmbedRefIndex("event-one-A1b", finalEntry);

    expect(notifications).toBe(baseline + 4);
    expect(resolveEmbedRefIndexEntry("event-one-A1b")).toEqual(finalEntry);
    expect(resolveEmbedRefIndexEntry("event-1")).toEqual(finalEntry);
    unsubscribe();
  });

  it("remaps readable refs without removing stable ID aliases", () => {
    const firstEntry = {
      embedId: "event-1",
      appId: "events",
      skillId: "search",
      type: "event",
    };
    const secondEntry = { ...firstEntry, embedId: "event-2" };

    registerEmbedRefIndex("event-one-A1b", firstEntry);
    registerEmbedRefIndex("event-one-A1b", secondEntry);

    expect(resolveEmbedRefIndexEntry("event-one-A1b")).toEqual(secondEntry);
    expect(resolveEmbedRefIndexEntry("event-1")).toEqual(firstEntry);
    expect(resolveEmbedRefIndexEntry("event-2")).toEqual(secondEntry);
  });
});
