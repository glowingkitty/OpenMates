<!-- frontend/packages/ui/src/components/settings/AppSettingsMemoriesCreateEntry.svelte
     Component for creating a new entry in a specific app settings/memories category.
     
     This component is used for the app_store/{app_id}/settings_memories/{category_id}/create nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time) for category definition
     - Storage: IndexedDB (encrypted with app-specific keys)
     - Types: frontend/packages/ui/src/types/apps.ts
     
     **Zero-Knowledge Architecture**:
     - Entry is encrypted before storage
     - Client-side encryption & decryption of entries
-->
<script lang="ts">
    import { untrack } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import type { AppMetadata, MemoryFieldMetadata, SchemaPropertyDefinition } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';

    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();

    // Check if user is authenticated
    let isAuthenticated = $derived($authStore.isAuthenticated);

    interface Props {
        appId: string;
        categoryId: string;
    }

    let { appId, categoryId }: Props = $props();

    // Debug logging
    console.log('[AppSettingsMemoriesCreateEntry] Component initialized with:', { appId, categoryId });

    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());

    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let category = $derived<MemoryFieldMetadata | undefined>(
        app?.settings_and_memories.find(c => c.id === categoryId)
    );
    
    // Debug logging for derived values (using snapshots to avoid proxy warnings)
    $effect(() => {
        console.log('[AppSettingsMemoriesCreateEntry] App:', app?.id, app ? 'found' : 'not found');
        console.log('[AppSettingsMemoriesCreateEntry] Category:', category?.id, category ? 'found' : 'not found');
        console.log('[AppSettingsMemoriesCreateEntry] Schema:', category?.schema_definition ? 'exists' : 'missing');
        console.log('[AppSettingsMemoriesCreateEntry] Is authenticated:', isAuthenticated);
    });

    /**
     * Get the translated category name.
     */
    let categoryName = $derived(
        category?.name_translation_key
            ? $text(category.name_translation_key)
            : categoryId
    );

    /**
     * Get the translated category description.
     */
    let categoryDescription = $derived(
        category?.description_translation_key
            ? $text(category.description_translation_key)
            : ''
    );

    // Get schema from category metadata
    let schema = $derived(category?.schema_definition);
    
    // Filter out auto_generated fields - these are populated automatically, not by user input
    // Returns only the properties that should be shown in the form
    // Using $derived.by() for complex computations with return statements
    let userInputProperties = $derived.by<Record<string, SchemaPropertyDefinition>>(() => {
        if (!schema?.properties) return {};
        const filtered: Record<string, SchemaPropertyDefinition> = {};
        for (const [key, prop] of Object.entries(schema.properties)) {
            // Only include fields that are NOT auto_generated
            if (!prop.auto_generated) {
                filtered[key] = prop;
            }
        }
        return filtered;
    });
    
    // Form state - dynamic based on schema (only user-input fields)
    // If schema exists, create fields for each non-auto_generated property
    // Otherwise, use generic form with itemKey and itemValue
    let formState = $state<Record<string, unknown>>({});
    let isCreating = $state(false);
    let createError = $state('');
    
    // Track if form has been initialized to prevent infinite loops
    // Use regular variables (not $state) to avoid reactivity loops
    let formInitialized = false;
    let lastSchemaId: string | null = null;
    
    // Initialize form state based on schema (only once per schema change)
    // Use untrack to prevent formState writes from triggering the effect again
    $effect(() => {
        // Create a unique identifier for the current schema to detect changes
        const currentSchemaId = schema ? JSON.stringify(schema) : 'no-schema';
        
        // Only initialize if schema changed or form hasn't been initialized yet
        if (lastSchemaId === currentSchemaId && formInitialized) {
            return; // Skip if already initialized for this schema
        }
        
        // Use untrack to prevent formState updates from retriggering this effect
        untrack(() => {
            if (Object.keys(userInputProperties).length > 0) {
                // Initialize form fields from user-input properties only (excludes auto_generated)
                const initialState: Record<string, unknown> = {};
                for (const [key, prop] of Object.entries(userInputProperties)) {
                    // Set default value if provided, otherwise empty string or appropriate default
                    if (prop.default !== undefined) {
                        initialState[key] = prop.default;
                    } else if (prop.type === 'integer' || prop.type === 'number') {
                        initialState[key] = '';
                    } else if (prop.type === 'boolean') {
                        initialState[key] = false;
                    } else {
                        initialState[key] = '';
                    }
                }
                // Replace formState completely but only when schema actually changes
                formState = initialState;
            } else {
                // Fallback to generic form
                formState = {
                    itemKey: '',
                    itemValue: '',
                    settingsGroup: ''
                };
            }
            
            // Mark as initialized and track schema ID (also untracked to prevent loops)
            formInitialized = true;
            lastSchemaId = currentSchemaId;
        });
    });

    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        // Handle special case: coding.svg -> code (since the app ID is "code" but icon file is coding.svg)
        // This ensures the correct CSS variable --color-app-code is used instead of --color-app-coding
        if (iconName === 'coding') {
            iconName = 'code';
        }
        return iconName;
    }
    
    /**
     * Navigate back to category page (settings and memories category page, not app details).
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: category?.name_translation_key ? $text(category.name_translation_key) : categoryId
        });
    }
    
    /**
     * Build an auto-generated title from other entry fields (e.g. for health appointments:
     * "dental - Dr. Mueller - 2025-03-15"). Used when schema has title with auto_generated: true.
     */
    function buildAutoTitleFromEntry(
        entryValue: Record<string, unknown>,
        schema: MemoryFieldMetadata['schema_definition']
    ): string {
        if (!schema?.properties) return 'Untitled';
        const parts: string[] = [];
        for (const [key, prop] of Object.entries(schema.properties)) {
            if (key === 'title' || prop.auto_generated) continue;
            const v = entryValue[key];
            if (v === undefined || v === null) continue;
            const s = String(v).trim();
            if (s === '') continue;
            // Format enum-style values (e.g. doctor_visit → Doctor visit)
            parts.push(s.includes('_') && !s.includes(' ') ? s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : s);
        }
        return parts.length > 0 ? parts.join(' - ') : 'Untitled';
    }
    
    /**
     * Validate form fields based on schema requirements.
     * Only validates user-input fields (excludes auto_generated fields).
     */
    function validateForm(): string | null {
        if (Object.keys(userInputProperties).length === 0) {
            // Generic form validation (fallback when no schema)
            if (!formState.itemKey || String(formState.itemKey).trim() === '') {
                return $text('settings.app_settings_memories.item_key_required');
            }
            if (!formState.itemValue || String(formState.itemValue).trim() === '') {
                return $text('settings.app_settings_memories.item_value_required');
            }
            return null;
        }
        
        // Schema-based validation - only check required fields that are NOT auto_generated
        const required = schema?.required || [];
        for (const fieldName of required) {
            // Skip validation for auto_generated fields (they'll be populated automatically)
            if (schema?.properties?.[fieldName]?.auto_generated) {
                continue;
            }
            
            const value = formState[fieldName];
            if (value === undefined || value === null || String(value).trim() === '') {
                const prop = userInputProperties[fieldName];
                const fieldLabel = prop?.description || fieldName;
                return `${fieldLabel} is required`;
            }
        }
        
        // Type validation for user-input fields only
        for (const [fieldName, prop] of Object.entries(userInputProperties)) {
            const value = formState[fieldName];
            if (value === undefined || value === null || String(value).trim() === '') {
                continue; // Skip empty optional fields
            }
            
            if (prop.type === 'integer' || prop.type === 'number') {
                const numValue = Number(value);
                if (isNaN(numValue)) {
                    return `${prop.description || fieldName} must be a number`;
                }
                if (prop.minimum !== undefined && numValue < prop.minimum) {
                    return `${prop.description || fieldName} must be at least ${prop.minimum}`;
                }
                if (prop.maximum !== undefined && numValue > prop.maximum) {
                    return `${prop.description || fieldName} must be at most ${prop.maximum}`;
                }
            }
        }
        
        return null;
    }
    
    /**
     * Handle form submission to create a new entry.
     * This creates an entry specific to this category type.
     * Auto-populates auto_generated fields (like timestamps).
     */
    async function handleCreateEntry() {
        createError = '';
        
        // Validate form
        const validationError = validateForm();
        if (validationError) {
            createError = validationError;
            return;
        }

        isCreating = true;
        try {
            let entryValue: Record<string, unknown>;
            let itemKey: string;
            let settingsGroup: string;
            
            if (schema?.properties && Object.keys(userInputProperties).length > 0) {
                // Build entry value from schema-based form
                entryValue = {};
                
                // First, add user-input fields from form
                for (const [key, prop] of Object.entries(userInputProperties)) {
                    const value = formState[key];
                    if (value !== undefined && value !== null && String(value).trim() !== '') {
                        // Convert value to appropriate type
                        if (prop.type === 'integer') {
                            entryValue[key] = parseInt(String(value), 10);
                        } else if (prop.type === 'number') {
                            entryValue[key] = parseFloat(String(value));
                        } else if (prop.type === 'boolean') {
                            entryValue[key] = Boolean(value);
                        } else {
                            entryValue[key] = String(value).trim();
                        }
                    }
                }
                
                // Then, auto-populate auto_generated fields
                const now = Math.floor(Date.now() / 1000); // Unix timestamp in seconds
                for (const [key, prop] of Object.entries(schema.properties)) {
                    if (prop.auto_generated) {
                        // Auto-generate based on field name patterns
                        if (key === 'title') {
                            // Build title from other entry fields (e.g. appointment type + where + date)
                            entryValue[key] = buildAutoTitleFromEntry(entryValue, schema);
                        } else if (key.includes('date') || key.includes('_at') || key === 'timestamp') {
                            // Timestamp fields get current time
                            entryValue[key] = now;
                        } else if (key === 'id' || key === 'entry_id') {
                            // ID fields get a UUID
                            entryValue[key] = crypto.randomUUID();
                        } else if (prop.type === 'integer' || prop.type === 'number') {
                            // Default numeric auto-generated to current timestamp
                            entryValue[key] = now;
                        } else {
                            // Default string auto-generated to empty
                            entryValue[key] = '';
                        }
                    }
                }
                
                // Generate item key from category and a unique field value
                // For bookmarks, use URL as key identifier
                const urlField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase().includes('url') || k.toLowerCase() === 'url'
                );
                const nameField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase() === 'name' || k.toLowerCase() === 'title'
                );
                const titleIsAutoGenerated = nameField && schema.properties?.[nameField]?.auto_generated;
                
                if (urlField && formState[urlField]) {
                    itemKey = `${categoryId}.${String(formState[urlField]).trim()}`;
                } else if (nameField && (titleIsAutoGenerated ? entryValue[nameField] : formState[nameField])) {
                    const titleVal = titleIsAutoGenerated ? String(entryValue[nameField] || '').trim() : String(formState[nameField]).trim();
                    itemKey = `${categoryId}.${titleVal || Date.now()}`;
                } else {
                    // Use first required field or first user-input field as key
                    const firstRequired = schema.required?.find(r => !schema.properties?.[r]?.auto_generated);
                    const firstField = firstRequired || Object.keys(userInputProperties)[0];
                    itemKey = `${categoryId}.${String(formState[firstField] || Date.now()).trim()}`;
                }
                
                // CRITICAL: Use categoryId (not categoryName) as settings_group
                // The filtering in AppSettingsMemoriesCategory.svelte uses categoryId to filter entries:
                //   const categoryEntries = groupedEntries[categoryId];
                // So the stored settings_group MUST match the categoryId, not the translated name
                settingsGroup = categoryId;
            } else {
                // Generic form - parse JSON or use plain text
                try {
                    entryValue = JSON.parse(String(formState.itemValue));
                } catch {
                    entryValue = { value: String(formState.itemValue).trim() };
                }
                itemKey = String(formState.itemKey).trim();
                settingsGroup = String(formState.settingsGroup || itemKey.split('.')[0] || categoryName).trim();
            }

            // Create the entry (this will handle encryption)
            await appSettingsMemoriesStore.createEntry(appId, {
                item_key: itemKey,
                item_value: entryValue,
                settings_group: settingsGroup
            });

            // Navigate back to category page after successful creation
            goBack();
        } catch (error) {
            createError = error instanceof Error ? error.message : 'Failed to create entry';
            console.error('[AppSettingsMemoriesCreateEntry] Error creating entry:', error);
        } finally {
            isCreating = false;
        }
    }
    
    /**
     * Reset form and navigate back.
     */
    function handleCancel() {
        // Reset form state based on user-input properties (excludes auto_generated)
        if (Object.keys(userInputProperties).length > 0) {
            const resetState: Record<string, unknown> = {};
            for (const [key, prop] of Object.entries(userInputProperties)) {
                if (prop.default !== undefined) {
                    resetState[key] = prop.default;
                } else if (prop.type === 'integer' || prop.type === 'number') {
                    resetState[key] = '';
                } else if (prop.type === 'boolean') {
                    resetState[key] = false;
                } else {
                    resetState[key] = '';
                }
            }
            formState = resetState;
        } else {
            formState = { itemKey: '', itemValue: '', settingsGroup: '' };
        }
        createError = '';
        goBack();
    }
    
    /**
     * Check if a field is required.
     * Note: auto_generated required fields are handled automatically, 
     * so we only mark user-input fields as required in the UI.
     */
    function isFieldRequired(fieldName: string): boolean {
        // Only mark as required if it's in the required list AND not auto_generated
        if (!schema?.required?.includes(fieldName)) return false;
        if (schema?.properties?.[fieldName]?.auto_generated) return false;
        return true;
    }
