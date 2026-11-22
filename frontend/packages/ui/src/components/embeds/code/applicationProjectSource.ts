// frontend/packages/ui/src/components/embeds/code/applicationProjectSource.ts
//
// A Project app's application card is built in the chat's Project sandbox, so it
// carries a Project name and folder instead of chat files. Renderers read those
// card facts from the decoded embed content here.

export interface ApplicationProjectSource {
  projectName: string;
  cwd: string;
}

/** Card facts of a Project-sandbox application embed, or null for a chat-file app. */
export function applicationProjectSource(
  content: Record<string, unknown> | null | undefined,
): ApplicationProjectSource | null {
  if (!content || content.source !== 'project_sandbox') return null;
  return {
    projectName: typeof content.project_name === 'string' ? content.project_name : '',
    cwd: typeof content.cwd === 'string' ? content.cwd : '',
  };
}
