const defaultProps = {
  suggestions: ['Explain the idea simply.', 'Compare their approaches.', 'Show a practical example.', 'Test my understanding.'],
  onSuggestionClick: (suggestion: string) => document.dispatchEvent(new CustomEvent('preview-follow-up', { detail: suggestion })),
};

export default defaultProps;
export const variants = {
  disabled: { ...defaultProps, disabled: true },
  filtering: { ...defaultProps, messageInputContent: 'Compare' },
};
