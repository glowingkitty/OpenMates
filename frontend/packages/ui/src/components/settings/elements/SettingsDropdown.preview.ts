const richOptions = [
  { value: 'weather', label: 'Weather | Get forecast', iconStyle: '--workflow-icon:var(--icon-url-weather)', iconBackground: 'var(--color-app-weather, #078fba)' },
  { value: 'ai', label: 'AI confirms', iconStyle: '--workflow-icon:var(--icon-url-ai)', iconBackground: 'var(--color-app-ai, #ce6858)' },
  { value: 'greater', label: 'is more than', iconText: '>', iconBackground: 'var(--color-error, #9f0f2a)' },
  { value: 'number', label: 'Number', iconText: '√x', iconBackground: 'var(--color-error, #9f0f2a)' },
];

const props = {
  rich: true,
  value: 'weather',
  options: richOptions,
  ariaLabel: 'Workflow check source',
  dataTestid: 'preview-rich-dropdown',
  onChange: (_value: string) => {},
};

export default props;
export const variants = {
  placeholder: { ...props, value: '', placeholder: 'Select a source' },
  native: { ...props, rich: false },
};
