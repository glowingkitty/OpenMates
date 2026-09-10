/**
 * Fictional contact text for inspecting inline sensitive-data controls.
 * Uses reserved example values only and never contacts external services.
 * The parent owns toggling; this isolated fixture leaves its callback inert.
 * Hidden and revealed states are selected through the preview URL.
 * Actual synchronization is reviewed in the shared plumber chat.
 */
const mapping = { placeholder: '[EMAIL_1_com]', original: 'hello@example.com', type: 'EMAIL' };
export default { value: 'Contact me at [EMAIL_1_com].', mappings: [mapping], revealed: false, onToggle: () => {} };
export const variants = { revealed: { value: 'Contact me at hello@example.com.', revealed: true } };
