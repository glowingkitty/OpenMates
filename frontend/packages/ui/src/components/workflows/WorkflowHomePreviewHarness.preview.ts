export default { greetingName: 'there' };
export const layout = 'fill';
export const variants = {
	empty: { greetingName: 'there', empty: true },
	guest: { greetingName: 'there', guest: true },
	// Start-screen suggestion placement, variant B (input-width, centred, left-aligned); default is variant A.
	suggestionsInputWidth: { greetingName: 'there', suggestionsVariant: 'input-width' }
};
