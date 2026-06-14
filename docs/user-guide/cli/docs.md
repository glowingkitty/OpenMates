---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-11
claims:
  - id: cli-docs-command-reference-matches-help
    type: unit
    claim: Docs command reference lists the public docs commands exposed by CLI help.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-docs-command-reference-matches-help
    verified: '2026-06-11'
---

# Docs Commands

Browse, search, display, and download OpenMates documentation from the terminal. Docs commands are public and do not require login.

## Listing Docs

```
openmates docs list
openmates docs list --json
```

Prints the documentation tree with doc titles and slugs. Use the slug with `show` or `download`.

## Searching Docs

```
openmates docs search "encryption"
openmates docs search "billing" --json
```

Searches docs by keyword and prints matching titles, slugs, and snippets.

## Showing A Doc

```
openmates docs show user-guide/getting-started
openmates docs show architecture/core/security
```

Displays a Markdown doc in the terminal.

## Downloading Docs

```
openmates docs download architecture/core/security
openmates docs download architecture/core/security --output ./security.md
openmates docs download --all --output ./openmates-docs
```

Downloads one doc as Markdown, or downloads all docs into a local folder with `--all`.

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for `handleDocs()` and docs command routing
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for `listDocs()`, `searchDocs()`, and `getDoc()`

## Related Docs

- [README](./README.md) -- CLI overview
- [CLI Package Architecture](../../architecture/platforms/cli-package.md) -- package command surface
