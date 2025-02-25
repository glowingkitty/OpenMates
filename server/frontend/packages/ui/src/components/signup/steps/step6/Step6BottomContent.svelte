<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
-->

<script lang="ts">
    import { text } from '@repo/ui';
</script>

<div class="bottom-content">
    {@html $text('signup.seperate_2fa_app.text')}
</div>

<style>
    .bottom-content {
        padding: 24px;
    }
</style>
