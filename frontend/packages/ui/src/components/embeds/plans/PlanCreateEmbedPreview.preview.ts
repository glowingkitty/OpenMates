/**
 * Preview fixture for the plans.create skill card (draft Plan, empty lists).
 * Design to refine: reuses the shared Plan card unchanged.
 */
export const planCreateContent = {
  title: 'Launch the household shopping app',
  summary: 'Plan the first public release of the shared shopping lists.',
  goal: 'Households can create, share and tick off a shopping list, verified by checks before release.',
  request_id: 'preview-plan-request', chat_id: 'preview-chat',
};

export default { id: 'preview-plan-create', data: planCreateContent, onFullscreen: () => {} };
