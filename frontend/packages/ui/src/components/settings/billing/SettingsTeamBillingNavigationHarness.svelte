<script lang="ts">
  import SettingsTeamBilling from "./SettingsTeamBilling.svelte";
  import teamBillingPreview from "./SettingsTeamBilling.preview";

  let activeSettingsView = $state("teams/team-preview/billing/buy-credits");
</script>

<div data-testid="team-billing-navigation-harness" data-active-view={activeSettingsView}>
  <SettingsTeamBilling
    {...teamBillingPreview}
    {activeSettingsView}
    on:openSettings={(event) => (activeSettingsView = event.detail.settingsPath)}
  />
</div>
