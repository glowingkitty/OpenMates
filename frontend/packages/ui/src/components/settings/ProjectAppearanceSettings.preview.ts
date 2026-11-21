import type { ProjectViewModel } from '../../services/projectService';

const now = Math.floor(Date.now() / 1000);
const project: ProjectViewModel = {
  project_id: 'preview-recipes',
  name: 'Recipe Keeper',
  description: 'Save, plan and cook your family recipes in one place.',
  icon: 'chef-hat',
  category: 'cooking_food',
  presentationState: null,
  projectKey: new Uint8Array(32),
  encrypted: {
    project_id: 'preview-recipes', encrypted_project_key: 'preview', encrypted_name: 'preview',
    created_at: now, updated_at: now, last_opened_at: now, item_count: 3,
  },
};

const defaultProps = {
  project,
  onSaved: (updated: ProjectViewModel) => {
    document.body.dataset.projectAppearanceSaved = `${updated.icon}|${updated.category ?? ''}`;
  },
};

export default defaultProps;

export const variants = {
  legacy: { ...defaultProps, project: { ...project, name: 'Kitchen renovation', icon: 'folder', category: '' } },
};
