import { dailyWeatherNewsGraph } from "./workflowExamples";
import type { WorkflowGraph } from "../../stores/workflowWorkspaceStore";
import type { Chat } from "../../types/chat";

function previewChat(
  chatId: string,
  title: string,
  category: string,
  icon: string,
  summary: string,
): Chat {
  return {
    chat_id: chatId,
    encrypted_title: null,
    messages_v: 1,
    title_v: 1,
    last_edited_overall_timestamp: Date.UTC(2026, 8, 24, 9),
    unread_count: 0,
    created_at: Date.UTC(2026, 8, 23, 9),
    updated_at: Date.UTC(2026, 8, 24, 9),
    title,
    category,
    icon,
    chat_summary: summary,
  };
}

const defaultProps = {
  graph: dailyWeatherNewsGraph(),
  readOnly: false,
  workflowId: null,
  onChange: (_graph: WorkflowGraph) => {},
  onSave: async (_graph: WorkflowGraph) => {},
  chatFixtures: [
    previewChat(
      "preview-weather-reports",
      "Daily weather reports",
      "science_technology",
      "cloud-sun",
      "Daily forecasts, rain windows, and practical plans for the week.",
    ),
    previewChat(
      "preview-language-events",
      "Language learning events",
      "education",
      "languages",
      "Privacy & user interests focused AI agents to make useful AI accessible to everyday users.",
    ),
  ],
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
          "x-ui": {
            control: "date-range",
            start_field: "start_date",
            end_field: "end_date",
            min: "today",
            max_offset_days: 13,
            default: "today",
          },
          properties: {
            location: { type: "string" },
            latitude: { type: "number" },
            longitude: { type: "number" },
            start_date: { type: "string", format: "date" },
            end_date: { type: "string", format: "date" },
            days: {
              type: "integer",
              default: 7,
              minimum: 1,
              maximum: 14,
              "x-ui": { hidden: true },
            },
            timezone: { type: "string" },
            units: { type: "string", enum: ["metric"], default: "metric" },
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
          properties: {
            answer: {
              type: "string",
              title: "Answer",
              example: "A concise summary",
            },
          },
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
