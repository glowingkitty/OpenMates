<!--
    SettingsCapabilityScale renders the Figma low/medium/high/max model scale.
    It is shared by AI tier rows, provider model lists, and model detail pages.
    The compact form shows bars only; the full form includes the translated label.
    Design reference: Figma components 5810:54675-5810:54678.
-->
<script lang="ts">
    import type { AiCapabilityLevel } from '../../../utils/aiModelDisplay';

    interface Props {
        level: AiCapabilityLevel;
        label: string;
        compact?: boolean;
        'data-testid'?: string;
    }

    let { level, label, compact = false, 'data-testid': testid = 'ai-capability-scale' }: Props = $props();
    const activeBars = $derived({ low: 1, medium: 2, high: 3, max: 4 }[level]);
</script>

<div class="capability-scale" class:compact aria-label={label} data-level={level} data-testid={testid}>
    <span class="bars" aria-hidden="true">
        {#each [1, 2, 3, 4] as bar}
            <span
                class="bar bar-{bar}"
                class:active={bar <= activeBars}
                data-testid={`${testid}-bar-${bar}`}
            ></span>
        {/each}
    </span>
    {#if !compact}<span class="label">{label}</span>{/if}
</div>

<style>
    .capability-scale {
        display: inline-flex;
        align-items: center;
        gap: var(--spacing-4);
        color: var(--color-font-secondary);
        font-size: var(--font-size-small);
        font-weight: 700;
        line-height: 1.25;
    }

    .bars {
        display: inline-flex;
        align-items: flex-end;
        gap: 0.057rem;
        width: 1.5rem;
        height: 1.5rem;
        padding: 0.1875rem;
        border-radius: 0.559rem;
        background: linear-gradient(135deg, var(--color-ai-icon-tile-start, var(--color-grey-10)) 9.04%, var(--color-ai-icon-tile-end, var(--color-grey-20)) 90.06%);
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.25);
        box-sizing: border-box;
    }

    .bar {
        width: 0.2275rem;
        border-radius: var(--radius-1) var(--radius-1) 0 0;
        background: var(--color-grey-30);
    }

    .bar-1 { height: 30%; }
    .bar-2 { height: 50%; }
    .bar-3 { height: 72%; }
    .bar-4 { height: 100%; }
    .capability-scale[data-level="low"] .bar.active { background: var(--color-ai-capability-low); }
    .capability-scale[data-level="medium"] .bar.active { background: var(--color-ai-capability-medium); }
    .capability-scale[data-level="high"] .bar.active { background: var(--color-ai-capability-high); }
    .capability-scale[data-level="max"] .bar.active { background: var(--color-ai-capability-max); }

    .compact .bars {
        width: 2.73125rem;
        height: 2.73125rem;
        padding: 0.8125rem;
    }
</style>
