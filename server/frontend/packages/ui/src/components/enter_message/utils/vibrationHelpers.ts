// src/components/MessageInput/utils/vibrationHelpers.ts
/**
 * Vibrates the message field to indicate an error (e.g., trying to send an empty message).
 */
export function vibrateMessageField() {
    const container = document.querySelector('.message-field');
    if (!container) return;

    container.animate([
        { transform: 'translateX(-4px)' },
        { transform: 'translateX(4px)' },
        { transform: 'translateX(-4px)' },
        { transform: 'translateX(4px)' },
        { transform: 'translateX(0)' }
    ], {
        duration: 200,
        easing: 'ease-in-out'
    });

    if (navigator.vibrate) {
        navigator.vibrate(100);
    }
}