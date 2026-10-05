import type {AppMetadata} from '../../types/apps';

const app: AppMetadata = {
    id: 'design', name: 'Mobile preferences', description: 'Your preferred layout and interaction style.',
    icon_image: 'design.svg', providers: [], skills: [], focus_modes: [], settings_and_memories: [],
};

export default {
    app, cardIconType: 'memory', memoryVisibility: 'private',
    onSelect: (appId: string) => window.dispatchEvent(new CustomEvent('preview-memory-card-selected', {detail: appId})),
};

export const variants = {
    public: {
        app: {...app, name: 'Mobile first design', description: 'Best practices for accessible mobile interfaces.'},
        memoryVisibility: 'public',
    },
};
