<!--
    SettingsButtonGroup — Flex container for grouping action buttons.

    Replaces inline `.action-buttons`, `.edit-actions`, `.delete-actions`
    patterns across settings pages. Handles alignment and wrapping for
    button groups like save+cancel, delete+confirm, etc.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    /** Horizontal alignment of buttons within the group */
    type ButtonGroupAlign = 'left' | 'center' | 'right' | 'space-between';

    /** Map align prop to CSS justify-content values */
    const alignMap: Record<ButtonGroupAlign, string> = {
        'left': 'flex-start',
        'center': 'center',
        'right': 'flex-end',
        'space-between': 'space-between',
    };

    let {
        align = 'right' as ButtonGroupAlign,
        wrap = true,
        children,
    }: {
        align?: ButtonGroupAlign;
        wrap?: boolean;
        children: Snippet;
    } = $props();

    let justifyContent = $derived(alignMap[align] || 'flex-end');
</script>

<div
    class="settings-button-group"
    class:no-wrap={!wrap}
    style="justify-content: {justifyContent};"
>
    {@render children()}
</div>

<style>
    .settings-button-group {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        padding: 0 0.625rem;
    }

    .settings-button-group.no-wrap {
        flex-wrap: nowrap;
    }

    /*
     * Reset nested SettingsButton wrapper padding — when buttons are inside
     * a group, the group provides the outer padding instead.
     */
    .settings-button-group :global(.settings-button-wrapper) {
        padding: 0;
    }
</style>
