<!--
    SettingsModelPreferenceItem is the canonical editable AI default-model row.
    It combines the tier capability glyph, request label, selected model value,
    and the standard settings modify action from the Figma AI settings design.
    Design reference: Figma node 5810:55043.
-->
<script lang="ts">
    import ModifyButton from '../../buttons/ModifyButton.svelte';
    import type { AiCapabilityLevel } from '../../../utils/aiModelDisplay';
    import SettingsCapabilityScale from './SettingsCapabilityScale.svelte';

    interface Props {
        title: string;
        value: string;
        capability: AiCapabilityLevel;
        capabilityLabel: string;
        onEdit: () => void;
        'data-testid'?: string;
    }

    let {
        title,
        value,
        capability,
        capabilityLabel,
        onEdit,
        'data-testid': testid = undefined,
    }: Props = $props();

</script>

<div class="preference-item" data-testid={testid}>
    <SettingsCapabilityScale level={capability} label={capabilityLabel} compact={true} />
    <div class="text">
        <span class="title">{title}</span>
        <span class="value"><span class="ai-icon" aria-hidden="true"></span>{value}</span>
    </div>
    <ModifyButton data-testid={testid ? `${testid}-modify-button` : undefined} onClick={onEdit} />
</div>

<style>
    .preference-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        min-height: 2.73125rem;
        padding: 0 var(--spacing-10);
        border-radius: 0.559rem;
        transition: background-color var(--duration-normal) var(--easing-default);
    }

    .preference-item:hover { background: var(--color-grey-10); }

    .text {
        display: flex;
        flex: 1;
        min-width: 0;
        flex-direction: column;
        gap: 0.0625rem;
    }

    .title {
        color: var(--color-ai-settings-muted, var(--color-font-secondary));
        font-size: var(--font-size-small);
        font-weight: 700;
        line-height: 1.25;
    }

    .value {
        display: flex;
        align-items: center;
        gap: var(--spacing-2);
        overflow: hidden;
        color: transparent;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .ai-icon {
        width: 1.4175rem;
        height: 1.4175rem;
        flex-shrink: 0;
        background: var(--color-primary-start);
        -webkit-mask: var(--icon-url-ai) center / contain no-repeat;
        mask: var(--icon-url-ai) center / contain no-repeat;
    }

</style>
