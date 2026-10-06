<script lang="ts">
  import { text } from "@repo/ui";
  import SettingsMenuItem from "../../SettingsItem.svelte";
  import SettingsTabs from "../elements/SettingsTabs.svelte";

  interface TeamUsageEntry {
    event_id: string;
    created_at: string | number;
    workspace_type: string;
    credit_amount: number;
  }

  let { entries }: { entries: TeamUsageEntry[] } = $props();
  let activeTab = $state("overview");

  const tabs = $derived([
    {
      id: "overview",
      icon: "event",
      label: $text("settings.usage.tab_overview"),
    },
    { id: "chats", icon: "chat", label: $text("settings.usage.tab_chats") },
    { id: "apps", icon: "app", label: $text("settings.usage.tab_apps") },
    {
      id: "work",
      icon: "coding",
      label: $text("settings.billing.team_usage_tab_work"),
    },
  ]);

  function timestamp(entry: TeamUsageEntry): number {
    if (typeof entry.created_at === "number")
      return entry.created_at < 1e12
        ? entry.created_at * 1000
        : entry.created_at;
    return Date.parse(entry.created_at);
  }

  function dayKey(milliseconds: number): string {
    const date = new Date(milliseconds);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function dayLabel(key: string): string {
    const [year, month, day] = key.split("-").map(Number);
    const date = new Date(year, month - 1, day);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (date.getTime() === today.getTime()) return $text("common.today");
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.getTime() === yesterday.getTime())
      return $text("common.yesterday");
    return date.toLocaleDateString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }

  function entryTitle(workspaceType: string): string {
    if (workspaceType === "chat") return $text("settings.usage.tab_chats");
    if (workspaceType === "app" || workspaceType === "apps")
      return $text("settings.usage.tab_apps");
    if (workspaceType === "workflow")
      return $text("settings.billing.team_usage_workflow");
    if (workspaceType === "task")
      return $text("settings.billing.team_usage_task");
    if (workspaceType === "plan")
      return $text("settings.billing.team_usage_plan");
    if (workspaceType === "project")
      return $text("settings.billing.team_usage_project");
    return $text("settings.billing.team_usage_other");
  }

  const filteredEntries = $derived(
    entries.filter((entry) => {
      if (activeTab === "chats") return entry.workspace_type === "chat";
      if (activeTab === "apps")
        return (
          entry.workspace_type === "app" || entry.workspace_type === "apps"
        );
      if (activeTab === "work")
        return ["workflow", "task", "plan", "project"].includes(
          entry.workspace_type,
        );
      return true;
    }),
  );

  const dayGroups = $derived.by(() => {
    const grouped = new Map<
      string,
      Map<string, { total: number; count: number }>
    >();
    for (const entry of [...filteredEntries].sort(
      (a, b) => timestamp(b) - timestamp(a),
    )) {
      const created = timestamp(entry);
      const key = Number.isFinite(created) ? dayKey(created) : "";
      if (!grouped.has(key)) grouped.set(key, new Map());
      const workspaces = grouped.get(key)!;
      const workspaceType =
        entry.workspace_type === "app" ? "apps" : entry.workspace_type;
      const summary = workspaces.get(workspaceType) ?? { total: 0, count: 0 };
      summary.total += entry.credit_amount;
      summary.count += 1;
      workspaces.set(workspaceType, summary);
    }
    return [...grouped].map(([key, workspaces]) => {
      const items = [...workspaces].map(([workspaceType, summary]) => ({
        workspaceType,
        ...summary,
      }));
      return {
        key,
        items,
        total: items.reduce((sum, item) => sum + item.total, 0),
      };
    });
  });
</script>

<div class="team-usage" data-testid="team-usage-ledger">
  <div class="team-usage-tabs">
    <SettingsTabs {tabs} bind:activeTab testIdPrefix="team-usage-tab" />
  </div>
  <div class="team-usage-day-list" id="tabpanel-{activeTab}" role="tabpanel">
    {#if dayGroups.length === 0}
      <p class="team-usage-empty" data-testid="team-usage-empty">
        {$text("settings.usage.no_usage_title")}
      </p>
    {:else}
      {#each dayGroups as group (group.key)}
        <div class="team-usage-day" data-testid="team-usage-day">
          <SettingsMenuItem
            type="heading"
            icon="event"
            title={group.key ? dayLabel(group.key) : $text("settings.usage")}
            creditsDisplay={group.total.toLocaleString()}
            data-testid="team-usage-day-heading"
          />
          {#each group.items as item (item.workspaceType)}
            <SettingsMenuItem
              type="heading"
              icon={item.workspaceType === "chat"
                ? "chat"
                : item.workspaceType === "apps"
                  ? "app"
                  : "coding"}
              iconBackground="none"
              title={entryTitle(item.workspaceType)}
              subtitleBottom={`${item.count} ${$text("settings.usage.requests")}`}
              creditsDisplay={item.total.toLocaleString()}
              data-testid="team-usage-workspace"
            />
          {/each}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .team-usage-tabs {
    width: calc(100% - 6px);
    margin: 15px 0 0 5px;
  }
  .team-usage-tabs :global(.settings-tab) {
    height: 37px;
  }
  .team-usage-day-list {
    margin-top: 12px;
  }
  .team-usage-day {
    padding: 3px 0 8px;
    margin-bottom: 10px;
    border-radius: 12px;
    background: var(--color-grey-0);
  }
  .team-usage-empty {
    margin: 0 10px;
    padding: 16px 10px;
    color: var(--color-font-secondary);
  }
</style>
