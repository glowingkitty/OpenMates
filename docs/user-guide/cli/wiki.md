# Wikipedia

Search for an article, then read its summary and learning suggestions:

```bash
openmates wiki search "Ada Lovelace" --language en
openmates wiki show "Ada Lovelace" --language en
openmates wiki show "Ada Lovelace" --language en --json
```

Use your logged-in CLI session or an API key. `show` includes the same summary,
related articles and suggested questions as the web fullscreen article. The
article remains available if suggestion generation is temporarily unavailable.

The TypeScript and Python SDKs expose the same feature:

```typescript
const results = await openmates.wikipedia.search("Ada Lovelace");
const article = await openmates.wikipedia.article("Ada Lovelace");
```

```python
results = openmates.wikipedia.search("Ada Lovelace")
article = openmates.wikipedia.article("Ada Lovelace")
```

`wikipedia.summary()` reads only the article summary. `wikipedia.learning()`
reads only its public suggestions. Generated bundles use public article content,
never chat history, memories or personal data, and are shared in the server cache
for up to 24 hours. A suggested question becomes a normal chat message only when
you choose to send it; the existing chat's learning mode still applies.
