/** Discoverable workspace actions shared by the palette and input completion. */
export const TUI_ACTIONS = [
  { label: "Stop active response", command: "/stop" },
  { label: "Retry last message", command: "/retry" },
  { label: "New chat", command: "/new" },
  { label: "Open daily inspiration", command: "/inspiration" },
  { label: "Create workflow", command: "/workflow-create" },
  { label: "Next daily inspiration", command: "/inspiration-next" },
  { label: "Show all workspace items", command: "/browse" },
  { label: "Use selected app skill", command: "/app-run" },
  { label: "Recent chats", command: "/chats" },
  { label: "Example chats", command: "/examples" },
  { label: "Projects", command: "/projects" },
  { label: "Tasks", command: "/tasks" },
  { label: "Workflows", command: "/workflows" },
  { label: "Apps", command: "/apps" },
  { label: "App results", command: "/app-results" },
  { label: "Toggle sidebar", command: "/sidebar" },
  { label: "Create task", command: "/task-create" },
  { label: "Edit selected task", command: "/task-edit" },
  { label: "Move selected task", command: "/task-status" },
  { label: "Add task activity", command: "/task-activity" },
  { label: "Create Project", command: "/project-create" },
  { label: "New chat in Project", command: "/project-chat" },
  { label: "Edit workflow step", command: "/workflow-edit" },
  { label: "Enable or disable workflow", command: "/workflow-toggle" },
  { label: "Run workflow now", command: "/workflow-run" },
  { label: "Refresh workspace", command: "/refresh" },
  { label: "Sign in", command: "/login" },
  { label: "Help", command: "/help" },
  { label: "Exit", command: "/exit" },
];
export function paletteActions(query: string) {
  const needle = query.trim().toLowerCase();
  return TUI_ACTIONS.filter((item) => `${item.label} ${item.command}`.toLowerCase().includes(needle));
}