</script>

<div class="app-settings-memories-create">
    {#if !app || !category}
        <div class="error">
            <p>Error: {!app ? 'App not found' : 'Category not found'}</p>
            <p>App ID: {appId}, Category ID: {categoryId}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else if !isAuthenticated}
        <div class="error">
            <p>{$text('settings.app_settings_memories.authentication_required')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- Category description at the top -->
        <div class="header">
            <h1>{$text('settings.app_settings_memories.add_entry')}</h1>
            {#if categoryDescription}
                <p class="description">{categoryDescription}</p>
            {/if}
        </div>

        <!-- Create entry form -->
        <div class="form-container">
            {#if Object.keys(userInputProperties).length > 0}
                <!-- Schema-based form: Generate fields from user-input properties (excludes auto_generated) -->
                {#each Object.entries(userInputProperties) as [fieldName, prop]}
                    <div class="form-group">
                        <label for={fieldName}>
                            {prop.description || fieldName}
                            {#if isFieldRequired(fieldName)}
                                <span class="required">*</span>
                            {/if}
                        </label>
                        {#if prop.type === 'boolean'}
                            <div class="checkbox-group">
                                <input
                                    id={fieldName}
                                    type="checkbox"
                                    checked={Boolean(formState[fieldName])}
                                    onchange={(e) => formState[fieldName] = (e.target as HTMLInputElement).checked}
                                    disabled={isCreating}
                                />
                                <span class="checkbox-label">{prop.description || fieldName}</span>
                            </div>
                        {:else if prop.type === 'integer' || prop.type === 'number'}
                            <input
                                id={fieldName}
                                type="number"
                                bind:value={formState[fieldName]}
                                placeholder={prop.description || fieldName}
                                min={prop.minimum}
                                max={prop.maximum}
                                step={prop.type === 'integer' ? 1 : undefined}
                                disabled={isCreating}
                            />
                        {:else if prop.enum}
                            <select
                                id={fieldName}
                                bind:value={formState[fieldName]}
                                disabled={isCreating}
                            >
                                <option value="">Select {prop.description || fieldName}</option>
                                {#each prop.enum as enumValue}
                                    <option value={enumValue}>{enumValue}</option>
                                {/each}
                            </select>
                        {:else}
                            <input
                                id={fieldName}
                                type="text"
                                bind:value={formState[fieldName]}
                                placeholder={prop.description || fieldName}
                                disabled={isCreating}
                            />
                        {/if}
                        {#if prop.description}
                            <small>{prop.description}</small>
                        {/if}
                    </div>
                {/each}
            {:else}
                <!-- Generic form: Fallback when no schema is defined -->
                <div class="form-group">
                    <label for="item-key">
                        {$text('settings.app_settings_memories.item_key')}
                        <span class="required">*</span>
                    </label>
                    <input
                        id="item-key"
                        type="text"
                        bind:value={formState.itemKey}
                        placeholder="e.g., favorite_movie or watched.2024"
                        disabled={isCreating}
                    />
                    <small>Key to identify this setting/memory entry</small>
                </div>

                <div class="form-group">
                    <label for="settings-group">
                        {$text('settings.app_settings_memories.settings_group')}
                    </label>
                    <input
                        id="settings-group"
                        type="text"
                        bind:value={formState.settingsGroup}
                        placeholder="e.g., Movies (defaults to first part of item key)"
                        disabled={isCreating}
                    />
                    <small>Group to organize this entry under</small>
                </div>

                <div class="form-group">
                    <label for="item-value">
                        {$text('settings.app_settings_memories.item_value')}
                        <span class="required">*</span>
                    </label>
                    <textarea
                        id="item-value"
                        bind:value={formState.itemValue}
                        placeholder="Example: JSON object or plain text"
                        rows="6"
                        disabled={isCreating}
                    ></textarea>
                    <small>Value can be JSON or plain text. JSON will be automatically parsed.</small>
                </div>
            {/if}

            {#if createError}
                <div class="error-message">{createError}</div>
            {/if}

            <div class="form-footer">
                <button class="cancel-btn" onclick={handleCancel} disabled={isCreating}>
                    {$text('settings.app_settings_memories.cancel')}
                </button>
                <button
                    class="create-btn"
                    onclick={handleCreateEntry}
                    disabled={isCreating}
                >
                    {isCreating ? $text('settings.app_settings_memories.creating') : $text('settings.app_settings_memories.add_entry')}
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .app-settings-memories-create {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .header {
        margin-bottom: 2rem;
        padding-left: 0;
    }
    
    .header h1 {
        margin: 0 0 0.5rem 0;
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--text-primary, #000000);
    }
    
    .description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }
    
    .form-container {
        padding-left: 0;
    }
    
    .form-group {
        margin-bottom: 1.5rem;
    }
    
    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 500;
        color: var(--text-primary);
    }
    
    .required {
        color: var(--error-color, #dc3545);
    }
    
    input,
    textarea,
    select {
        width: 100%;
        padding: 0.75rem;
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        font-family: inherit;
        font-size: 0.95rem;
        color: var(--text-primary);
        background: var(--color-white);
        transition: border-color 0.2s ease;
        box-sizing: border-box;
    }
    
    .checkbox-group {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .checkbox-group input[type="checkbox"] {
        width: auto;
        margin: 0;
    }
    
    .checkbox-label {
        color: var(--text-primary);
        font-size: 0.95rem;
    }
    
    input:focus,
    textarea:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 3px rgba(0, 95, 163, 0.1);
    }
    
    input:disabled,
    textarea:disabled {
        background: var(--color-grey-15);
        cursor: not-allowed;
        opacity: 0.6;
    }
    
    small {
        display: block;
        margin-top: 0.25rem;
        color: var(--text-secondary);
        font-size: 0.8rem;
    }
    
    .error-message {
        padding: 1rem;
        background: var(--color-error-light, #f8d7da);
        border: 1px solid var(--color-error, #f5c6cb);
        border-radius: 6px;
        color: var(--error-color, #721c24);
        margin-bottom: 1rem;
    }
    
    .form-footer {
        display: flex;
        gap: 1rem;
        justify-content: flex-end;
        margin-top: 2rem;
    }
    
    .cancel-btn,
    .create-btn {
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        border: none;
        cursor: pointer;
        font-size: 0.95rem;
        font-weight: 500;
        transition: background-color 0.2s ease;
    }
    
    .cancel-btn {
        background: var(--color-grey-30);
        color: var(--text-primary);
    }
    
    .cancel-btn:hover:not(:disabled) {
        background: var(--color-grey-40);
    }
    
    .create-btn {
        background: var(--color-primary);
        color: white;
    }
    
    .create-btn:hover:not(:disabled) {
        background: var(--color-primary-dark, #005fa3);
    }
    
    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
</style>
