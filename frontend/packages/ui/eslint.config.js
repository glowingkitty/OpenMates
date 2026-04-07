import { config } from '@repo/eslint-config/index.js';

export default [
  { ignores: ['src/tokens/generated/**'] },
  ...config
];
