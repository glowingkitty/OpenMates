<!-- Supply the settings page layout around the real fragment in bare previews. -->
<script lang="ts">
  import { SettingsPageContainer } from '../elements';
  import SettingsHidePersonalData from './SettingsHidePersonalData.svelte';
</script>

<SettingsPageContainer maxWidth="wide">
  <SettingsHidePersonalData />
</SettingsPageContainer>
