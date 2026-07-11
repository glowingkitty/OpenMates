<!--
  WorkspaceDetailHeader.svelte
  Presentation-only header shared by chat and workspace detail surfaces.
  Callers own authorization, encryption, persistence, and synchronization;
  this component owns only ephemeral edit state and interaction semantics.
-->

<script lang="ts">
  import { tick } from 'svelte';
  import { getCategoryGradientColors, getLucideIcon, getValidIconName } from '../../utils/categoryUtils';
  import { text } from '@repo/ui';

  type SaveCallback = (value: string) => void | Promise<void>;

  let {
    title,
    description,
    category,
    icon,
    writable,
    onSaveTitle,
    onSaveDescription,
    metadata = '',
    embedded = false,
    titleTestId = 'workspace-detail-title',
    descriptionTestId = 'workspace-detail-description',
    showDescription = true,
    iconTestId = undefined,
    showIcon = true,
    alignment = 'center',
  }: {
    title: string;
    description: string;
    category: string;
    icon: string;
    writable: boolean;
    onSaveTitle: SaveCallback;
    onSaveDescription: SaveCallback;
    metadata?: string;
    embedded?: boolean;
    titleTestId?: string;
    descriptionTestId?: string;
    showDescription?: boolean;
    iconTestId?: string;
    showIcon?: boolean;
    alignment?: 'center' | 'start';
  } = $props();

  let editingField = $state<'title' | 'description' | null>(null);
  let titleDraft = $state('');
  let descriptionDraft = $state('');
  let savingField = $state<'title' | 'description' | null>(null);
  let failedField = $state<'title' | 'description' | null>(null);
  let titleInput = $state<HTMLInputElement | null>(null);
  let descriptionInput = $state<HTMLTextAreaElement | null>(null);
  let titleDisplay = $state<HTMLButtonElement | null>(null);
  let descriptionDisplay = $state<HTMLButtonElement | null>(null);
  let titleFieldElement = $state<HTMLElement | null>(null);
  let descriptionFieldElement = $state<HTMLElement | null>(null);

  const IconComponent = $derived(getLucideIcon(getValidIconName(icon, category)));
  const EditIcon = getLucideIcon('pencil');
  const SaveIcon = getLucideIcon('check');
  const UndoIcon = getLucideIcon('undo-2');
  const titleChanged = $derived(titleDraft.trim() !== title.trim());
  const descriptionChanged = $derived(descriptionDraft.trim() !== description.trim());
  const titleValid = $derived(titleDraft.trim().length > 0);
  const bannerStyle = $derived.by(() => {
    const colors = getCategoryGradientColors(category);
    if (!colors) return 'background: var(--color-primary); --orb-color: var(--color-grey-0);';
    return `background: linear-gradient(135deg, ${colors.start}, ${colors.end}); --orb-color: ${colors.end};`;
  });

  function beginEdit(field: 'title' | 'description'): void {
    if (!writable || savingField) return;
    titleDraft = title;
    descriptionDraft = description;
    failedField = null;
    editingField = field;
    void tick().then(() => {
      const input = field === 'title' ? titleInput : descriptionInput;
      input?.focus();
      input?.select();
    });
  }

  function cancelEdit(): void {
    const cancelledField = editingField;
    titleDraft = title;
    descriptionDraft = description;
    failedField = null;
    editingField = null;
    void tick().then(() => {
      (cancelledField === 'title' ? titleDisplay : descriptionDisplay)?.focus();
    });
  }

  async function saveField(field: 'title' | 'description'): Promise<void> {
    if (!writable || savingField) return;
    const draft = field === 'title' ? titleDraft.trim() : descriptionDraft.trim();
    const changed = field === 'title' ? titleChanged : descriptionChanged;
    if (!changed) {
      cancelEdit();
      return;
    }
    if (field === 'title' && !titleValid) return;

    savingField = field;
    failedField = null;
    try {
      await (field === 'title' ? onSaveTitle(draft) : onSaveDescription(draft));
      editingField = null;
    } catch (error) {
      failedField = field;
      console.error(`[WorkspaceDetailHeader] Failed to save ${field}:`, error);
    } finally {
      savingField = null;
    }
  }

  function handleKeydown(event: KeyboardEvent, field: 'title' | 'description'): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      cancelEdit();
      return;
    }
    if (field === 'title' && event.key === 'Enter') {
      event.preventDefault();
      void saveField(field);
      return;
    }
    if (field === 'description' && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void saveField(field);
    }
  }

  function handleOutsidePointer(event: PointerEvent): void {
    if (!editingField || savingField) return;
    const activeField = editingField === 'title' ? titleFieldElement : descriptionFieldElement;
    if (activeField?.contains(event.target as Node)) return;
    const valid = editingField === 'title' ? titleValid : true;
    const changed = editingField === 'title' ? titleChanged : descriptionChanged;
    if (valid && changed) void saveField(editingField);
    else cancelEdit();
  }
