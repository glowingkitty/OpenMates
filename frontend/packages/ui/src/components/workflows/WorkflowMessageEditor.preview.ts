export default {
  value: 'Summarize these events: {{steps.events.results}}',
  outputs: [{ reference: '$nodes.events.output.results', nodeId: 'events', appId: 'events', label: 'Events · Results', schema: { type: 'array' } }],
  placeholder: 'Type @ to add a variable',
  onChange: (_value: string) => {},
  onMentionTrigger: (_visible: boolean, _query: string) => {},
};
