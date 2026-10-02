import { dailyWeatherNewsGraph, weeklyEventsGraph } from "./workflowPreviewFixtures";
import { websiteChangesGraph } from "./workflowTemplates";
import { workflowApiRequest, type WorkflowGraph } from "../../stores/workflowWorkspaceStore";
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
    { id: "web.read", type: "app_skill", enabled: true, title: "Read website", metadata: {
      app_id: "web", skill_id: "read", input_schema: { type: "object", properties: { url: { type: "string" } } },
      output_schema: { type: "object", properties: {
        text: { type: "string", title: "Page text", "x-ui": { basic: true } },
        has_changed: { type: "boolean", title: "Has changed since last successful read", "x-ui": { basic: true } },
        changes: { type: "string", title: "Changes since last successful read", "x-ui": { basic: true } },
        source_url: { type: "string", title: "Website link", "x-ui": { basic: true } },
      } }, workflow: { test_allowed: true },
    } },
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
  return { ...defaultProps, graph, capabilityFixtures: [capability, defaultCapability("ai.ask")] };
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

const typedControlsGraph: WorkflowGraph = {
  version: 2,
  trigger_node_id: 'trigger',
  nodes: [
    { id: 'trigger', type: 'schedule_trigger', config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } } },
    { id: 'fitness', type: 'app_skill_action', config: { app_id: 'fitness', skill_id: 'search_classes', input: { requests: [{ query: 'Yoga', city: 'Berlin' }] } } },
    { id: 'stays', type: 'app_skill_action', config: { app_id: 'travel', skill_id: 'search_stays', input: { requests: [{ query: 'Hotels in Paris' }] } } },
  ],
  edges: [{ from: 'trigger', to: 'fitness' }, { from: 'fitness', to: 'stays' }],
};

const typedControlsCapabilities: Capability[] = [
  {
    id: 'fitness.search_classes', type: 'app_skill', enabled: true, title: 'Search classes',
    metadata: { app_id: 'fitness', skill_id: 'search_classes', input_schema: {
      type: 'object', properties: { requests: { type: 'array', items: {
        type: 'object', 'x-ui': { control: 'date-range', start_field: 'start_date', end_field: 'end_date', max_offset_days: 365, max_span_days: 13 },
        properties: {
          query: { type: 'string', 'x-ui': { basic: true } },
          city: { type: 'string', 'x-ui': { basic: true, control: 'location', location_mode: 'city', latitude_field: 'lat', longitude_field: 'lon', clear_fields: ['address'] } },
          address: { type: 'string', 'x-ui': { basic: false, control: 'location', location_mode: 'place', city_field: 'city', latitude_field: 'lat', longitude_field: 'lon' } },
          lat: { type: 'number', 'x-ui': { basic: false } }, lon: { type: 'number', 'x-ui': { basic: false } },
          start_date: { type: 'string', format: 'date', 'x-ui': { basic: true } },
          end_date: { type: 'string', format: 'date', 'x-ui': { basic: true } },
          plan: { type: 'string', enum: ['essential', 'classic', 'premium', 'max'], 'x-ui': { basic: false } },
        },
      } } },
    } },
  },
  {
    id: 'travel.search_stays', type: 'app_skill', enabled: true, title: 'Search stays',
    metadata: { app_id: 'travel', skill_id: 'search_stays', input_schema: {
      type: 'object', properties: { requests: { type: 'array', items: {
        type: 'object', 'x-ui': { control: 'date-range', start_field: 'check_in_date', end_field: 'check_out_date', max_offset_days: 365 },
        properties: {
          query: { type: 'string', 'x-ui': { basic: true } },
          check_in_date: { type: 'string', format: 'date', 'x-ui': { basic: true } },
          check_out_date: { type: 'string', format: 'date', 'x-ui': { basic: true } },
        },
      } } },
    } },
  },
];

async function saveTestGraph(graph: WorkflowGraph): Promise<void> {
  await workflowApiRequest('/v1/workflows/preview-workflow', { method:'PATCH', body:JSON.stringify({ graph }) });
}

