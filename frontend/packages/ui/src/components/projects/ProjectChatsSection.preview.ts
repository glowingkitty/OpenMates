import { item, presentation } from './ProjectChatPreview.preview';
const items = [item, { ...item, project_item_id: 'preview-chat-two', target_id: 'preview-chat-two', displayName: 'Audience research' }];
const presentations = { [item.target_id]: presentation, 'preview-chat-two': { ...presentation, title: 'Audience research', category: 'research', icon: 'search' } };
export default { items, presentations };
export const variants = { empty: { items: [], presentations: {} } };
