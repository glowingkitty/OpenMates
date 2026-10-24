# Social Media App

The Social Media app exposes normalized post/comment retrieval and topic search
across social platforms. `get-posts` is for known profiles/pages. `search` is for
topic discovery across supported platforms.

## Current Providers

- `bluesky_public` fetches profile feeds and post search results through the
  official Bluesky AppView APIs.
- Bluesky profile feeds use `app.bsky.feed.getAuthorFeed` and require no API key.
- Bluesky replies use `app.bsky.feed.getPostThread` and hydrate direct replies
  into the normalized `comments` field when requested.
- Bluesky topic search uses `app.bsky.feed.searchPosts`. It first tries the
  public AppView and can use authenticated PDS requests when credentials are
  configured.
- Store Bluesky credentials via the normal `SECRET__*` migration convention:
  `SECRET__BLUESKY__IDENTIFIER` and `SECRET__BLUESKY__APP_PASSWORD` migrate to
  `kv/data/providers/bluesky` as `identifier` and `app_password`.
- `mastodon_public` fetches public account statuses, instance-local status
  search results, and status contexts through unauthenticated Mastodon instance
  APIs.
- Mastodon `get-posts` accepts profile URLs or account IDs in `user@instance`
  format. Replies are fetched from `/api/v1/statuses/{id}/context` and may be
  incomplete because each instance only knows federated content it has received.
- Mastodon `search` uses `/api/v2/search?type=statuses`, searches
  `mastodon.social` by default, and accepts extra public instances via
  `mastodon_instances`. When status search is empty, it falls back to the public
  tag timeline for the normalized query (for example `open source` ->
  `#opensource`). Results are instance-local and depend on each server's public
  search configuration.

## Request Modes

- `get-posts` is for one or multiple specific pages/profiles. Callers pass
  `platform` and `page` for each requested source. Mastodon pages must include
  an instance, for example `Gargron@mastodon.social` or
  `https://mastodon.social/@Gargron`.
- `search` is for finding recent public posts around a topic. Callers pass
  `platform` and `query`, with optional provider filters such as Bluesky
  `author` or Mastodon `mastodon_instances`.
- Mastodon broad search is intentionally instance-scoped rather than global;
  `mastodon.social` is always searched first and extra instances can be added
  when the user names communities to include.
- Bluesky topic search may require an authenticated session in some environments;
  configure the Vault/env credentials above when unauthenticated search returns
  `403`.

Social post titles, bodies, and replies pass through the external-content sanitizer before embed data is stored or sent to the model.
