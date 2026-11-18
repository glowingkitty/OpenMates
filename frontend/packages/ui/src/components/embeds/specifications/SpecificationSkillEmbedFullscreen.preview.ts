/** Fullscreen fixture for the plans.specification skill result. Design to refine: shared reader as is. */
import { specificationSkillContent } from './SpecificationSkillEmbedPreview.preview';

/** A Specification drafted by the guided Write specification focus: role, open assumptions, design and links. */
const guidedContent = {
  type: 'specification', title: 'Online sourdough ordering', category: 'Feature', role: 'product',
  summary: 'Customers order a sourdough loaf online and pick it up at the bakery.',
  outcome: 'A customer picks a loaf, chooses a pickup day and pays online in under two minutes.',
  scope: { included: ['Choosing a loaf and a pickup day.', 'Paying online.'], excluded: ['Delivery.', 'Wholesale orders.'] },
  requirements: [
    { id: 'R1', statement: 'A customer sees only loaves that can still be baked for the chosen pickup day.', example: 'Rye is sold out for Saturday, so it is not offered.' },
    { id: 'R2', statement: 'An order is confirmed only after the payment succeeded.' },
  ],
  flows: [{ id: 'order', title: 'Order a loaf', kind: 'user_flow', steps: ['Pick a loaf', 'Choose a pickup day', 'Pay'] }],
  assumptions: ['Pickup only, no delivery in the first version.', 'Orders close at 6 pm the day before pickup.'],
  design_decisions: ['One-page order form: loaf, pickup day, payment (R1, R2).', 'Pickup days shown as a two-week calendar strip.'],
  related_specifications: [{ title: 'Online sourdough ordering - technical', role: 'technical', relation: 'Payments and the daily baking capacity' }],
  chat_id: 'preview-chat',
};

export default { data: { decodedContent: specificationSkillContent }, onClose: () => {} };

export const variants = {
  guided: { data: { decodedContent: guidedContent }, onClose: () => {} },
};
