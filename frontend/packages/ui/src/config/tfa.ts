import { authFlowActive, loadTfaApps } from '../services/rustCore/auth/flowPush';


export const tfaApps: string[] = [
    'Google Authenticator',
    'Twilio Authy',
    'Microsoft Authenticator',
    '2FAS',
    'OTP Auth',
    'Proton Authenticator'
];

export const tfaAppIcons: Record<string, string> = {
    'Google Authenticator': 'google-authenticator',
    'Twilio Authy': 'authy',
    'Microsoft Authenticator': 'microsoft-authenticator',
    '2FAS': 'tfas',
    'OTP Auth': 'otp-auth',
    'Proton Authenticator': 'proton-authenticator'
};

// Flag builds: the lists are owned by the shared Rust core. They start empty
// (neutral default) and are filled in place once the Worker answers, which is
// long before the signup and security screens that read them are opened.
if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && authFlowActive()) {
    tfaApps.length = 0;
    for (const name of Object.keys(tfaAppIcons)) delete tfaAppIcons[name];
    void loadTfaApps(tfaApps, tfaAppIcons);
}
