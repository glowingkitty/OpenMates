<!--
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

<div class="content">
    <div class="header-content">
        <div class="primary-text">
            {@html $text('signup.pay_per_use.text').replace('{credits}', '<span class="coin-icon-inline"></span>')}
        </div>
        <div class="secondary-text">
            {@html $text('signup.for_chatting_and_apps.text')}
        </div>
    </div>
</div>

<style>
    .header-content {
        z-index: 2;
        display: flex;
        flex-direction: column;
        height: 100%;
    }
    .content {
        padding: 24px;
        padding-top: 70px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    .secondary-text {
        font-size: 14px;
        color: white;
        opacity: 0.6;
        margin-top: 10px;
    }
    /* Updated class for the inline icon to make it white */
    :global(.coin-icon-inline) {
        display: inline-flex;
        width: 25px;
        height: 25px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        vertical-align: middle;
        filter: invert(1); /* Make the icon white */
        margin: 0 5px;
        position: relative;
        top: -2px; /* Fine-tune vertical alignment with text */
    }
    .primary-text {
        white-space: nowrap; /* Prevent line breaks within the text */
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
    }
</style>