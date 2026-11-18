/** One-line reason shown next to the signed-out Sign up / Log in button. */
export default { reason: 'status_unavailable' };

export const variants = {
    loggedInBefore: { reason: 'logged_in_before' },
    usageLimit: { reason: 'usage_limit' },
    unavailable: { reason: 'unavailable' },
    statusUnavailable: { reason: 'status_unavailable' },
    fileRequiresAccount: { reason: 'file_requires_account' },
};
