/**
 * Preview fixture for the plans.specification skill card (unsaved draft).
 * Design to refine: reuses the shared Specification card unchanged.
 * Synthetic data only; open /dev/preview/embeds/specifications/SpecificationSkillEmbedPreview.
 */
export const specificationSkillContent = {
  type: 'specification', title: 'Shared shopping lists', category: 'Feature',
  summary: 'Households keep one shopping list that everyone can edit together.',
  outcome: 'Members of a household add, tick off and remove items on the same list and see changes right away.',
  scope: { included: ['Adding, ticking off and removing items.', 'Inviting household members.'], excluded: ['Price tracking.', 'Store integrations.'] },
  requirements: [
    { id: 'shared-lists.items.add', statement: 'A member can add an item that every other member sees.', example: 'Ana adds "Oat milk" and Ben sees it.' },
    { id: 'shared-lists.items.tick', statement: 'A ticked item moves to a done section.' },
    { id: 'shared-lists.members.invite', statement: 'Only the list owner can invite members.' },
  ],
  flows: [
    { id: 'add-item', title: 'Add an item', kind: 'user_flow', steps: ['Open the list', 'Type an item name', 'Confirm'] },
    { id: 'invite-denied', title: 'Non-owner invites a member', kind: 'edge_case', steps: ['Open the list as a member', 'Try to invite someone', 'See that inviting is not allowed'] },
  ],
  chat_id: 'preview-chat',
};

export default { id: 'preview-specification-skill', data: specificationSkillContent, isMobile: false, onFullscreen: () => {} };
