/** Deterministic account-free Tasks workspace matching the Figma board state. */

import '@fontsource-variable/lexend-deca';
import taskBoardPreview, { variants as boardVariants } from './TaskBoard.preview';

const defaultProps = {
  previewTasks: taskBoardPreview.tasks,
  previewPlans: taskBoardPreview.plans,
  previewProjectNames: taskBoardPreview.projectNames,
  previewAssigneeAvatarUrl: taskBoardPreview.assigneeAvatarUrl,
};

export default defaultProps;

export const variants = {
  project: {
    ...defaultProps,
    compact: true,
  },
  manyBacklog: {
    ...defaultProps,
    previewTasks: boardVariants.manyBacklog.tasks,
  },
};