function comparisonCheckGraph(): WorkflowGraph {
  const graph = structuredClone(dailyWeatherNewsGraph());
  const weather = graph.nodes.find(node => node.id === 'weather')!;
  graph.nodes.splice(2, 0, { ...structuredClone(weather), id:'second_forecast', config:{ ...weather.config, input:{ location:'Paris' } } });
  graph.edges = graph.edges.filter(edge => !(edge.from === 'weather' && edge.to === 'rain'));
  graph.edges.push({ from:'weather', to:'second_forecast' }, { from:'second_forecast', to:'rain' });
  return graph;
}

export default defaultProps;
function websiteChangeGraph(ai = false): WorkflowGraph {
  return { version: 1, trigger_node_id: "trigger", nodes: [
    { id: "trigger", type: "manual_trigger", config: {} },
    { id: "read", type: "app_skill_action", title: "Read website", config: { app_id: "web", skill_id: "read", input: { url: "https://events.ccc.de" } } },
    { id: "rain", type: "check", config: ai ? { mode: "ai", question: "Do these changes announce a new Chaos Communication Congress article? {{steps.read.changes}}", selected_inputs: ["$nodes.read.output.changes"] } : { mode: "exact", predicate: { op: "eq", left: "$nodes.read.output.has_changed", right: true } } },
    { id: "message", type: "send_chat_message", config: { title: "Congress updates", message: "{{steps.read.changes}}\n{{steps.read.source_url}}" } },
  ], edges: [{ from: "trigger", to: "read" }, { from: "read", to: "rain" }, { from: "rain", to: "message", branch: ai ? "true" : "yes" }] };
}

function deliveryPreviewGraph(): WorkflowGraph {
  return { version: 2, trigger_node_id: 'trigger', nodes: [
    { id: 'trigger', type: 'manual_trigger', title: 'Start', config: {} },
    { id: 'send', type: 'send_chat_message', title: 'Send message', config: { title: 'Daily result', message: 'Today is ready' } },
  ], edges: [{ from: 'trigger', to: 'send' }] };
}

function deliveryPreview(status?: string) {
  return { ...defaultProps, graph: deliveryPreviewGraph(), readOnly: true, onSave: null,
    nodeRuns: [{ id: 'preview-send', run_id: 'preview-run', workflow_id: 'preview-workflow',
      node_id: 'send', node_type: 'send_chat_message', status: 'completed',
      output_summary: { delivery_id: 'preview-delivery', chat_id: 'preview-delivered-chat',
        ...(status ? { status } : {}) } }],
  };
}

