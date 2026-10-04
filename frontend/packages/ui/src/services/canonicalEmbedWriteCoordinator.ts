/** Serialize all canonical writes for one embed through their durable receipts. */
const tails = new Map<string, Promise<void>>();
const activeLeases = new WeakSet<object>();
const leaseBrand = Symbol("canonical embed write lease");
const acknowledgedRecovery = new Map<string, { chatId: string; version: number }>();

export type CanonicalEmbedWriteLease = {
  readonly embedId: string;
  readonly [leaseBrand]: true;
};

export function assertCanonicalEmbedWriteLease(
  lease: CanonicalEmbedWriteLease | undefined,
  embedId: string,
): asserts lease is CanonicalEmbedWriteLease {
  if (!lease || lease.embedId !== embedId || !activeLeases.has(lease)) {
    throw new Error("Canonical embed write lease was missing or expired.");
  }
}

export function markAcknowledgedRecoveredEmbed(
  lease: CanonicalEmbedWriteLease, chatId: string, version: number,
): void {
  assertCanonicalEmbedWriteLease(lease, lease.embedId);
  const previous = acknowledgedRecovery.get(lease.embedId);
  if (!previous || previous.chatId !== chatId || previous.version < version) {
    acknowledgedRecovery.set(lease.embedId, { chatId, version });
  }
}

export function hasAcknowledgedRecoveredEmbed(
  lease: CanonicalEmbedWriteLease, chatId: string, version: number,
): boolean {
  assertCanonicalEmbedWriteLease(lease, lease.embedId);
  const acknowledged = acknowledgedRecovery.get(lease.embedId);
  return acknowledged?.chatId === chatId && acknowledged.version >= version;
}

export async function withCanonicalEmbedWrite<T>(
  embedId: string,
  write: (lease: CanonicalEmbedWriteLease) => Promise<T>,
): Promise<T> {
  if (!embedId) throw new Error("Canonical embed write requires an embed ID.");
  const previous = tails.get(embedId) ?? Promise.resolve();
  const run = previous.catch(() => undefined).then(async () => {
    const lease = { embedId, [leaseBrand]: true } as const;
    activeLeases.add(lease);
    try {
      return await write(lease);
    } finally {
      activeLeases.delete(lease);
    }
  });
  const settled = run.then(() => undefined, () => undefined);
  tails.set(embedId, settled);
  try {
    return await run;
  } finally {
    if (tails.get(embedId) === settled) tails.delete(embedId);
  }
}