</script>

<svelte:window onpointerdown={handleOutsidePointer} />

<section
  class="workspace-detail-header"
  class:embedded
  class:align-start={alignment === 'start'}
  data-testid="workspace-detail-header"
  data-header-system="workspace-detail"
  style={embedded ? undefined : bannerStyle}
>
  {#if !embedded}
    <div class="header-orbs" aria-hidden="true"><span></span><span></span><span></span></div>
    <div class="decorative-icon left" aria-hidden="true"><IconComponent size={126} color="currentColor" /></div>
    <div class="decorative-icon right" aria-hidden="true"><IconComponent size={126} color="currentColor" /></div>
  {/if}

  <div class="header-content">
    {#if showIcon}<div class="header-icon" data-testid={iconTestId} aria-hidden="true"><IconComponent size={38} color="currentColor" /></div>{/if}

    <div bind:this={titleFieldElement} class="editable-field title-field" data-testid="workspace-detail-title-field">
      {#if editingField === 'title'}
        <input
          bind:this={titleInput}
          bind:value={titleDraft}
          class="title-input"
          data-testid="workspace-detail-title-input"
          aria-label={$text('common.edit')}
          onkeydown={(event) => handleKeydown(event, 'title')}
        />
        <span class="edit-hint" data-testid="workspace-detail-title-hint">{$text('common.detail_title_hint')}</span>
        <div class="field-actions">
          {#if titleChanged}
            <button type="button" data-testid="workspace-detail-title-save" aria-label={$text('common.save')} disabled={!titleValid || savingField === 'title'} onclick={() => void saveField('title')}><SaveIcon size={18} /></button>
          {/if}
          <button type="button" data-testid="workspace-detail-title-undo" aria-label={$text('common.cancel')} disabled={savingField === 'title'} onclick={cancelEdit}><UndoIcon size={18} /></button>
        </div>
      {:else}
        <button bind:this={titleDisplay} class="display-value title-value" type="button" data-testid={titleTestId} disabled={!writable} onclick={() => beginEdit('title')}>{title}</button>
        {#if writable}
          <button class="edit-affordance" type="button" data-testid="workspace-detail-title-edit" aria-label={$text('common.edit')} onclick={() => beginEdit('title')}><EditIcon size={18} /></button>
        {/if}
      {/if}
      {#if failedField === 'title'}
        <div class="save-error" role="alert" data-testid="workspace-detail-title-error">
          <span>{$text('common.detail_save_error')}</span>
          <button type="button" data-testid="workspace-detail-title-retry" onclick={() => void saveField('title')}>{$text('common.retry')}</button>
        </div>
      {/if}
    </div>

    {#if showDescription}<div bind:this={descriptionFieldElement} class="editable-field description-field" data-testid="workspace-detail-description-field">
      {#if editingField === 'description'}
        <textarea
          bind:this={descriptionInput}
          bind:value={descriptionDraft}
          rows="3"
          data-testid="workspace-detail-description-input"
          aria-label={$text('common.edit')}
          onkeydown={(event) => handleKeydown(event, 'description')}
        ></textarea>
        <span class="edit-hint" data-testid="workspace-detail-description-hint">{$text('common.detail_description_hint')}</span>
        <div class="field-actions">
          {#if descriptionChanged}
            <button type="button" data-testid="workspace-detail-description-save" aria-label={$text('common.save')} disabled={savingField === 'description'} onclick={() => void saveField('description')}><SaveIcon size={18} /></button>
          {/if}
          <button type="button" data-testid="workspace-detail-description-undo" aria-label={$text('common.cancel')} disabled={savingField === 'description'} onclick={cancelEdit}><UndoIcon size={18} /></button>
        </div>
      {:else}
        <button bind:this={descriptionDisplay} class="display-value description-value" type="button" data-testid={descriptionTestId} disabled={!writable} onclick={() => beginEdit('description')}>{description}</button>
        {#if writable}
          <button class="edit-affordance" type="button" data-testid="workspace-detail-description-edit" aria-label={$text('common.edit')} onclick={() => beginEdit('description')}><EditIcon size={18} /></button>
        {/if}
      {/if}
      {#if failedField === 'description'}
        <div class="save-error" role="alert" data-testid="workspace-detail-description-error">
          <span>{$text('common.detail_save_error')}</span>
          <button type="button" data-testid="workspace-detail-description-retry" onclick={() => void saveField('description')}>{$text('common.retry')}</button>
        </div>
      {/if}
    </div>{/if}

    {#if metadata}<span class="metadata">{metadata}</span>{/if}
  </div>
</section>

<style>
  .workspace-detail-header {
    position: relative;
    display: flex;
    width: 100%;
    min-height: 240px;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: 0 0 14px 14px;
    box-shadow: var(--shadow-xl);
    color: var(--color-grey-0);
    isolation: isolate;
  }

  .workspace-detail-header.embedded {
    min-height: 0;
    overflow: visible;
    border-radius: 0;
    box-shadow: none;
    color: inherit;
    isolation: auto;
  }

  .header-orbs,
  .header-orbs span,
  .decorative-icon {
    position: absolute;
  }

  .header-orbs { inset: 0; opacity: 0.45; }
  .header-orbs span { width: 48%; aspect-ratio: 1; border-radius: 50%; background: radial-gradient(circle, var(--orb-color), transparent 68%); filter: blur(28px); }
  .header-orbs span:nth-child(1) { inset: -30% auto auto -10%; }
  .header-orbs span:nth-child(2) { inset: auto -10% -45% auto; }
  .header-orbs span:nth-child(3) { inset: 15% auto auto 35%; opacity: 0.6; }
  .decorative-icon { top: 50%; z-index: 1; opacity: 0.35; transform: translateY(-50%); }
  .decorative-icon.left { left: var(--spacing-10); }
  .decorative-icon.right { right: var(--spacing-10); }

  .header-content {
    position: relative;
    z-index: 2;
    display: flex;
    width: min(760px, calc(100% - 64px));
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-5);
    padding: var(--spacing-10);
    text-align: center;
  }

  .embedded .header-content { width: 100%; padding: 0; }
  .align-start .header-content { align-items: flex-start; text-align: left; }
  .align-start .display-value, .align-start input, .align-start textarea { text-align: left; }
  .header-icon { height: 38px; }
  .editable-field { position: relative; width: 100%; }
  .display-value { width: 100%; border: 0; background: transparent; color: inherit; font: inherit; cursor: text; }
  .display-value:disabled { cursor: default; opacity: 1; }
  .title-value, .title-input { font-size: var(--font-size-h3); font-weight: 700; text-align: center; }
  .description-value, textarea { font-size: var(--font-size-small); line-height: 1.5; text-align: center; }
  .edit-affordance { position: absolute; top: 0; right: 0; opacity: 0; transition: opacity 0.2s ease; }
  .editable-field:hover .edit-affordance, .editable-field:focus-within .edit-affordance { opacity: 1; }

  input, textarea {
    box-sizing: border-box;
    width: 100%;
    border: 1px solid color-mix(in srgb, currentColor 60%, transparent);
    border-radius: var(--radius-3);
    background: color-mix(in srgb, var(--color-grey-100) 18%, transparent);
    color: inherit;
    padding: var(--spacing-5) var(--spacing-8);
    font-family: inherit;
  }
  textarea { resize: vertical; }
  input:focus-visible, textarea:focus-visible, button:focus-visible { outline: 2px solid currentColor; outline-offset: 3px; }
  button { min-width: 44px; min-height: 44px; border: 0; border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-100) 22%, transparent); color: inherit; cursor: pointer; }
  button:disabled { cursor: default; }
  .field-actions { display: flex; justify-content: center; gap: var(--spacing-3); margin-top: var(--spacing-3); }
  .edit-hint, .metadata { display: block; margin-top: var(--spacing-3); font-size: var(--font-size-xs); opacity: 0.78; }
  .save-error { display: flex; align-items: center; justify-content: center; gap: var(--spacing-3); margin-top: var(--spacing-3); font-size: var(--font-size-small); }

  @media (max-width: 730px) {
    .workspace-detail-header { min-height: 190px; }
    .decorative-icon { display: none; }
    .header-content { width: calc(100% - 24px); padding: var(--spacing-8); }
    .edit-affordance { opacity: 0.75; }
  }

  @media (prefers-reduced-motion: reduce) {
    .edit-affordance { transition: none; }
  }
</style>
