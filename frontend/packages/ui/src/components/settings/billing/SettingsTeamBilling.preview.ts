import type { TeamViewModel } from "../../../services/teamService";

const previewTeam: TeamViewModel = {
  team_id: "team-preview",
  name: "xHain",
  description: "",
  role: "owner",
  status: "active",
  profileImageMetadata: {
    version: 1,
    mode: "generated",
    icon_name: "team",
    icon_color: "#ffffff",
    background_color: "#4d73ff",
  },
  zeroBalance: 0,
  createdAt: 1,
  updatedAt: 1,
  encrypted: { team_id: "team-preview" },
};

/** Account-free Team billing overview. Child routes can be selected with props.activeSettingsView. */
export default {
  teamId: "team-preview",
  activeSettingsView: "teams/team-preview/billing",
  preview: true,
  previewTeam,
  previewRole: "owner",
  previewBalance: 0,
};
