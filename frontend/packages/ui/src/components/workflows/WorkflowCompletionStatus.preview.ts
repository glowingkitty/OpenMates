const onRetry = () => window.dispatchEvent(new CustomEvent('workflow-preview-completion-retry'));

export default { status: 'waiting' as const, onRetry };
export const variants = { unavailable: { status: 'unavailable' as const, onRetry } };
