import type { ProjectReadmeState } from '../../services/projectReadme';

const ready: ProjectReadmeState = {
  status: 'ready',
  document: {
    path: 'README.md',
    origin: 'stored',
    imageUrls: {
      'docs/overview.png': '/favicon.png',
    },
    content: `# Aurora project

Plan and ship a calm, privacy-first workspace for the team.

![Project overview](docs/overview.png)

## Current focus

| Area | Status | Owner |
| --- | --- | --- |
| Research | Complete | Alex |
| Prototype | In progress | Sam |

### Run locally

\`\`\`bash
pnpm dev
\`\`\`

See the [public documentation](https://openmates.org) for more details.
`,
  },
};

function dispatch(action: string): void {
  window.dispatchEvent(new CustomEvent('project-readme-action', { detail: action }));
}

export default {
  state: ready,
  onUpload: () => dispatch('upload'),
  onCreate: () => dispatch('create'),
};

export const variants = {
  empty: {
    state: { status: 'empty' } satisfies ProjectReadmeState,
    onUpload: () => dispatch('upload'),
    onCreate: () => dispatch('create'),
  },
  loading: {
    state: { status: 'loading' } satisfies ProjectReadmeState,
    onUpload: () => dispatch('upload'),
    onCreate: () => dispatch('create'),
  },
  error: {
    state: { status: 'error', message: 'Could not load the connected README.' } satisfies ProjectReadmeState,
    onUpload: () => dispatch('upload'),
    onCreate: () => dispatch('create'),
    onRetry: () => dispatch('retry'),
  },
};
