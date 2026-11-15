import { createReactiveTfaApps } from './tfaReactive.svelte';
import { loadTfaApps } from '../services/rustCore/auth/flowPush';

// The lists are owned by the shared Rust core. They start empty (neutral
// default) and are filled when the Worker answers. The app list is a `$state`
// array, so components that already rendered or captured it update on push.
export const tfaApps: string[] = createReactiveTfaApps();
export const tfaAppIcons: Record<string, string> = {};

void loadTfaApps(tfaApps, tfaAppIcons);
