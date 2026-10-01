import type { Output } from './workflowBuilder';

const outputs: Output[] = [
  { nodeId: 'events', appId: 'events', reference: '$nodes.events.output.results', label: 'Search · Results', schema: { type: 'array', 'x-ui': { basic: true } } },
  { nodeId: 'events', appId: 'events', reference: '$nodes.events.output.result_count', label: 'Search · Result count', schema: { type: 'integer' } },
  { nodeId: 'events', appId: 'events', reference: '$nodes.events.output.provider', label: 'Search · Provider', schema: { type: 'string' } },
  { nodeId: 'weather', appId: 'weather', reference: '$nodes.weather.output.rain_probability', label: 'Forecast · Rain probability', schema: { type: 'number' } },
];
const props = {
  outputs,
  sources: [
    { nodeId: 'events', appId: 'events', label: 'Events | Search', iconStyle: '--workflow-icon:var(--icon-url-events)' },
    { nodeId: 'weather', appId: 'weather', label: 'Weather | Get forecast', iconStyle: '--workflow-icon:var(--icon-url-weather)' },
  ],
  selectedSourceId: 'events',
  onSelectSource: (_nodeId: string) => {},
  onInsert: (_output: Output) => {},
};
export default props;
export const variants = {
  sources: { ...props, selectedSourceId: null },
  filtered: { ...props, query: 'E' },
  empty: { ...props, query: 'missing' },
};
