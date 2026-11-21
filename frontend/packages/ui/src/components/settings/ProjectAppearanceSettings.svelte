<!--
  Project appearance in Project settings (TASK-1807): the icon and the category whose
  chat gradient the Project tile uses. A choice made here is recorded by the Rust core
  as the user's, so the assistant, the Specification refresh and the backfill never
  overwrite it. Shown only with the shared Rust core (flag-on builds).
  spec: specifications/features/projects#projects.presentation.manual-lock
-->
<script lang="ts">
    import { SettingsDropdown, SettingsInfoBox, SettingsSectionHeading } from './elements';
    import { getCategoryGradientColors } from '../../utils/categoryUtils';
    import type { ProjectViewModel } from '../../services/projectService';
    import { saveProjectPresentationByUser } from '../../services/projectPresentationService';

    let { project, onSaved }: {
        project: ProjectViewModel;
        onSaved: (project: ProjectViewModel) => void;
    } = $props();

    // Same ids as PRESENTATION_CATEGORIES in the Rust core (contract section 2).
    const CATEGORIES: Array<[string, string]> = [
        ['software_development', 'Software development'], ['business_development', 'Business'],
        ['medical_health', 'Health'], ['legal_law', 'Legal'], ['maker_prototyping', 'Maker and prototyping'],
        ['marketing_sales', 'Marketing and sales'], ['finance', 'Finance'], ['design', 'Design'],
        ['electrical_engineering', 'Electrical engineering'], ['movies_tv', 'Movies and TV'], ['history', 'History'],
        ['science', 'Science'], ['life_coach_psychology', 'Life coaching'], ['cooking_food', 'Cooking and food'],
        ['activism', 'Activism'], ['general_knowledge', 'General knowledge'],
    ];
    const ICONS: Array<[string, string]> = [
        ['folder', 'Folder'], ['code', 'Code'], ['app-window', 'App'], ['smartphone', 'Mobile app'],
        ['gamepad-2', 'Game'], ['chef-hat', 'Cooking'], ['book-open', 'Book'], ['graduation-cap', 'Learning'],
        ['briefcase', 'Business'], ['wallet', 'Money'], ['chart-line', 'Chart'], ['megaphone', 'Marketing'],
        ['palette', 'Design'], ['camera', 'Photo'], ['film', 'Film'], ['music', 'Music'], ['heart-pulse', 'Health'],
        ['scale', 'Legal'], ['flask-conical', 'Science'], ['cpu', 'Electronics'], ['wrench', 'Tools'],
        ['house', 'Home'], ['plane', 'Travel'], ['calendar-check', 'Planning'], ['users', 'People'], ['leaf', 'Nature'],
    ];

    let saving = $state(false);
    let failed = $state(false);
    let iconValue = $derived(project.icon || 'folder');
    let categoryValue = $derived(project.category || '');
    let iconOptions = $derived([
        ...(ICONS.some(([id]) => id === iconValue) ? [] : [{ value: iconValue, label: iconValue }]),
        ...ICONS.map(([value, label]) => ({ value, label })),
    ]);
    const categoryOptions = CATEGORIES.map(([value, label]) => {
        const colors = getCategoryGradientColors(value);
        return {
            value, label, iconText: ' ',
            iconBackground: colors ? `linear-gradient(135deg, ${colors.start}, ${colors.end})` : undefined,
        };
    });

    async function save(changed: { icon?: string; category?: string }): Promise<void> {
        saving = true;
        failed = false;
        try {
            onSaved(await saveProjectPresentationByUser(project, changed));
        } catch (error) {
            console.error('[ProjectAppearanceSettings] save failed:', error);
            failed = true;
        } finally {
            saving = false;
        }
    }
</script>

<div data-testid="project-appearance-settings">
    <SettingsSectionHeading title="Appearance" icon="project" />
    <SettingsDropdown
        value={categoryValue}
        options={categoryOptions}
        placeholder="Choose a category"
        ariaLabel="Project category"
        dataTestid="project-appearance-category"
        rich
        disabled={saving}
        onChange={(value) => { if (value !== categoryValue) void save({ category: value }); }}
    />
    <SettingsDropdown
        value={iconValue}
        options={iconOptions}
        ariaLabel="Project icon"
        dataTestid="project-appearance-icon"
        disabled={saving}
        onChange={(value) => { if (value !== iconValue) void save({ icon: value }); }}
    />
    <SettingsInfoBox type="info"><p>The tile uses this category's colours. What you choose here stays; the assistant does not change it.</p></SettingsInfoBox>
    {#if failed}
        <SettingsInfoBox type="warning"><p>Could not save the appearance. Try again.</p></SettingsInfoBox>
    {/if}
</div>