export const variants = {
  websiteTemplate: {
    ...defaultProps,
    graph: websiteChangesGraph({
      question: "Do these website changes announce any new article about Chaos Communication Congress? {{steps.read.changes}}",
      summaryPrompt: "Summarize the new Congress articles and include links to their posts. Changes: {{steps.read.changes}}\nWebsite: {{steps.read.source_url}}",
      messageTitle: "Congress updates",
    }),
    capabilityFixtures: defaultProps.capabilityFixtures.map((capability) => capability.id !== "web.read" ? capability : {
      ...capability,
      metadata: { ...capability.metadata, input_schema: {
        type: "object",
        properties: { requests: { type: "array", items: {
          type: "object",
          properties: { url: { type: "string" }, only_main_content: { type: "boolean", default: true }, max_age: { type: "integer", "x-ui": { hidden: true } } },
          required: ["url"],
        } } },
        required: ["requests"],
      } },
    }),
  },

  deliveryMissingStatus: deliveryPreview(),
  deliveryPending: deliveryPreview('delivery_pending'),
  deliveryClaimed: deliveryPreview('claimed'),
  deliveryAcknowledged: deliveryPreview('acknowledged'),
  deliveryExpired: deliveryPreview('expired'),
  deliveryNoEvidence: {
    ...deliveryPreview(),
    nodeRuns: [{ ...deliveryPreview().nodeRuns[0], output_summary: {} }],
  },
  deliveryTerminalStale: {
    ...deliveryPreview('delivery_pending'),
    executionStatus: 'failed',
    nodeRuns: [
      { ...deliveryPreview().nodeRuns[0], node_id: 'trigger', node_type: 'manual_trigger', status: 'running', output_summary: {} },
      ...deliveryPreview('delivery_pending').nodeRuns,
    ],
  },
  askAiTestable: {
    ...defaultProps,
    workflowId: 'preview-workflow',
    onSave:saveTestGraph,
    graph: {
      version: 2, trigger_node_id: 'trigger',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', config: {} },
        { id: 'weather', type: 'app_skill_action', title: 'Forecast', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin' } } },
        { id: 'events', type: 'app_skill_action', title: 'Search', config: { app_id: 'events', skill_id: 'search', input: { requests: [{ query: 'Community events', location: 'Berlin' }] } } },
        { id: 'ask', type: 'app_skill_action', title: 'Ask AI', config: { app_id: 'ai', skill_id: 'ask', input: { prompt: 'Summarize {{steps.events.results}}', model: 'auto' } } },
      ],
      edges: [{ from: 'trigger', to: 'weather' }, { from: 'weather', to: 'events' }, { from: 'events', to: 'ask' }],
    } as WorkflowGraph,
    capabilityFixtures: [...defaultProps.capabilityFixtures, {
      ...eventsSearchCapability,
      metadata: {
        ...eventsSearchCapability.metadata,
        output_schema: { type: 'object', properties: {
          results: { type: 'array', title: 'Results', 'x-ui': { basic: true }, example: [{ title: 'Community meetup', url: 'https://example.com/event', date_start: '2026-10-01', location: 'Berlin' }], items: { type: 'object', properties: {
            title: { type: 'string', title: 'Title', 'x-ui': { basic: true } },
            url: { type: 'string', title: 'URL' }, location: { type: 'string', title: 'Location' },
          } } },
          result_count: { type: 'integer', title: 'Result count', example: 1 },
          provider: { type: 'string', title: 'Provider', example: 'Example provider' },
        } },
      },
    }],
  },
  empty: {
    ...defaultProps,
    graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] },
  },
  aiCheck: { ...defaultProps, graph: aiCheckGraph() },
  exactCheckTestable: { ...defaultProps, workflowId: "preview-workflow" },
  aiCheckTestable: { ...defaultProps, workflowId: "preview-workflow", graph: aiCheckGraph(), onSave:saveTestGraph },
  websiteChange: { ...defaultProps, workflowId: "preview-workflow", graph: websiteChangeGraph(), onSave: saveTestGraph },
  websiteAiChange: { ...defaultProps, workflowId: "preview-workflow", graph: websiteChangeGraph(true), onSave: saveTestGraph },
  websiteBlocked: { ...defaultProps, readOnly: true, onSave: null, graph: websiteChangeGraph(), nodeRuns: [{
    id: "blocked-read", run_id: "preview-run", workflow_id: "preview-workflow", node_id: "read",
    node_type: "app_skill_action", status: "failed", error_code: "WORKFLOW_WEBSITE_READ_BLOCKED",
    error_summary: "WORKFLOW_WEBSITE_READ_BLOCKED", input_summary: { url: "https://events.ccc.de" }, output_summary: {},
  }] },
  comparisonCheck: { ...defaultProps, workflowId:"preview-workflow", graph:comparisonCheckGraph(), onSave:saveTestGraph },
  weatherForecast: skillVariant(
    singleSkillGraph("weather"),
    defaultCapability("weather.forecast"),
  ),
  newsSearch: skillVariant(
    singleSkillGraph("news"),
    defaultCapability("news.search"),
  ),
  eventsSearch: skillVariant(weeklyEventsGraph(), eventsSearchCapability),
  typedControls: { ...defaultProps, graph: typedControlsGraph, capabilityFixtures: typedControlsCapabilities },
  readonly: { ...defaultProps, readOnly: true, onSave: null },
};
