import type { ProjectItemViewModel } from '../../services/projectService';
import { presentation } from './ProjectChatPreview.preview';

/** A linked non-embed record renders without an authenticated embed resolver. */
const item: ProjectItemViewModel = {
  project_item_id: 'preview-project-item',
  item_type: 'chat',
  target_id: 'preview-chat',
  displayName: 'Project discussion',
  metadata: {},
  encrypted: {
    project_item_id: 'preview-project-item',
    item_type: 'chat',
    target_id_hash: 'preview-target-hash',
    target_id_encrypted: 'synthetic-ciphertext',
    created_at: 1,
    updated_at: 1,
    position: 0,
  },
};

const fixture = { item, viewMode: 'tile', chatPresentation: presentation, onOpenFullscreen: () => {} };
export default fixture;
export const variants = { list: { ...fixture, viewMode: 'list' } };
