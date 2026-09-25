import { dailyWeatherNewsGraph, weeklyEventsGraph } from "./workflowExamples";
import type { WorkflowGraph } from "../../stores/workflowWorkspaceStore";
import type { Chat } from "../../types/chat";
import type { Capability } from "./workflowBuilder";

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

const eventsSearchCapability: Capability = {
  id: "events.search",
  type: "app_skill",
  enabled: true,
  title: "Search",
  metadata: {
    app_id: "events",
    skill_id: "search",
    cost: { per_unit: { credits: 30 } },
    workflow: {
      test_allowed: true,
      test_example_input: {
        requests: [
          { query: "OpenMates meetup Berlin", location: "Berlin", count: 3 },
        ],
      },
    },
    input_schema: {
      type: "object",
      properties: {
        provider: {
          "x-ui": { basic: false },
          type: "string",
          enum: [
            "auto",
            "Meetup",
            "Luma",
            "Eventbrite",
            "Resident Advisor",
            "Siegessäule",
            "Berlin Philharmonic",
            "GPN24",
            "39C3",
            "38C3",
            "37C3",
          ],
        },
        requests: {
          "x-ui": { basic: true },
          type: "array",
          items: {
            type: "object",
            "x-ui": {
              control: "date-range",
              start_field: "start_date",
              end_field: "end_date",
              max_offset_days: 365,
              basic: false,
            },
            properties: {
              query: { type: "string", "x-ui": { basic: true } },
              location: { type: "string", "x-ui": { basic: true } },
              lat: { type: "number", "x-ui": { basic: false } },
              lon: { type: "number", "x-ui": { basic: false } },
              start_date: { type: "string", "x-ui": { basic: false } },
              end_date: { type: "string", "x-ui": { basic: false } },
              event_type: {
                type: "string",
                enum: ["PHYSICAL", "ONLINE"],
                "x-ui": { basic: false },
              },
              radius_miles: { type: "number", default: 25, "x-ui": { basic: false } },
              count: {
                type: "integer",
                minimum: 1,
                maximum: 50,
                default: 10,
              },
              relevance_criteria: { type: "string", "x-ui": { basic: true } },
              provider: {
                type: "string",
                enum: [
                  "auto",
                  "Meetup",
                  "Luma",
                  "Eventbrite",
                  "Resident Advisor",
                  "Siegessäule",
                  "Berlin Philharmonic",
                  "GPN24",
                  "39C3",
                  "38C3",
                  "37C3",
                ],
              },
              providers: {
                type: "array",
                items: {
                  type: "string",
                  enum: [
                    "Meetup",
                    "Luma",
                    "Eventbrite",
                    "Resident Advisor",
                    "Siegessäule",
                    "Berlin Philharmonic",
                    "GPN24",
                    "39C3",
                    "38C3",
                    "37C3",
                  ],
                },
              },
              conference: {
                type: "string",
                enum: ["GPN24", "39C3", "38C3", "37C3"],
              },
              past_events: { type: "boolean", default: false },
              concert_tags: { type: "array", items: { type: "string" } },
            },
            required: ["query"],
          },
        },
      },
      required: ["requests"],
    },
    output_schema: {
      type: "object",
      properties: {
        summary: { type: "string", example: "Events search completed", "x-ui": { basic: false } },
        result_count: { type: "integer", example: 1, "x-ui": { basic: false } },
        provider: { type: "string", example: "Example events provider", "x-ui": { basic: false } },
        results: {
          "x-ui": { basic: true },
          type: "array",
          items: {
            type: "object",
            properties: {
              id: { type: "string", example: "example-event", "x-ui": { basic: false } },
              title: { type: "string", example: "AI community meetup", "x-ui": { basic: true } },
              url: {
                type: "string",
                example: "https://example.invalid/events/ai",
                "x-ui": { basic: true },
              },
              provider: {
                type: "string",
                example: "Example events provider",
                "x-ui": { basic: false },
              },
              description: {
                type: "string",
                example: "An example meetup for people working with AI.",
                "x-ui": { basic: false },
              },
              date_start: {
                type: "string",
                example: "2026-09-23T18:00:00+02:00",
                "x-ui": { basic: true },
              },
              date_end: {
                type: "string",
                example: "2026-09-23T20:00:00+02:00",
                "x-ui": { basic: false },
              },
              location: { type: "string", example: "Berlin", "x-ui": { basic: true } },
              event_type: { type: "string", example: "PHYSICAL", "x-ui": { basic: false } },
              price_amount: { type: "number", example: 0, "x-ui": { basic: false } },
            },
          },
        },
        warnings: { type: "array", items: { type: "string" }, example: [] },
        partial: { type: "boolean", example: false },
      },
    },
  },
};

function skillVariant(graph: WorkflowGraph, capability: Capability) {
  return { ...defaultProps, graph, capabilityFixtures: [capability] };
}

function defaultCapability(id: string): Capability {
  const capability = defaultProps.capabilityFixtures.find(
    (candidate) => candidate.id === id,
  );
  if (!capability) throw new Error(`Missing preview capability: ${id}`);
  return capability as Capability;
}

function singleSkillGraph(nodeId: "weather" | "news"): WorkflowGraph {
  const source = dailyWeatherNewsGraph();
  const trigger = source.nodes.find((node) => node.id === "trigger");
  const skill = source.nodes.find((node) => node.id === nodeId);
  if (!trigger || !skill)
    throw new Error(`Missing preview graph node: ${nodeId}`);
  return {
    version: source.version,
    trigger_node_id: trigger.id,
    nodes: [trigger, skill],
    edges: [{ from: trigger.id, to: skill.id }],
  };
}

export default defaultProps;
export const variants = {
  empty: {
    ...defaultProps,
    graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] },
  },
  aiCheck: { ...defaultProps, graph: aiCheckGraph() },
  exactCheckTestable: { ...defaultProps, workflowId: "preview-workflow" },
  aiCheckTestable: { ...defaultProps, workflowId: "preview-workflow", graph: aiCheckGraph() },
  weatherForecast: skillVariant(
    singleSkillGraph("weather"),
    defaultCapability("weather.forecast"),
  ),
  newsSearch: skillVariant(
    singleSkillGraph("news"),
    defaultCapability("news.search"),
  ),
  eventsSearch: skillVariant(weeklyEventsGraph(), eventsSearchCapability),
  readonly: { ...defaultProps, readOnly: true, onSave: null },
};
