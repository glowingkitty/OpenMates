<script lang="ts">
  import { getLucideIcon } from '../../utils/categoryUtils';

  let {
    title,
    backLabel = '',
    iconStyle = '',
    colored = false,
    collapsible = false,
    disabled = false,
    closeLabel,
    collapseLabel,
    onBack,
    onClose
  }: {
    title: string;
    backLabel?: string;
    iconStyle?: string;
    colored?: boolean;
    collapsible?: boolean;
    disabled?: boolean;
    closeLabel: string;
    collapseLabel: string;
    onBack: () => void;
    onClose: () => void;
  } = $props();

  const Back = getLucideIcon('chevron-left');
  const Up = getLucideIcon('chevron-up');
</script>

<header class="editor-header" class:colored>
  {#if backLabel}
    <button type="button" class="breadcrumb" disabled={disabled} onclick={onBack}><Back size={16}/><span>{backLabel}</span></button>
  {:else}<span></span>{/if}
  <div class="title">
    {#if iconStyle}<span class="asset-icon" style={iconStyle} aria-hidden="true"></span>{/if}
    <strong>{title}</strong>
  </div>
  <div class="new-chat-button-wrapper">
    <button type="button" class="header-action" disabled={disabled} aria-label={closeLabel} onclick={onClose}>
      <span class="clickable-icon icon_close top-button" aria-hidden="true"></span>
    </button>
  </div>
  {#if collapsible}
    <button type="button" class="collapse" disabled={disabled} aria-label={collapseLabel} onclick={onClose}><Up size={16}/></button>
  {/if}
</header>

<style>
  .editor-header { position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; min-height:3.25rem; margin-inline:-1.5rem; padding:.35rem .65rem; border-radius:1rem 1rem 0 0; color:var(--color-font-secondary); }
  .editor-header.colored { min-height:6.25rem; padding-bottom:1.4rem; background:var(--node-gradient); color:var(--color-font-button); }
  button { border:0; box-shadow:none; background:transparent; color:inherit; font:inherit; cursor:pointer; }
  .breadcrumb { justify-self:start; display:flex; align-items:center; gap:var(--spacing-2); min-width:0; padding:.35rem; font-size:max(14px, .875rem); }
  .breadcrumb span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .title { display:flex; align-items:center; justify-content:center; gap:var(--spacing-4); min-width:0; }
  .title strong { max-width:24rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:max(16px, 1rem); }
  .asset-icon { display:inline-block; flex:0 0 auto; width:16px; height:16px; background:currentColor; -webkit-mask:var(--workflow-icon) center/contain no-repeat; mask:var(--workflow-icon) center/contain no-repeat; }
  .new-chat-button-wrapper { justify-self:end; display:flex; align-items:center; justify-content:center; padding:var(--spacing-4); border-radius:40px; background-color:var(--color-grey-10); box-shadow:var(--shadow-md); }
  .header-action { display:flex; align-items:center; justify-content:center; margin:0; padding:0; }
  .header-action :global(.clickable-icon.top-button) { width:25px; height:25px; color:var(--color-font-primary); }
  .collapse { position:absolute; bottom:.25rem; left:50%; display:grid; place-items:center; width:2rem; height:1.6rem; padding:0; transform:translateX(-50%); }
  button:disabled { opacity:.5; cursor:default; }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) { .editor-header { margin-inline:-.8rem; } .title strong { max-width:11rem; } }
</style>
