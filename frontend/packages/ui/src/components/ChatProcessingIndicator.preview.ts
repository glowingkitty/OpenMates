/**
 * Preview fixtures for ChatProcessingIndicator.
 * The default is George's thinking status while the selecting variant has no
 * mate identity, matching the initial processing state.
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
    sending: {
        lines: ['Sending your message...'],
        statusType: 'sending',
    },
};
