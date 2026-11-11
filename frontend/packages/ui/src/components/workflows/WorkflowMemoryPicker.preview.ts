import { sortMemoriesByRecency, type MentionableMemory } from '../../services/workflowMemorySnapshotService';

const titles = [
  'Preferred answer style', 'Weekly planning routine', 'Dietary restrictions and allergies to remember when suggesting recipes',
  'Home office setup', 'Travel preferences', 'Project Atlas kickoff notes and long-term stakeholder expectations',
  'Reading list', 'Garden watering schedule', 'Team contacts', 'Budget rules', 'Language learning goals', 'Weekend hobbies',
];
const memories: MentionableMemory[] = sortMemoriesByRecency(
  titles.map((title, index): MentionableMemory => ({ id: `memory-${index + 1}`, title, ...(index % 3 === 0 ? { updatedAt: 1_700_000_000 + index * 1000 } : {}) })),
);

export default { initialMemories: memories, query: '', disabled: false, onInsert: () => {}, onLoaded: () => {} };
