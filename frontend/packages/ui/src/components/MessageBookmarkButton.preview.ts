/** Private bookmark control; exercised interactively inside the timeline harness. */
const props = { active: false, onToggle: async () => {} };
export default props;
export const variants = { active: { ...props, active: true }, unavailable: { ...props, onToggle: async () => { throw new Error('Fictional offline save'); } } };
