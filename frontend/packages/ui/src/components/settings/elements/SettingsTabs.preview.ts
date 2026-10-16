/** Icon-only settings tabs with a selected gradient pill. */
export default {
    tabs: [
        { id: 'overview', icon: 'app', label: 'Overview' },
        { id: 'results', icon: 'files', label: 'Results' },
        { id: 'workflows', icon: 'workflow', label: 'Workflows' },
    ],
    activeTab: 'overview',
    maxVisibleTabs: 3,
    testIdPrefix: 'preview-settings-tab',
};
