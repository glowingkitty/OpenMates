/**
 * Preview fixtures for ChatProcessingIndicator.
 * The default resolves general_knowledge to George's known thinking state.
 * The selecting variant intentionally has no mate identity.
 * onMateClick emits a browser event so preview interaction is observable.
 */

function emitMateClick() {
    window.dispatchEvent(new CustomEvent('openmates-preview-mate-click', {
        detail: { mateCategory: 'general_knowledge' },
    }));
}

const defaultProps = {
    lines: ['George is thinking...'],
    mateCategory: 'general_knowledge',
    statusType: 'typing',
    onMateClick: emitMateClick,
};

export default defaultProps;

export const variants = {
    selecting: {
        lines: ['Selecting mate & AI model...'],
        mateCategory: null,
        statusType: 'processing',
    },
};
