<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import { tooltip } from '../../actions/tooltip';

  interface Props extends Pick<HTMLButtonAttributes,
    'class' | 'disabled' | 'title' | 'aria-label' | 'aria-haspopup' | 'aria-expanded' |
    'onclick' | 'onkeydown' | 'onmousedown' | 'onmouseup' | 'onmouseleave' |
    'onpointerdown' | 'ontouchstart' | 'ontouchend'> {
    icon: string;
    testId: string;
    insetIcon?: boolean;
    showTooltip?: boolean;
    button?: HTMLButtonElement;
    'data-icon'?: string;
    'data-attachment-kind'?: string;
    'data-record-audio-trigger'?: string;
  }

  let {
    icon, testId, insetIcon = false, showTooltip = false,
    button = $bindable(), class: className = '', disabled, title,
    'aria-label': label, 'aria-haspopup': hasPopup, 'aria-expanded': isExpanded,
    'data-icon': iconName, 'data-attachment-kind': attachmentKind,
    'data-record-audio-trigger': recordAudioTrigger,
    onclick, onkeydown, onmousedown, onmouseup, onmouseleave, onpointerdown, ontouchstart, ontouchend,
  }: Props = $props();

  function attachTooltip(element: HTMLButtonElement) {
    if (showTooltip) return tooltip(element);
  }
</script>

<button
  data-testid={testId}
  {disabled}
  {title}
  aria-label={label}
  aria-haspopup={hasPopup}
  aria-expanded={isExpanded}
  data-icon={iconName}
  data-attachment-kind={attachmentKind}
  data-record-audio-trigger={recordAudioTrigger}
  {onclick}
  {onkeydown}
  {onmousedown}
  {onmouseup}
  {onmouseleave}
  {onpointerdown}
  {ontouchstart}
  {ontouchend}
  bind:this={button}
  type="button"
  data-workspace-control="composer-icon"
  class={['composer-action-icon', className, !insetIcon && 'clickable-icon', !insetIcon && icon]}
  use:attachTooltip
>
  {#if insetIcon}<span class={`clickable-icon ${icon}`} aria-hidden="true"></span>{/if}
</button>
