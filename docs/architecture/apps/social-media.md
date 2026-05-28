# Social Media App

The Social Media app exposes normalized post/comment retrieval and topic search
across social platforms. `get-posts` is for known profiles/pages. `search` is for
topic discovery across supported platforms.

## Current Providers

- `reddit_json` fetches subreddit JSON listings, search results, and optional
  post comments through provider-managed Webshare residential proxies.
- `reddit_rss` remains as a low-volume fallback when JSON access fails.
- It is read-only and does not post, vote, message users, or automate account
  actions.
- It returns normalized posts and comments for manual review workflows.
- Callers should fetch comments only for relevant posts and respect Reddit's
  `x-ratelimit-*` headers.
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

## Reddit Sorting and Filters

- `get-posts` supports Reddit listing sorts: `new`, `hot`, `rising`, `top`, and
  `comments`. `comments` uses subreddit-restricted JSON search with
  `sort=comments` and defaults to `time_range=week` when no time range is set.
- `search` supports Reddit search sorts: `relevance`, `hot`, `top`, `new`,
  `comments`, and `latest` (`latest` maps to Reddit `new`).
- Reddit time filters are enum-backed: `hour`, `day`, `week`, `month`, `year`,
  and `all`.
- Reddit comment sorts are enum-backed: `confidence`, `top`, `new`,
  `controversial`, and `old`. The default is `top`, and returned comments are
  locally ordered by public upvotes/score before being capped.
- Client-side filters include `min_score`, `min_comments`, `exclude_stickied`,
  `exclude_nsfw`, `include_self_posts`, and `include_link_posts`.
- Reddit comments are capped to at most 5 per post embed.
- Social post titles, post bodies, and comment bodies are treated as hostile
  external content and pass through the same prompt-injection sanitizer used for
  video transcripts before embed data is stored or sent to the model.
