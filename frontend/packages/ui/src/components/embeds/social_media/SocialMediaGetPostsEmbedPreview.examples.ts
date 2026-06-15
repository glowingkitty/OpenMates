/**
 * App-store examples for social_media/get-posts.
 *
 * Uses synthetic but provider-shaped post data so the Apps avoids
 * promoting specific real accounts while still rendering realistic cards.
 */

export interface SocialMediaGetPostsStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  result_count: number;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: SocialMediaGetPostsStoreExample[] = [
  {
    "id": "store-example-social-media-get-posts-1",
    "query": "@samplegarden.example",
    "query_translation_key": "settings.app_store_examples.social_media.get_posts.1",
    "provider": "bluesky_public",
    "result_count": 3,
    "status": "finished",
    "results": [{
      "platform": "bluesky",
      "page": "@samplegarden.example",
      "posts": [
        {
          "title": "Balcony herbs after rain",
          "body": "Mint and basil bounced back fastest after moving the planters closer to the wall. The wind break mattered more than the fertilizer schedule.",
          "author": "samplegarden.example",
          "author_display_name": "Sample Garden Log",
          "published_at": "2026-05-24T08:05:00Z",
          "like_count": 129,
          "reply_count": 14,
          "repost_count": 18,
          "url": "https://bsky.app/profile/samplegarden.example/post/example-1"
        },
        {
          "title": "Compost reminder",
          "body": "The easiest rule I have found: if the bin smells sharp, add dry browns; if nothing changes for a week, add greens and turn once.",
          "author": "samplegarden.example",
          "author_display_name": "Sample Garden Log",
          "published_at": "2026-05-22T11:36:00Z",
          "like_count": 88,
          "reply_count": 7,
          "repost_count": 10,
          "url": "https://bsky.app/profile/samplegarden.example/post/example-2"
        },
        {
          "title": "Seedling notes",
          "body": "Labeling trays with both variety and sowing date made thinning decisions much easier two weeks later.",
          "author": "samplegarden.example",
          "author_display_name": "Sample Garden Log",
          "published_at": "2026-05-19T15:10:00Z",
          "like_count": 64,
          "reply_count": 3,
          "repost_count": 6,
          "url": "https://bsky.app/profile/samplegarden.example/post/example-3"
        }
      ]
    }]
  },
  {
    "id": "store-example-social-media-get-posts-2",
    "query": "r/sampletravel",
    "query_translation_key": "settings.app_store_examples.social_media.get_posts.2",
    "provider": "reddit_json",
    "result_count": 2,
    "status": "finished",
    "results": [{
      "platform": "reddit",
      "page": "r/sampletravel",
      "posts": [
        {
          "title": "Packing list after three rail trips",
          "body": "The winning setup was one backpack, one small sling, a paper copy of reservations, and a reusable fork. Everything else was negotiable.",
          "author": "sample_rail_planner",
          "published_at": "2026-05-18T13:12:00Z",
          "like_count": 302,
          "reply_count": 51,
          "url": "https://www.reddit.com/r/sampletravel/comments/example1"
        },
        {
          "title": "Quiet museum mornings",
          "body": "Booking the first entry slot and planning lunch nearby turned out to be the simplest way to avoid the midday crowd spike.",
          "author": "slow_trip_notes",
          "published_at": "2026-05-15T07:55:00Z",
          "like_count": 176,
          "reply_count": 19,
          "url": "https://www.reddit.com/r/sampletravel/comments/example2"
        }
      ]
    }]
  }
];

export default examples;
