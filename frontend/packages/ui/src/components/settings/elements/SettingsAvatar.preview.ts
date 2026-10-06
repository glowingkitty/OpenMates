/** Neutral account avatar remains the default settings appearance. */
export default { size: 'lg', ariaLabel: 'Account avatar' };

export const variants = {
  generated: {
    size: 'lg', ariaLabel: 'Alex team avatar',
    generatedIcon: 'mate', generatedBackground: '#8b62c9',
  },
  unsafe: {
    size: 'lg', ariaLabel: 'Fallback team avatar',
    generatedIcon: '../other', generatedBackground: 'url(javascript:alert(1))',
  },
};
