declare global {
  namespace App {
    interface Locals {
      language: 'en' | 'de';
      languageMode: 'manual' | 'account' | 'auto';
    }
  }
}

export {};
