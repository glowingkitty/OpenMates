type TransactionStepLike = { toJSON(): unknown };

export type ComposerTransactionLike = {
  docChanged: boolean;
  steps: readonly TransactionStepLike[];
};

function collectInsertedText(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  let text = typeof record.text === "string" ? record.text : "";
  if (Array.isArray(record.content)) {
    for (const child of record.content) text += collectInsertedText(child);
  }
  if (record.slice) text += collectInsertedText(record.slice);
  return text;
}

/**
 * Return true only when the current editor transaction inserted a parsing
 * boundary. Looking at the final character of the whole document is incorrect:
 * editing before a trailing period or space would otherwise force a full parse
 * after every keystroke.
 */
export function transactionInsertedTriggerCharacter(
  transaction: ComposerTransactionLike,
  triggerCharacters: ReadonlySet<string>,
): boolean {
  if (!transaction.docChanged) return false;
  return transaction.steps.some((step) => {
    const insertedText = collectInsertedText(step.toJSON());
    return Array.from(insertedText).some((character) => triggerCharacters.has(character));
  });
}
