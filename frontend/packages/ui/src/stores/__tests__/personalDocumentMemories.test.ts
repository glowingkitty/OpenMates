import {beforeEach, expect, it, vi} from 'vitest';
vi.mock('../authState', async () => {const {writable} = await import('svelte/store');return {authStore:writable({isAuthenticated:true})};});
vi.mock('../userProfile', async () => {const {writable} = await import('svelte/store');return {userProfile:writable({user_id:'owner',encrypted_settings:'revision'})};});
import {authStore} from '../authState';
import {userProfile} from '../userProfile';
import {personalDocumentMemories, currentPersonalDocumentMemories, publishPersonalDocumentMemories} from '../personalDocumentMemories';
import {get} from 'svelte/store';
const entry={id:'account-memory-a',app_id:'openmates',item_key:'Preference',settings_group:'memories',item_value:{title:'Preference',document:'Private guidance'},created_at:0,updated_at:0,item_version:1};
beforeEach(() => {personalDocumentMemories.set(null);authStore.set({isAuthenticated:true});userProfile.set({user_id:'owner',encrypted_settings:'revision'});});

// contract-test: supporting surface=gui.web assertions=app-memories.access.owner-scoped,app-memories.privacy.client-encrypted
it('clears transient private discovery immediately on logout, owner or ciphertext changes', () => {
  for (const change of [() => authStore.set({isAuthenticated:false}), () => userProfile.set({user_id:'other',encrypted_settings:'revision'}), () => userProfile.set({user_id:'owner',encrypted_settings:'changed'})]) {
    authStore.set({isAuthenticated:true});userProfile.set({user_id:'owner',encrypted_settings:'revision'});
    publishPersonalDocumentMemories('owner','revision',[entry]);
    expect(currentPersonalDocumentMemories()).toEqual([entry]);change();
    expect(currentPersonalDocumentMemories()).toEqual([]);expect(get(personalDocumentMemories)).toBeNull();
  }
});

// contract-test: supporting surface=gui.web assertions=app-memories.access.owner-scoped
it('does not publish a private read that completed for a stale owner or source revision', () => {
  publishPersonalDocumentMemories('other','revision',[entry]);
  publishPersonalDocumentMemories('owner','old',[entry]);
  expect(currentPersonalDocumentMemories()).toEqual([]);
});
