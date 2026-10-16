import type { ProjectFocusActivationPolicy } from '../../services/projectService';

const defaultProps = {
  value: 'delayed' as ProjectFocusActivationPolicy,
  disabled: false,
  onChange: (value: ProjectFocusActivationPolicy) => {
    document.body.dataset.projectFocusPolicyChanged = value;
  },
};

export default defaultProps;

export const variants = {
  immediate: { ...defaultProps, value: 'immediate' as const },
  approval: { ...defaultProps, value: 'approval' as const },
  disabled: { ...defaultProps, disabled: true },
};
