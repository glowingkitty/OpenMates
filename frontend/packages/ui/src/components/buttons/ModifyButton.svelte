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
    import { tooltip } from '../../actions/tooltip';
</script>

<button
    use:tooltip 
    class="modify-button" 
    aria-label={$text('settings.modify.text')}
></button>

<style>
    .modify-button {
        all: unset;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: var(--color-primary);
        cursor: pointer;
        position: relative;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);

        transition: transform 0.2s ease;

        &:hover {
            transform: scale(1.1);
        }

        &::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: white;
            -webkit-mask-image: url('@openmates/ui/static/icons/modify.svg');
            mask-image: url('@openmates/ui/static/icons/modify.svg');
            -webkit-mask-size: 50%;
            mask-size: 50%;
            -webkit-mask-position: center;
            mask-position: center;
            -webkit-mask-repeat: no-repeat;
            mask-repeat: no-repeat;
        }
    }
</style>