export interface ProcessingFeedbackTurnIdentity {
  taskId: string;
  userMessageId: string;
}

export interface ProcessingFeedbackTerminalIdentity {
  taskId?: string;
  userMessageId?: string;
}

export function matchesProcessingFeedbackTerminal(
  feedbackTurn: ProcessingFeedbackTurnIdentity | null,
  terminal: ProcessingFeedbackTerminalIdentity,
): boolean {
  const hasTaskId = typeof terminal.taskId === "string" && terminal.taskId.length > 0;
  const hasUserMessageId = typeof terminal.userMessageId === "string" && terminal.userMessageId.length > 0;

  if (!feedbackTurn || (!hasTaskId && !hasUserMessageId)) return false;

  return (!hasTaskId || terminal.taskId === feedbackTurn.taskId)
    && (!hasUserMessageId || terminal.userMessageId === feedbackTurn.userMessageId);
}
