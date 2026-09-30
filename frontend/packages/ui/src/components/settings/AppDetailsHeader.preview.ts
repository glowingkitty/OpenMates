/** Standard Teams settings banner: exercises the shared route-to-icon alias. */
const defaults = {
  breadcrumbLabel: "Settings",
  fullBreadcrumbLabel: "Settings",
  settingsPage: { title: "Teams", icon: "teams", description: "" },
  scrollTop: 0,
};
export default defaults;
export const variants = { collapsed: { ...defaults, scrollTop: 120 } };
