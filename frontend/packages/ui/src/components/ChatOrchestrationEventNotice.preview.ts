/**
 * Fictional chat orchestration events for the notice; no account, chat or inference is used.
 * Default is a started event; `variant` selects started, report, sent, reported, finished, waiting_for_user, user_wrote.
 */
const base = { chat_id: 'preview-spawned-chat', title: 'Kitchen tile quotes', text: null, event_id: 'preview-event', created_at: 1_760_000_000 };
const mock = (action: string, text: string | null = null) => ({ event: { ...base, action, text }, onOpen: () => {} });
export default mock('started');
export const variants = {
  report: mock('report', 'Three kinds of kitchen floor tiles: porcelain is hard-wearing and water-resistant; ceramic is affordable and easy to cut; natural stone is durable but needs sealing.'),
  sent: mock('sent', 'Please compare porcelain and ceramic prices for a 12 square metre floor.'),
  reported: mock('reported', 'Porcelain is the best fit: about 45 euro per square metre, water-resistant.'),
  finished: mock('finished'),
  waiting_for_user: mock('waiting_for_user'),
  user_wrote: mock('user_wrote'),
};
