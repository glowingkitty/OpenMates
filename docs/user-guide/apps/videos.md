---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-videos-source
    type: unit
    claim: The Videos app guide is grounded in the Videos app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-videos-source
---

# Videos

> Search for videos and retrieve supported captions for summarising and analysis.

## What It Does

The Videos app helps you find videos on any topic and retrieve captions from supported video sources so your mate can work with it.

**Available skills:**

- **Generate** -- Creates short AI videos. Ordinary generation uses Google Veo. Authenticated chats and calls can use H3 Max Turbo for five-second 480p clips with one saved image as the first frame. H3 results are encrypted and saved alongside other generated videos; REST generation currently supports Veo only.
- **Search** -- Searches the web for videos, documentaries, tutorials, and clips on any topic. Results show video thumbnails, titles, and durations.
- **Get Transcript** -- Retrieves available captions from media.ccc.de recordings. YouTube links support metadata and search; captions are unavailable.

**Focus mode:**

- **Analyse Video** -- When supported captions are available, this mode provides a detailed summary, bias analysis, and fact-checks the key claims using web searches. It rates the overall reliability of the information and identifies what context might be missing.

## How to Use It

- Search for videos: "Find tutorials about watercolour painting"
- Get a transcript: "Get available captions for this media.ccc.de recording: [link]"
- Summarise a video: "Summarise this video for me: [link]"
- Fact-check a video: Share a link and ask "Analyse this video for bias and accuracy"

## Memories

- **To Watch List** -- Save videos you want to watch later, with the video name, link, and channel.

## Tips

- Video search results appear as preview cards with thumbnails. Click to watch in your browser.
- Transcripts are useful for getting key points from long videos without watching the whole thing.
- The analyse mode fact-checks claims by running web searches, so you get an independent assessment of the video's accuracy.
- If captions are not available for a video, your mate will let you know.

## Related

- [Web](./web.md) -- General web search
- [News](./news.md) -- Search for news articles instead of videos
- [Images](./images.md) -- Search for images
