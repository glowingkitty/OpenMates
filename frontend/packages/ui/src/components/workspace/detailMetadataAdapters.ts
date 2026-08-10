// frontend/packages/ui/src/components/workspace/detailMetadataAdapters.ts
// Domain-owned metadata adapters for unified workspace detail headers.
// The shared presentation component only passes plaintext to these adapters;
// Project, Task, and Plan services encrypt before API mutation, while Workflow
// stays inside its approved Automation Vault API/store boundary.

import { getProject, updateProjectMetadata, type ProjectViewModel } from '../../services/projectService';
import { listUserTasks, updateUserTask, type UserTaskViewModel } from '../../services/userTaskService';
import { listUserPlans, updateUserPlan, type UserPlanViewModel } from '../../services/userPlanService';
import { workflowWorkspaceStore, type WorkflowDetail } from '../../stores/workflowWorkspaceStore';

export type DetailMetadataAdapter<T> = {
  load: (id: string) => Promise<T>;
  saveTitle: (item: T, title: string) => Promise<T>;
  saveDescription: (item: T, description: string) => Promise<T>;
};

function requireItem<T>(item: T | undefined, domain: string): T {
  if (!item) throw new Error(`${domain} not found`);
  return item;
}

export const projectDetailAdapter: DetailMetadataAdapter<ProjectViewModel> = {
  load: getProject,
  saveTitle: (project, title) => updateProjectMetadata(project, { name: title }),
  saveDescription: (project, description) => updateProjectMetadata(project, { description }),
};

export const taskDetailAdapter: DetailMetadataAdapter<UserTaskViewModel> = {
  load: async (id) => requireItem((await listUserTasks()).find((task) => task.task_id === id), 'Task'),
  saveTitle: (task, title) => updateUserTask(task, { title }),
  saveDescription: (task, description) => updateUserTask(task, { description }),
};

export const planDetailAdapter: DetailMetadataAdapter<UserPlanViewModel> = {
  load: async (id) => requireItem((await listUserPlans()).find((plan) => plan.plan_id === id), 'Plan'),
  saveTitle: (plan, title) => updateUserPlan(plan, { title }),
  saveDescription: (plan, summary) => updateUserPlan(plan, { summary }),
};

export const workflowDetailAdapter: DetailMetadataAdapter<WorkflowDetail> = {
  load: async (id) => workflowWorkspaceStore.selectWorkflow(id),
  saveTitle: (workflow, title) => workflowWorkspaceStore.patchWorkflow(workflow.id, { title, version: workflow.version }),
  saveDescription: (workflow, description) => workflowWorkspaceStore.patchWorkflow(workflow.id, { description, version: workflow.version }),
};
