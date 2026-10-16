/** Shared web/terminal workspace inspiration fallback data. */
import type { DailyInspiration, DailyInspirationSurface } from "./ui/src/stores/dailyInspirationStore.js";

export function getWorkspaceInspirations(surface: Exclude<DailyInspirationSurface, "chats">): DailyInspiration[] {
  const now = Math.floor(Date.now() / 1000);
  if (surface === "apps") {
    return [
      { inspiration_id: "hardcoded-apps-search", phrase: "Find information directly with an app skill, and keep the results for later.", title: "Use a Skill Directly", category: "general_knowledge", content_type: "feature", video: null, generated_at: now, surface, feature: { feature_id: "apps-direct-search", icon: "search", title: "Search the web", description: "Search without starting a chat.", settings_path: "apps/web/search" } },
      { inspiration_id: "hardcoded-apps-weather", phrase: "Check the forecast before making plans. Your saved results stay together in Apps.", title: "Plan Around the Weather", category: "travel", content_type: "feature", video: null, generated_at: now, surface, feature: { feature_id: "apps-weather", icon: "cloud-sun", title: "Weather forecast", description: "Choose a location and dates.", settings_path: "apps/weather/forecast" } },
    ];
  }
  if (surface === "projects") {
    return [
      {
        inspiration_id: "hardcoded-project-brief",
        phrase: "Start every project with a short brief: goal, audience, deadline, and the first concrete next step.",
        title: "Write a Project Brief",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "A clear project brief turns a vague idea into a workspace you can actually organize. Create one folder for source material, one for drafts, and one for final outputs, then add the chat or embed that defines the next step.",
        follow_up_suggestions: ["Draft a one-page brief", "Plan my first milestone", "Organize project folders"],
        feature: {
          feature_id: "project-brief",
          icon: "folder-kanban",
          title: "Project planning tip",
          description: "Define the outcome before collecting files and chats.",
          settings_path: null,
        },
      },
      {
        inspiration_id: "hardcoded-project-milestones",
        phrase: "Use milestones as folders: research, prototype, review, launch. It keeps work visible without extra UI.",
        title: "Milestone Folders",
        category: "software_development",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "Milestone folders make a project feel like a file browser while still reflecting the real work sequence. Put chats, uploads, and embeds into the milestone they support so the latest state is easy to resume.",
        follow_up_suggestions: ["Create milestone folders", "Define prototype scope", "Review launch checklist"],
        feature: {
          feature_id: "project-milestones",
          icon: "list-checks",
          title: "Milestone structure",
          description: "Turn project phases into folders.",
          settings_path: null,
        },
      },
      {
        inspiration_id: "hardcoded-project-assets",
        phrase: "Save the source next to the output: prompts, PDFs, images, and final embeds belong in the same project context.",
        title: "Keep Sources Together",
        category: "general_knowledge",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "Projects are most useful when they preserve both the inputs and the generated outputs. Upload key files, add relevant chats, and keep generated embeds in the same place so future you can verify where each result came from.",
        follow_up_suggestions: ["List missing source files", "Create an outputs folder", "Summarize project context"],
        feature: {
          feature_id: "project-assets",
          icon: "archive",
          title: "Project organization",
          description: "Keep evidence and outputs side by side.",
          settings_path: null,
        },
      },
    ];
  }

  if (surface === "tasks") {
    return [
      {
        inspiration_id: "hardcoded-task-next-action",
        phrase: "Turn one messy goal into a next action you can finish today.",
        title: "Find the Next Action",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "Tasks work best when each item starts with a verb, has one owner, and can be checked off without rereading the whole project. Pick one goal, name the next physical action, and park the rest as follow-ups.",
        follow_up_suggestions: ["Break down this goal", "Prioritize today's tasks", "Create a review checklist"],
        feature: {
          feature_id: "task-next-action",
          icon: "check-square",
          title: "Task planning tip",
          description: "Make every task small enough to finish.",
          settings_path: null,
        },
      },
      {
        inspiration_id: "hardcoded-task-priorities",
        phrase: "Choose the three tasks that matter most today, then start with the one that removes a blocker.",
        title: "Choose Today's Priorities",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "A short priority list keeps urgent messages from crowding out useful progress. Pick three outcomes for today and start with the task that clears the way for other work.",
        follow_up_suggestions: ["Choose today's top three", "Find my blockers", "Make a realistic task list"],
        feature: {
          feature_id: "task-priorities",
          icon: "list",
          title: "Task prioritization tip",
          description: "Focus on the next few useful outcomes.",
          settings_path: null,
        },
      },
      {
        inspiration_id: "hardcoded-task-finish-line",
        phrase: "Write down what done looks like before you begin a task.",
        title: "Define Done",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "A clear finish line makes a task easier to start and easier to hand off. Describe the result you can check, then add any missing step as its own task.",
        follow_up_suggestions: ["Define a task outcome", "Split a large task", "Review unfinished work"],
        feature: {
          feature_id: "task-finish-line",
          icon: "check-square",
          title: "Task completion tip",
          description: "Give each task a clear finish line.",
          settings_path: null,
        },
      },
    ];
  }

  if (surface === "plans") {
    return [
      {
        inspiration_id: "hardcoded-plan-timeline",
        phrase: "Start a plan with the deadline, the decision points, and the first reversible step.",
        title: "Sketch a Lightweight Plan",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "A good plan separates commitments from guesses. Put the fixed deadline first, list the assumptions that need checking, and choose the smallest first step that still teaches you something useful.",
        follow_up_suggestions: ["Draft a timeline", "List risky assumptions", "Choose the first step"],
        feature: {
          feature_id: "plan-timeline",
          icon: "calendar-clock",
          title: "Planning tip",
          description: "Keep plans anchored to decisions and dates.",
          settings_path: null,
        },
      },
    ];
  }

  if (surface === "teams") {
    return [
      {
        inspiration_id: "hardcoded-team-context",
        phrase: "Keep the team context explicit: shared credits, shared memories, and no personal connected accounts.",
        title: "Team Context Check",
        category: "productivity",
        content_type: "feature",
        video: null,
        generated_at: now,
        surface,
        assistant_response: "Teams work best when the context boundary is obvious. Confirm who belongs to the team, keep shared memories in the team context, and leave personal provider accounts in personal mode until team-owned credentials ship.",
        follow_up_suggestions: ["Create a team brief", "Invite the first member", "Review team privacy boundaries"],
        feature: {
          feature_id: "team-context",
          icon: "team",
          title: "Team privacy tip",
          description: "Keep shared and personal context separate.",
          settings_path: null,
        },
      },
    ];
  }

  return [
    {
      inspiration_id: "hardcoded-workflow-trigger",
      phrase: "A useful workflow starts with one trigger, one decision, and one visible result.",
      title: "Design a Workflow Trigger",
      category: "productivity",
      content_type: "feature",
      video: null,
      generated_at: now,
      surface,
      assistant_response: "Before automating anything, write the trigger in plain language: when this happens, decide this, then produce that result. This keeps workflows understandable and testable.",
      follow_up_suggestions: ["Define a workflow trigger", "Map decision points", "Design the result"],
      feature: {
        feature_id: "workflow-trigger",
        icon: "workflow",
        title: "Workflow planning tip",
        description: "Start automation with a clear trigger.",
        settings_path: null,
      },
    },
  ];
}

