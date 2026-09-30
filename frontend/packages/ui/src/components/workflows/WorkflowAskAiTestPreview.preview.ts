const response = 'The weather briefing is ready.\n\n- **Monday:** Mild and clear\n- **Tuesday:** Bring a raincoat\n\nRead the [forecast](https://example.com/forecast) for details.';

export default { content: response, processing: false, error: '' };

export const variants = {
  streaming: { content: 'The weather briefing is ready.\n\n- **Monday:** Mild and clear\n- **Tuesday:**', processing: true, error: '' },
  error: { content: '', processing: false, error: 'The test response could not be completed.' },
  empty: { content: '', processing: false, error: '' },
};
