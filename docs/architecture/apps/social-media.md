# Social Media App

The Social Media app exposes normalized post/comment retrieval and topic search
across social platforms. `get-posts` is for known profiles/pages. `search` is for
topic discovery across supported platforms.

## Current Providers

- `reddit_rss` fetches subreddit Atom feeds and optional post comment feeds.
- It is read-only and does not post, vote, message users, or automate account
  actions.
- It returns normalized posts and comments for manual review workflows.
- Callers should fetch comments only for relevant posts and respect Reddit's
  `x-ratelimit-*` headers.
- `bluesky_public` fetches profile feeds and post search results through the
  official Bluesky AppView APIs.
- Bluesky profile feeds use `app.bsky.feed.getAuthorFeed` and require no API key.
- Bluesky topic search uses `app.bsky.feed.searchPosts`. It first tries the
  public AppView and can use authenticated PDS requests when credentials are
  configured.
- Store Bluesky credentials via the normal `SECRET__*` migration convention:
  `SECRET__BLUESKY__IDENTIFIER` and `SECRET__BLUESKY__APP_PASSWORD` migrate to
  `kv/data/providers/bluesky` as `identifier` and `app_password`.

## Request Modes

- `get-posts` is for one or multiple specific pages/profiles. Callers pass
  `platform` and `page` for each requested source.
- `search` is for finding recent public posts around a topic. Callers pass
  `platform` and `query`, with optional provider filters such as Bluesky
  `author`.
- Bluesky topic search may require an authenticated session in some environments;
  configure the Vault/env credentials above when unauthenticated search returns
  `403`.

## Future Provider

When official Reddit Data API access is approved, add a `reddit_api` provider
behind the same `social_media:get-posts` skill response shape. Keep RSS as a
fallback for low-volume discovery.
