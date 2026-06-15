/**
 * App-store examples for social_media/search.
 *
 * Uses synthetic but provider-shaped social post data so the Apps does not
 * promote specific real accounts while still exercising realistic render paths.
 */

export interface SocialMediaSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  result_count: number;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: SocialMediaSearchStoreExample[] = [
  {
    "id": "store-example-social-media-search-1",
    "query": "Indie coffee setup inspiration",
    "query_translation_key": "settings.app_store_examples.social_media.search.1",
    "provider": "bluesky_public",
    "result_count": 3,
    "status": "finished",
    "results": [{
      "platform": "bluesky",
      "page": "search",
      "posts": [
        {
          "title": "Small cafe bar layout notes",
          "body": "A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.",
          "author": "sample.cafe",
          "author_display_name": "Sample Cafe Journal",
          "published_at": "2026-05-24T10:30:00Z",
          "like_count": 184,
          "reply_count": 12,
          "repost_count": 27,
          "url": "https://bsky.app/profile/sample.cafe/post/example-1"
        },
        {
          "title": "Home pourover station",
          "body": "Keeping grinder, scale, filters and kettle on one tray reduced morning friction more than any equipment upgrade.",
          "author": "dailybrew.example",
          "author_display_name": "Daily Brew Notes",
          "published_at": "2026-05-23T18:12:00Z",
          "like_count": 96,
          "reply_count": 8,
          "repost_count": 11,
          "url": "https://bsky.app/profile/dailybrew.example/post/example-2"
        },
        {
          "title": "Menu photography tip",
          "body": "Shoot drinks next to the ingredients that define them. Even one citrus peel or spice jar gives people a faster read on flavor.",
          "author": "menu-lab.example",
          "author_display_name": "Menu Lab",
          "published_at": "2026-05-22T14:04:00Z",
          "like_count": 73,
          "reply_count": 5,
          "repost_count": 9,
          "url": "https://bsky.app/profile/menu-lab.example/post/example-3"
        }
      ]
    }]
  },
  {
    "id": "store-example-social-media-search-2",
    "query": "Remote workshop facilitation tips",
    "query_translation_key": "settings.app_store_examples.social_media.search.2",
    "provider": "reddit_json",
    "result_count": 2,
    "status": "finished",
    "results": [{
      "platform": "reddit",
      "page": "r/sampleteams",
      "posts": [
        {
          "title": "What changed our remote retrospectives",
          "body": "We switched from one big discussion to silent notes, dot voting, then two focused action owners. The meeting got shorter and follow-through improved.",
          "author": "sample_facilitator",
          "published_at": "2026-05-21T09:45:00Z",
          "like_count": 421,
          "reply_count": 68,
          "url": "https://www.reddit.com/r/sampleteams/comments/example1"
        },
        {
          "title": "Async prep before strategy sessions",
          "body": "Sending a one-page decision memo two days before the workshop helped quieter people arrive with sharper opinions.",
          "author": "workshop_notes",
          "published_at": "2026-05-20T16:20:00Z",
          "like_count": 137,
          "reply_count": 24,
          "url": "https://www.reddit.com/r/sampleteams/comments/example2"
        }
      ]
    }]
  }
];

export default examples;
