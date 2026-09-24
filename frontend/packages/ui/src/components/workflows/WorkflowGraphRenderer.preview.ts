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
    {
      id: "ai.ask",
      type: "app_skill",
      enabled: true,
      title: "Ask",
      metadata: {
        app_id: "ai",
        skill_id: "ask",
        input_schema: {
          type: "object",
          properties: { prompt: { type: "string" } },
          required: ["prompt"],
        },
        output_schema: {
          type: "object",
          properties: { answer: { type: "string", title: "Answer", example: "A concise summary" } },
        },
        workflow: { test_allowed: true },
      },
    },
  ],
};

function aiCheckGraph(): WorkflowGraph {
  const graph = structuredClone(dailyWeatherNewsGraph());
  const check = graph.nodes.find((node) => node.id === "rain");
  if (check) {
    check.title = "Outdoor weather judgment";
    check.config = {
      mode: "ai",
      question: "Is this weather unsuitable for an outdoor lunch?",
      selected_inputs: [
        "$nodes.weather.output.rain_probability",
        "$nodes.weather.output.forecast_day",
      ],
    };
  }
  return graph;
}

export default defaultProps;
export const variants = {
  empty: {
    ...defaultProps,
    graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] },
  },
  aiCheck: { ...defaultProps, graph: aiCheckGraph() },
  readonly: { ...defaultProps, readOnly: true, onSave: null },
};
