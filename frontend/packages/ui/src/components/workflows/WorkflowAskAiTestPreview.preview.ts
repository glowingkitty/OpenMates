const response = 'The weather briefing is ready.\n\n- **Monday:** Mild and clear\n- **Tuesday:** Bring a raincoat\n\nRead the [forecast](https://example.com/forecast) for details.';

export default { content: response, processing: false, error: '' };

const eventId = '00000000-0000-4000-8000-000000007001';
const event = { embed_id: eventId, content_type: 'events-event', app_id: 'events', skill_id: 'search', content: { title: 'Berlin drawing class', date_start: '2026-10-07T18:30:00+02:00', url: 'https://example.com/drawing', description: 'An evening art class.', venue: { name: 'Art studio', city: 'Berlin' } } };

export const variants = {
  withEmbeds: { content: `## Art this week\n\nJoin [Berlin drawing class](embed:${eventId}).\n\n\`\`\`embeds_results_view\ntitle: Art classes\nembeds: ${eventId}\n\`\`\``, processing: false, embeds: [event] },
  streaming: { content: 'The weather briefing is ready.\n\n- **Monday:** Mild and clear\n- **Tuesday:**', processing: true, error: '' },
  error: { content: '', processing: false, error: 'The test response could not be completed.' },
  empty: { content: '', processing: false, error: '' },
};
