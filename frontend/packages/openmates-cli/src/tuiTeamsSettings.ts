/** Native Team management pages under Settings. Decrypted text stays in this panel. */
import type { OpenMatesClient, TeamMemberRecord, TeamRole } from "./client.js";
import type { SettingsPage } from "./tuiSettingsCatalog.js";
import { captureTuiWorkspaceOwner } from "./tuiCachedWorkspaces.js";

const field = (id: string, label: string, required = false) => ({ id, label, kind: "text" as const, required });
const activeTeam = (client: OpenMatesClient): string => {
  const id = client.getActiveTeamId();
  if (!id) throw new Error("Select a Team with Teams → Select Team first.");
  return id;
};
const teamRole = async (client: OpenMatesClient): Promise<TeamRole> => {
  const teamId = activeTeam(client), isCurrent = captureTuiWorkspaceOwner(client);
  const team = await client.getTeam(teamId);
  if (!isCurrent() || client.getActiveTeamId() !== teamId) throw new Error("Team changed while checking permissions.");
  if (!team.role) throw new Error("Team role is unavailable.");
  return team.role;
};
const requireRole = async (client: OpenMatesClient, allowed: TeamRole[]): Promise<string> => {
  const id = activeTeam(client), isCurrent = captureTuiWorkspaceOwner(client);
  const team = await client.getTeam(id);
  if (!isCurrent() || client.getActiveTeamId() !== id) throw new Error("Team changed while checking permissions.");
  if (!allowed.includes(team.role as TeamRole)) throw new Error("Your Team role cannot perform this action.");
  return id;
};
const displayMember = (member: TeamMemberRecord) => ({
  user_id: member.user_id,
  display_name: member.profile?.display_name ?? "",
  role: member.role,
  status: member.status ?? "",
  joined_at: member.joined_at ?? null,
});

