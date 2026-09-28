/** Account-free login form states for focused input verification. */
export default {
    email: 'preview@example.com',
    previewMode: true,
    tfaAppName: 'Authenticator',
};

export const variants = {
    otp: { tfa_required: true },
};
