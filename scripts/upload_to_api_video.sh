#!/bin/bash
# upload_to_api_video.sh
#
# Uploads a local video file to api.video and prints the HLS + MP4 URLs.
#
# Usage:
#   ./upload_to_api_video.sh <path-to-video> <api-key> [title]
#
# Example:
#   ./upload_to_api_video.sh ~/Desktop/demo.mp4 your_api_key_here "OpenMates Demo"
#
# Requirements: curl, jq  (install jq with: brew install jq)

set -e

# ─── Args ──────────────────────────────────────────────────────────────────────

VIDEO_PATH="$1"
API_KEY="$2"
TITLE="${3:-Product Demo}"

if [[ -z "$VIDEO_PATH" || -z "$API_KEY" ]]; then
  echo "Usage: $0 <path-to-video> <api-key> [title]"
  echo "Example: $0 ~/Desktop/demo.mp4 your_api_key_here \"OpenMates Demo\""
  exit 1
fi

if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "Error: file not found: $VIDEO_PATH"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required. Install it with: brew install jq"
  exit 1
fi

# ─── Step 1: Create video object ───────────────────────────────────────────────

echo ""
echo "Step 1/2 — Creating video object..."

CREATE_RESPONSE=$(curl -s -X POST "https://ws.api.video/videos" \
  -u "${API_KEY}:" \
  -H "Content-Type: application/json" \
  -d "{\"title\": \"${TITLE}\", \"mp4Support\": true, \"public\": true}")

VIDEO_ID=$(echo "$CREATE_RESPONSE" | jq -r '.videoId')

if [[ -z "$VIDEO_ID" || "$VIDEO_ID" == "null" ]]; then
  echo "Error: failed to create video object. Response:"
  echo "$CREATE_RESPONSE" | jq .
  exit 1
fi

echo "  Video ID: $VIDEO_ID"

# ─── Step 2: Upload file ───────────────────────────────────────────────────────

echo ""
echo "Step 2/2 — Uploading file (this may take a while)..."
echo "  File: $VIDEO_PATH"
echo "  Size: $(du -sh "$VIDEO_PATH" | cut -f1)"

UPLOAD_RESPONSE=$(curl -s -X POST "https://ws.api.video/videos/${VIDEO_ID}/source" \
  -u "${API_KEY}:" \
  -F "file=@${VIDEO_PATH}")

HLS_URL=$(echo "$UPLOAD_RESPONSE" | jq -r '.assets.hls')
MP4_URL=$(echo "$UPLOAD_RESPONSE" | jq -r '.assets.mp4')
THUMBNAIL_URL=$(echo "$UPLOAD_RESPONSE" | jq -r '.assets.thumbnail')

if [[ -z "$HLS_URL" || "$HLS_URL" == "null" ]]; then
  echo "Error: upload failed or URLs not ready yet. Response:"
  echo "$UPLOAD_RESPONSE" | jq .
  exit 1
fi

# ─── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════"
echo "  Upload complete!"
echo ""
echo "  Video ID  : $VIDEO_ID"
echo "  HLS URL   : $HLS_URL"
echo "  MP4 URL   : $MP4_URL"
echo "  Thumbnail : $THUMBNAIL_URL"
echo "════════════════════════════════════════════════════"
echo ""
echo "Copy the HLS and MP4 URLs — you'll need them for the frontend."
