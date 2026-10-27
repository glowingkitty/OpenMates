/** Identify the assistant response affected by one embed delivery. */
export function embedUpdateTargetIds(
  messages: ReadonlyArray<{
    message_id: string;
    user_message_id?: string | null;
    role?: string;
    status?: string;
    content?: unknown;
  }>,
  event: { message_id?: string; task_id?: string; embed_id?: string },
): Set<string> {
  const assistants = messages.filter(message => message.role === 'assistant');
  const linked = assistants.filter(message =>
    (event.message_id && (message.message_id === event.message_id || message.user_message_id === event.message_id)) ||
    (event.task_id && message.message_id === event.task_id),
  );
  if (linked.length) return new Set(linked.map(message => message.message_id));
  const referenced = event.embed_id ? assistants.filter(message => {
    const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? '');
    return content.includes(event.embed_id!);
  }) : [];
  return new Set(referenced.map(message => message.message_id));
}
