/** Disabled starting points; the owner reviews location, query and schedule before activation. */
import type {
  WorkflowGraph,
  WorkflowNode,
} from "../../stores/workflowWorkspaceStore";
const schedule = (value: Record<string, unknown>): WorkflowNode => ({
  id: "trigger",
  type: "schedule_trigger",
  config: {
    schedule: {
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      ...value,
    },
  },
});
const skill = (id: string, app: string, input: unknown): WorkflowNode => ({
  id,
  type: "app_skill_action",
  title: app === "weather" ? "Get forecast" : `Search ${app}`,
  config: {
    app_id: app,
    skill_id: app === "weather" ? "forecast" : "search",
    input,
  },
});
const graph = (nodes: WorkflowNode[]): WorkflowGraph => ({
  version: 2,
  trigger_node_id: "trigger",
  nodes,
  edges: nodes.slice(1).map((node, i) => ({ from: nodes[i].id, to: node.id })),
});
export function dailyWeatherNewsGraph(): WorkflowGraph {
  return graph([
    schedule({ type: "daily", time: "09:00" }),
    skill("weather", "weather", { location: "Berlin", days: 1 }),
    {
      id: "rain",
      type: "check",
      title: "Rain expected today",
      config: {
        predicate: {
          left: "$nodes.weather.output.rain_probability",
          op: "gt",
          right: 0,
        },
      },
    },
    skill("news", "news", {
      requests: [{ query: "Germany news", freshness: "pd", count: 6 }],
    }),
    {
      id: "message",
      type: "send_chat_message",
      title: "Send morning report",
      config: {
        title: "Morning weather and news",
        message: "Your morning update",
        blocks: [
          {
            id: "weather",
            source: "$nodes.weather.output.rain_periods",
            include_if: "$nodes.rain.output.matched",
          },
          {
            id: "news",
            source: "$nodes.news.output.results",
            only_new_results: true,
          },
        ],
      },
    },
  ]);
}
export function weeklyEventsGraph(): WorkflowGraph {
  return graph([
    schedule({ type: "weekly", weekdays: ["sunday"], time: "09:00" }),
    skill("events", "events", {
      requests: [
        {
          query: "AI",
          location: "Berlin",
          start_date: { $date: "next_week_start", format: "datetime" },
          end_date: { $date: "next_week_end", format: "datetime" },
          count: 10,
        },
      ],
    }),
    {
      id: "message",
      type: "send_chat_message",
      title: "Send AI events",
      config: {
        title: "AI events for the upcoming week",
        blocks: [
          {
            id: "events",
            source: "$nodes.events.output.results",
            only_new_results: true,
          },
        ],
      },
    },
  ]);
}
export function hourlyApartmentsGraph(): WorkflowGraph {
  return graph([
    schedule({ type: "hourly", minute: 0 }),
    skill("apartments", "home", {
      requests: [
        {
          query: "Berlin",
          listing_type: "rent",
          property_type: "apartment",
          max_price_eur: 1200,
          sort: "newest",
          providers: ["Kleinanzeigen"],
          max_results: 10,
        },
      ],
    }),
    {
      id: "message",
      type: "send_chat_message",
      title: "Send new apartments",
      config: {
        title: "New apartments",
        blocks: [
          {
            id: "apartments",
            source: "$nodes.apartments.output.results",
            only_new_results: true,
          },
        ],
      },
    },
  ]);
}
