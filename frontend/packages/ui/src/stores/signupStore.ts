import { writable } from 'svelte/store';

export const signupStore = writable({
  email: '',
  username: '',
  password: '',
  inviteCode: '',
  language: '',
  darkmode: false,
  stayLoggedIn: false,
  encryptedMasterKey: '',
  salt: ''
});

export function clearSignupData() {
  signupStore.set({
    email: '',
    username: '',
    password: '',
    inviteCode: '',
    language: '',
    darkmode: false,
    stayLoggedIn: false,
    encryptedMasterKey: '',
    salt: ''
  });
}
