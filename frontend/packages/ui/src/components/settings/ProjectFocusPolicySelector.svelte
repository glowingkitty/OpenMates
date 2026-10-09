<script lang="ts">
    import { text } from '@repo/ui';
    import { SettingsDropdown } from './elements';
    import type { ProjectFocusActivationPolicy } from '../../services/projectService';

    let { value, disabled = false, onChange }: {
        value: ProjectFocusActivationPolicy;
        disabled?: boolean;
        onChange: (value: ProjectFocusActivationPolicy) => void;
    } = $props();

    function handleChange(next: string): void {
        if (next === 'delayed' || next === 'immediate' || next === 'approval') onChange(next);
    }
</script>

<SettingsDropdown
    {value}
    options={[
        { value: 'delayed', label: $text('projects.focus_activation_policy_delayed') },
        { value: 'immediate', label: $text('projects.focus_activation_policy_immediate') },
        { value: 'approval', label: $text('projects.focus_activation_policy_approval') },
    ]}
    ariaLabel={$text('projects.focus_activation_policy_label')}
    dataTestid="project-settings-focus-activation-policy"
    {disabled}
    onChange={handleChange}
/>
