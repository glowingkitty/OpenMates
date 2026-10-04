const phases = [
  { id: 'understand', title: 'Understand your situation', instructions: 'Ask at least five questions by default, one per round with examples and a recommendation. Honor requests to skip remaining questions or ask them all at once.', requirements: [{ id: 'context', text: 'The goal is understood, or the user asks to proceed with available information.' }] },
  { id: 'confirm', title: 'Confirm your career profile', instructions: 'Summarize the profile and ask for confirmation or corrections.', requirements: [{ id: 'approval', text: 'The user confirms the profile or explicitly asks to skip confirmation.', type: 'user_confirmation' as const }] },
];
export default { phases };
export const variants = { long: { phases: [...phases, ...phases.map(p => ({ ...p, id: `${p.id}-2` }))] } };