export const TEAM_SETTINGS_PAGES: readonly SettingsPage[] = [
  { route: "teams", title: "Teams", parent: "main", auth: true, description: "Manage the selected Team or create one.",
    load: async (c) => ({ active_team_id: c.getActiveTeamId(), teams: await Promise.all((await c.listTeams()).map(async (team) => ({
      team_id: team.team_id ?? "", name: (await c.getTeamDetails(team.team_id ?? "")).name, role: team.role ?? "",
    }))) }),
    rows: (value) => { const list = (value as { teams?: Array<{ team_id: string; name: string; role: string }> } | undefined)?.teams ?? [];
      return list.filter((team) => team.team_id).map((team) => ({ id: `team:${team.team_id}`, label: `${team.name || team.team_id} · ${team.role} · ${team.team_id}`, switchTeam: team.team_id })); } },
  { route: "teams/select", title: "Select Team", parent: "teams", auth: true,
    description: "Enter a Team ID shown above. Switching refreshes the Settings owner.",
    fields: [field("team_id", "Team ID", true)],
    actions: [{ id: "select", label: "Select Team", requiredFields: ["team_id"], run: async (c, d) => {
      const isCurrent = captureTuiWorkspaceOwner(c);
      const team = await c.getTeam(d.team_id.trim());
      if (!isCurrent()) throw new Error("Workspace changed while selecting Team.");
      c.setActiveTeamId(team.team_id ?? d.team_id.trim());
      return { success: true };
    } }, { id: "personal", label: "Switch to Personal", run: async (c) => { c.setActiveTeamId(null); return { success: true }; } }] },
  { route: "teams/create", title: "Create Team", parent: "teams", auth: true,
    description: "Team name approval and encryption happen before creation.",
    fields: [field("name", "Name", true), field("description", "Description")],
    actions: [{ id: "create", label: "Create Team", run: async (c, d) => {
      const team = await c.createTeam({ name: d.name.trim(), description: d.description.trim() || undefined });
      return { team_id: team.team_id ?? "" };
    } }] },
  { route: "teams/details", title: "Team Details", parent: "teams", auth: true,
    load: async (c) => { const team = await c.getTeamDetails(activeTeam(c)); return {
      team_id: team.team_id ?? "", name: team.name, description: team.description, role: team.role ?? "", status: team.status ?? "",
    }; },
    fields: [field("name", "Name", true), field("description", "Description")],
    saveRoles: ["owner", "admin"],
    defaults: (value) => { const v = value as { name?: string; description?: string }; return { name: v.name ?? "", description: v.description ?? "" }; },
    save: async (c, d) => { await requireRole(c, ["owner", "admin"]); const team = await c.updateTeam(activeTeam(c), { name: d.name.trim(), description: d.description.trim() }); return { team_id: team.team_id }; } },
  { route: "teams/members", title: "Members", parent: "teams", auth: true,
    load: async (c) => ({ role: await teamRole(c), members: (await c.listTeamMembers(activeTeam(c))).map(displayMember) }),
    rows: (value) => { const list = (value as { members?: Array<{ user_id: string; display_name: string; role: string }> } | undefined)?.members ?? [];
      return list.filter((member) => member.user_id).map((member) => ({ id: `member:${member.user_id}`, label: `${member.display_name || member.user_id} · ${member.role} · ${member.user_id}`,
        route: "teams/member", field: "user_id", value: member.user_id,
        details: { selected_name: member.display_name, selected_role: member.role, selected_user_id: member.user_id } })); } },
  { route: "teams/member", title: "Member Role", parent: "teams/members", auth: true,
    description: "Owner and admins can change roles or remove a member.",
    load: async (c) => ({ role: await teamRole(c) }), requiresLoad: true,
    fields: [field("user_id", "Member user ID", true), { id: "role", label: "New role", kind: "choice", options: ["member", "viewer", "admin"] }],
    actions: [
      { id: "change-role", label: "Change member role", confirm: "Change this member's Team role?", roles: ["owner", "admin"], requiredFields: ["user_id"], run: async (c, d) => {
        const id = await requireRole(c, ["owner", "admin"]);
        const member = await c.updateTeamMemberRole(id, d.user_id.trim(), d.role as "member" | "viewer" | "admin");
        return displayMember(member as unknown as TeamMemberRecord);
      } },
      { id: "remove-member", label: "Remove member", confirm: "Remove this member from the Team?", roles: ["owner", "admin"], requiredFields: ["user_id"], run: async (c, d) => c.removeTeamMember(await requireRole(c, ["owner", "admin"]), d.user_id.trim()) },
    ] },
  { route: "teams/profile", title: "My Team Profile", parent: "teams", auth: true,
    load: async (c) => {
      const id = activeTeam(c), isCurrent = captureTuiWorkspaceOwner(c);
      const identity = await c.whoAmI();
      if (!isCurrent() || c.getActiveTeamId() !== id) throw new Error("Team changed while loading your profile.");
      const member = await c.getTeamMember(id, String(identity.id));
      return { user_id: member.user_id, display_name: member.profile?.display_name ?? "", avatar: member.profile?.avatar ?? "", role: member.role };
    },
    fields: [field("display_name", "Display name"), field("avatar", "Avatar")],
    defaults: (value) => { const v = value as { display_name?: string; avatar?: string }; return { display_name: v.display_name ?? "", avatar: v.avatar ?? "" }; },
    save: async (c, d) => displayMember(await c.updateOwnTeamMemberProfile(activeTeam(c), { display_name: d.display_name, avatar: d.avatar || null })) },
  { route: "teams/invite", title: "Invite Member", parent: "teams", auth: true, teamRoles: ["owner", "admin"],
    load: async (c) => ({ role: await teamRole(c) }), requiresLoad: true,
    fields: [{ ...field("email", "Recipient email", true), validate: (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? null : "Enter a valid email address." }, { id: "role", label: "Role", kind: "choice", options: ["member", "viewer", "admin"] }],
    actions: [{ id: "invite", label: "Create invite", roles: ["owner", "admin"], requiredFields: ["email"], run: async (c, d) => {
      const id = await requireRole(c, ["owner", "admin"]);
      const invite = await c.createTeamInvite(id, { recipient_email: d.email.trim(), role: d.role as "member" | "viewer" | "admin" });
      return { invite_id: invite.invite_id ?? "", invite_url: invite.invite_url ?? "" };
    } }] },
  { route: "teams/access", title: "Access Requests", parent: "teams", auth: true, teamRoles: ["owner", "admin"],
    load: async (c) => ({ role: await teamRole(c), requests: (await c.listTeamAccessRequests(activeTeam(c))).map((row) => ({
      access_request_id: row.access_request_id ?? "", status: row.status ?? "",
    })) }),
    fields: [field("request_id", "Request ID", true)],
    actions: [
      { id: "approve", label: "Approve access", confirm: "Approve this Team access request?", roles: ["owner", "admin"], requiredFields: ["request_id"], run: async (c, d) => {
        await c.approveTeamAccessRequest(await requireRole(c, ["owner", "admin"]), d.request_id.trim()); return { success: true };
      } },
      { id: "reject", label: "Reject access", confirm: "Reject this Team access request?", roles: ["owner", "admin"], requiredFields: ["request_id"], run: async (c, d) => c.rejectTeamAccessRequest(await requireRole(c, ["owner", "admin"]), d.request_id.trim()) },
    ] },
  { route: "teams/billing", title: "Team Billing", parent: "teams", auth: true, teamRoles: ["owner", "admin"],
    description: "Billing applies to the selected Team. Purchases and billing settings are in the browser.",
    load: async (c) => { const id = await requireRole(c, ["owner", "admin"]), billing = await c.getTeamBilling(id); return {
      team_id: id, balance_credits: billing.balance_credits ?? 0,
    }; } },
  { route: "teams/billing/usage", title: "Team Usage", parent: "teams/billing", auth: true, teamRoles: ["owner", "admin"],
    description: "Credit usage for the selected Team only.",
    load: async (c) => ({ usage: (await c.listTeamUsage(await requireRole(c, ["owner", "admin"]))).map((row) => ({
      workspace_type: typeof row.workspace_type === "string" ? row.workspace_type : "",
      credit_amount: typeof row.credit_amount === "number" ? row.credit_amount : 0,
      created_at: typeof row.created_at === "string" || typeof row.created_at === "number" ? row.created_at : "",
    })) }) },
  { route: "teams/billing/manage", title: "Manage Team Billing", parent: "teams/billing", auth: true, teamRoles: ["owner", "admin"],
    webOnly: "teams", webReason: "Open Teams, select this Team, then Billing to manage purchases, invoices and payment methods." },
  { route: "teams/security", title: "Team Security", parent: "teams", auth: true, teamRoles: ["owner", "admin"], requiresLoad: true,
    description: "Owner and admins can edit Team access policy. Team deletion uses the browser verification flow.",
    load: async (c) => ({ ...await c.getTeamSecurity(await requireRole(c, ["owner", "admin"])), role: await teamRole(c) }),
    fields: [
      { id: "restrict_email_domains", label: "Restrict email domains", kind: "boolean" },
      field("allowed_email_domains", "Allowed domains"),
      { id: "require_invite_link_approval", label: "Approve invite links", kind: "boolean" },
      { id: "require_strong_auth", label: "Require strong auth", kind: "boolean" },
    ],
    saveRoles: ["owner", "admin"],
    saveConfirm: "Save Team security policy? Turning restrictions off can broaden Team access. Review each field before confirming.",
    defaults: (value) => { const policy = value as { restrict_email_domains?: boolean; allowed_email_domains?: string[]; require_invite_link_approval?: boolean; require_strong_auth?: boolean }; return {
      restrict_email_domains: policy.restrict_email_domains ? "on" : "off",
      allowed_email_domains: (policy.allowed_email_domains ?? []).join(", "),
      require_invite_link_approval: policy.require_invite_link_approval === false ? "off" : "on",
      require_strong_auth: policy.require_strong_auth ? "on" : "off",
    }; },
    save: async (c, d) => c.updateTeamSecurity(await requireRole(c, ["owner", "admin"]), {
      restrict_email_domains: d.restrict_email_domains === "on",
      allowed_email_domains: [...new Set(d.allowed_email_domains.split(",").map((v) => v.trim().toLowerCase()).filter(Boolean))],
      require_invite_link_approval: d.require_invite_link_approval === "on",
      require_strong_auth: d.require_strong_auth === "on",
    }) },
  { route: "teams/security/delete", title: "Delete Team", parent: "teams/security", auth: true, teamRoles: ["owner"],
    webOnly: "teams", webReason: "Open Teams, select this Team, then use its verified deletion flow in the browser." },
];
