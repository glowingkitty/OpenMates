import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

export const config = ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs['flat/recommended'],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node
      }
    },
    rules: {
      // Warn on console.log/debug/info — allow console.warn and console.error
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      // Prefix unused vars with _ to indicate intentional non-use
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_'
      }],
    }
  },
  {
    files: ['**/*.svelte'],
    ignores: ['.svelte-kit/*'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser
      },
      globals: {
        // DOM types used in Svelte event handler typings
        EventListener: 'readonly',
        // WebAuthn API types
        PublicKeyCredentialRequestOptions: 'readonly',
        PublicKeyCredentialCreationOptions: 'readonly',
        UserVerificationRequirement: 'readonly',
        AttestationConveyancePreference: 'readonly',
        AuthenticationExtensionsClientInputs: 'readonly',
        // Node.js types used in Svelte
        NodeJS: 'readonly',
      }
    }
  },
  {
    files: ['**/*.test.ts', '**/*.spec.ts', '**/*.test.js'],
    rules: {
      // Tests often use any for mocking
      '@typescript-eslint/no-explicit-any': 'off',
    }
  }
);
