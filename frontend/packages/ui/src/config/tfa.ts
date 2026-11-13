import { createReactiveTfaApps } from './tfaReactive.svelte';
import { authFlowActive, loadTfaApps } from '../services/rustCore/auth/flowPush';

// Flag builds: the lists are owned by the shared Rust core. They start empty
// (neutral default) and are filled when the Worker answers. The app list is a
// `$state` array, so components that already rendered or captured it update on push.
const rustOwned: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && authFlowActive();

export const tfaApps: string[] = rustOwned ? createReactiveTfaApps() : [
    'Google Authenticator',
    'Twilio Authy',
    'Microsoft Authenticator',
    '2FAS',
    'OTP Auth',
    'Proton Authenticator'
];

export const tfaAppIcons: Record<string, string> = rustOwned ? {} : {
    'Google Authenticator': 'google-authenticator',
    'Twilio Authy': 'authy',
    'Microsoft Authenticator': 'microsoft-authenticator',
    '2FAS': 'tfas',
    'OTP Auth': 'otp-auth',
    'Proton Authenticator': 'proton-authenticator'
};

if (rustOwned) void loadTfaApps(tfaApps, tfaAppIcons);
