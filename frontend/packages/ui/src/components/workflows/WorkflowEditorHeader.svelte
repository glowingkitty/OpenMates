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
    showDelete,
    deleteArmed,
    disabled = false,
    closeLabel,
    deleteLabel,
    confirmDeleteLabel,
    onBack,
    onDelete,
    onClose
  }: {
    title: string;
    eyebrow?: string;
    subtitle?: string;
    backLabel?: string;
    backIconSize?: number;
    iconStyle?: string;
    colored?: boolean;
    showDelete: boolean;
    deleteArmed: boolean;
    disabled?: boolean;
    closeLabel: string;
    deleteLabel: string;
    confirmDeleteLabel: string;
    onBack: () => void;
    onDelete: () => void;
    onClose: () => void;
  } = $props();

  const Back = getLucideIcon('chevron-left');
</script>

<header class="editor-header" class:colored>
  <div class="left-actions">
    {#if backLabel}
      <button type="button" class="breadcrumb header-control" disabled={disabled} aria-label={backLabel} title={backLabel} onclick={onBack}><Back size={backIconSize}/></button>
    {/if}
    {#if showDelete}
      <button type="button" class="delete-control header-control" class:armed={deleteArmed} data-testid="workflow-node-delete" disabled={disabled} aria-label={deleteArmed ? confirmDeleteLabel : deleteLabel} title={deleteArmed ? confirmDeleteLabel : deleteLabel} onclick={onDelete}>
        <span class="clickable-icon icon_delete top-button" aria-hidden="true"></span>
        {#if deleteArmed}<span class="confirm-label" data-testid="workflow-node-delete-confirmation">{confirmDeleteLabel}</span>{/if}
      </button>
    {/if}
  </div>
  <div class="title">
    {#if iconStyle}<span class="asset-icon" data-testid="workflow-editor-primary-icon" style={iconStyle} aria-hidden="true"></span>{/if}
    {#if eyebrow}<span class="eyebrow">{eyebrow}</span>{/if}
    <strong>{title}</strong>
    {#if subtitle}<span class="subtitle">{subtitle}</span>{/if}
  </div>
  <div class="close-control">
    <button type="button" class="close-button header-control" disabled={disabled} aria-label={closeLabel} title={closeLabel} onclick={onClose}>
      <span class="clickable-icon icon_close top-button" aria-hidden="true"></span>
    </button>
  </div>
</header>

<style>
  .editor-header { position:relative; box-sizing:border-box; container:workflow-editor-header / inline-size; display:flex; align-items:center; justify-content:center; min-height:3.25rem; margin-inline:-1.5rem; padding:.35rem 3.5rem; border-radius:1rem 1rem 0 0; color:var(--color-font-secondary); }
  .editor-header.colored { min-height:11.5rem; padding-bottom:1.65rem; background:var(--node-gradient); color:var(--color-font-button); }
  button { border:0; box-shadow:none; background:transparent; color:inherit; font:inherit; cursor:pointer; }
  .header-control { display:grid; place-items:center; min-width:2.5rem; height:2.5rem; padding:0; border-radius:var(--radius-full); background:color-mix(in srgb, var(--color-grey-0) 82%, transparent); box-shadow:var(--shadow-md); }
  .left-actions { position:absolute; top:.4rem; left:.65rem; display:flex; align-items:center; gap:var(--spacing-4); max-width:calc(100% - 4.5rem); }
  .breadcrumb :global(svg) { width:30px; height:30px; stroke-width:2.4; }
  .title { display:flex; align-items:center; justify-content:center; gap:var(--spacing-4); min-width:0; text-align:center; }
  .title strong { max-width:34rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:max(14px, .875rem); }
  .colored .title { flex-direction:column; gap:.45rem; }
  .colored .title strong { color:var(--color-font-button); font-size:max(18px, 1.125rem); line-height:1.35; white-space:normal; overflow-wrap:anywhere; }
  .colored .title .asset-icon { width:40px; height:40px; }
  .colored .eyebrow { font-size:max(16px, 1rem); }
  .colored .subtitle { font-size:max(18px, 1.125rem); }
  .colored .header-control { background:color-mix(in srgb, var(--color-grey-0) 22%, transparent); }
  .eyebrow { font-size:max(14px, .875rem); font-weight:700; line-height:1.25; }
  .subtitle { font-size:var(--font-size-p); font-weight:700; line-height:1.25; }
  .asset-icon { display:inline-block; flex:0 0 auto; width:var(--workflow-icon-size, 16px); height:var(--workflow-icon-size, 16px); background:currentColor; -webkit-mask:var(--workflow-icon) center/contain no-repeat; mask:var(--workflow-icon) center/contain no-repeat; }
  .close-control { position:absolute; top:.4rem; right:.65rem; display:grid; place-items:center; width:2.5rem; height:2.5rem; }
  .close-button { width:100%; }
  .delete-control { box-sizing:border-box; grid-auto-flow:column; gap:var(--spacing-4); width:2.5rem; overflow:hidden; color:var(--color-font-button); transition:width .18s ease, padding .18s ease; }
  .delete-control.armed { width:auto; max-width:min(22rem, calc(100cqw - 7rem)); padding-inline:.65rem .85rem; }
  .confirm-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:var(--font-size-small); font-weight:700; }
  .header-control :global(.clickable-icon.top-button) { position:static !important; inset:auto !important; display:block; flex:0 0 auto; width:22px; height:22px; margin:0 !important; transform:none !important; background:var(--color-primary-start); }
  .delete-control :global(.clickable-icon.top-button) { background:var(--color-font-button); }
  .colored .close-control :global(.clickable-icon.top-button) { background:var(--color-font-button); }
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
    .left-actions { gap:var(--spacing-2); }
    .delete-control.armed { max-width:calc(100cqw - 6.5rem); }
  }
  @media(prefers-reduced-motion:reduce) { .delete-control { transition:none; } }
</style>
