<script lang="ts">
  import { getLucideIcon } from '../../utils/categoryUtils';

  let {
    title,
    eyebrow = '',
    subtitle = '',
    backLabel = '',
    backIconSize = 16,
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
    eyebrow?: string;
    subtitle?: string;
    backLabel?: string;
    backIconSize?: number;
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
    <button type="button" class="breadcrumb" disabled={disabled} onclick={onBack}><Back size={backIconSize}/><span>{backLabel}</span></button>
  {:else}<span></span>{/if}
  <div class="title">
    {#if eyebrow}<span class="eyebrow">{eyebrow}</span>{/if}
    {#if iconStyle}<span class="asset-icon" data-testid="workflow-editor-primary-icon" style={iconStyle} aria-hidden="true"></span>{/if}
    <strong>{title}</strong>
    {#if subtitle}<span class="subtitle">{subtitle}</span>{/if}
  </div>
  <div class="close-control">
    <button type="button" class="header-action" disabled={disabled} aria-label={closeLabel} onclick={onClose}>
      <span class="clickable-icon icon_close top-button" aria-hidden="true"></span>
    </button>
  </div>
  {#if collapsible}
    <button type="button" class="collapse" disabled={disabled} aria-label={collapseLabel} onclick={onClose}><Up size={16}/></button>
  {/if}
</header>

<style>
  .editor-header { position:relative; box-sizing:border-box; display:flex; align-items:center; justify-content:center; min-height:3.25rem; margin-inline:-1.5rem; padding:.35rem 3.5rem; border-radius:1rem 1rem 0 0; color:var(--color-font-secondary); }
  .editor-header.colored { min-height:11.5rem; padding-bottom:1.65rem; background:var(--node-gradient); color:var(--color-font-button); }
  button { border:0; box-shadow:none; background:transparent; color:inherit; font:inherit; cursor:pointer; }
  .breadcrumb { position:absolute; left:.65rem; top:.75rem; display:flex; align-items:center; gap:var(--spacing-2); min-width:0; max-width:35%; padding:.35rem; font-size:max(14px, .875rem); }
  .breadcrumb span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .title { display:flex; align-items:center; justify-content:center; gap:var(--spacing-4); min-width:0; text-align:center; }
  .title strong { max-width:34rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:max(14px, .875rem); }
  .colored .title { flex-direction:column; gap:.45rem; }
  .colored .title strong { color:var(--color-font-button); font-size:max(18px, 1.125rem); line-height:1.35; white-space:normal; overflow-wrap:anywhere; }
  .colored .title .asset-icon { width:40px; height:40px; }
  .colored .eyebrow { font-size:max(16px, 1rem); }
  .colored .subtitle { font-size:max(18px, 1.125rem); }
  .colored .breadcrumb { font-size:max(16px, 1rem); }
  .colored .breadcrumb :global(svg), .colored .collapse :global(svg) { width:22px; height:22px; }
  .eyebrow { font-size:max(14px, .875rem); font-weight:700; line-height:1.25; }
  .subtitle { font-size:var(--font-size-p); font-weight:700; line-height:1.25; }
  .asset-icon { display:inline-block; flex:0 0 auto; width:var(--workflow-icon-size, 16px); height:var(--workflow-icon-size, 16px); background:currentColor; -webkit-mask:var(--workflow-icon) center/contain no-repeat; mask:var(--workflow-icon) center/contain no-repeat; }
  .close-control { position:absolute; top:.4rem; right:.65rem; display:grid; place-items:center; width:2.5rem; height:2.5rem; border-radius:var(--radius-full); background:var(--color-grey-0); box-shadow:var(--shadow-md); }
  .colored .close-control { background:color-mix(in srgb, var(--color-grey-0) 22%, transparent); }
  .header-action { position:relative; box-sizing:border-box; display:grid; place-items:center; width:100%; min-width:0; max-width:100%; height:100%; margin:0; padding:0; overflow:hidden; }
  .header-action :global(.clickable-icon.top-button) { position:static !important; inset:auto !important; display:block; width:22px; height:22px; margin:0 !important; transform:none !important; background:var(--color-primary-start); }
  .colored .header-action :global(.clickable-icon.top-button) { background:var(--color-font-button); }
  .collapse { position:absolute; bottom:.25rem; left:50%; display:grid; place-items:center; width:2rem; height:1.6rem; padding:0; transform:translateX(-50%); }
  button:disabled { opacity:.5; cursor:default; }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) {
    .editor-header { margin-inline:-.8rem; padding-inline:3rem; }
    .editor-header.colored { min-height:10.625rem; padding-bottom:1.45rem; }
    .title strong { max-width:11rem; }
    .colored .title strong { max-width:15rem; font-size:max(17px, 1.0625rem); }
    .colored .title .asset-icon { width:36px; height:36px; }
    .colored .eyebrow { font-size:max(15px, .9375rem); }
    .colored .subtitle { font-size:max(17px, 1.0625rem); }
    .colored .breadcrumb { top:2.35rem; }
    .colored .breadcrumb :global(svg), .colored .collapse :global(svg) { width:20px; height:20px; }
  }
</style>
