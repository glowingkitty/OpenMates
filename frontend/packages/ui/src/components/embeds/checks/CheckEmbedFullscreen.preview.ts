/** Preview mock data for CheckEmbedFullscreen. */
import { failedRequiredUnit, neverRun, passedMixed, running, stale, storedHumanSource, waitingForConfirmation } from './checkFixtures';

const fixture = (check: typeof passedMixed) => ({
  check,
  embedId: 'preview-check-1',
  onClose: () => console.log('[Preview] close'),
  onRun: () => console.log('[Preview] run'),
  onCancel: () => console.log('[Preview] cancel'),
  onConfirm: (bindingId: string, decision: string) => console.log('[Preview] confirm', bindingId, decision),
  onSelectRun: (runId: string) => console.log('[Preview] select run', runId),
  onOpenTestResult: (embedId: string) => console.log('[Preview] open test result', embedId),
});

const defaultProps = fixture(passedMixed);

export default defaultProps;

const planTasks = [
  { taskId: 'task-pay', title: 'Build the payment step', description: 'Covers: A shopper can pay', status: 'in_progress', linkedSubChatId: 'preview-chat-task-pay' },
  { taskId: 'task-docs', title: 'Update the help page', description: 'Unrelated documentation', status: 'todo', linkedSubChatId: 'preview-chat-task-docs' },
];

export const variants = {
  'with-plan-tasks': { ...fixture(passedMixed), planTasks, onOpenChat: (chatId: string) => { (window as unknown as { __openedChat?: string }).__openedChat = chatId; } },
  failedRequiredUnit: fixture(failedRequiredUnit),
  waitingForConfirmation: fixture(waitingForConfirmation),
  stale: fixture(stale),
  neverRun: fixture(neverRun),
  running: fixture(running),
  storedHumanSource: fixture(storedHumanSource),
};
