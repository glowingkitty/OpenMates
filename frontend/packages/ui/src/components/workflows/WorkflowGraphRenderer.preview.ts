import { dailyWeatherNewsGraph } from "./workflowExamples";
import type { WorkflowGraph } from "../../stores/workflowWorkspaceStore";
const defaultProps = {
  graph: dailyWeatherNewsGraph(),
  readOnly: false,
  workflowId: null,
  onChange: (_graph: WorkflowGraph) => {},
  onSave: async (_graph: WorkflowGraph) => {},
  capabilityFixtures: [
    {
      id: "weather.forecast",
      type: "app_skill",
      enabled: true,
      title: "Forecast",
      metadata: {
        app_id: "weather",
        skill_id: "forecast",
        input_schema: {
          type: "object",
          properties: {
            location: { type: "string" },
            days: { type: "integer", default: 1, minimum: 1, maximum: 14 },
          },
          required: ["location"],
        },
        output_schema: {
          properties: {
            rain_probability: { type: "number", example: 60 },
            rain_expected: { type: "boolean", example: true },
            rain_periods: {
              type: "array",
              example: [{ start: "09:00", end: "11:00" }],
            },
            forecast_day: { type: "object" },
          },
        },
        workflow: { test_allowed: true },
        cost: { fixed: 10 },
      },
    },
    {
      id: "news.search",
      type: "app_skill",
      enabled: true,
      title: "Search",
      metadata: {
        app_id: "news",
        skill_id: "search",
        input_schema: {
          type: "object",
          properties: {
            requests: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  query: { type: "string" },
                  count: { type: "integer", minimum: 1, maximum: 20 },
                },
                required: ["query"],
              },
            },
          },
        },
        output_schema: {
          properties: {
            results: {
              type: "array",
              example: [
                {
                  title: "Example article",
                  url: "https://example.com/article",
                },
              ],
            },
          },
        },
        workflow: { test_allowed: true },
      },
    },
  ],
};
export default defaultProps;
export const variants = {
  empty: {
    ...defaultProps,
    graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] },
  },
  readonly: { ...defaultProps, readOnly: true, onSave: null },
};
