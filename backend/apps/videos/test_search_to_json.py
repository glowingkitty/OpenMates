#!/usr/bin/env python3
"""
Manual debug script for video search.

OPE-342: previously HTTP-curled into the app-videos container. That container
no longer exists. The script is left in place for reference but disabled until
it is rewritten to dispatch via the in-process SkillRegistry, e.g.:

    docker exec api python -c "
    import asyncio
    from backend.core.api.app.services.skill_registry import get_global_registry
    print(asyncio.run(get_global_registry().dispatch_skill(
        'videos', 'search', {'requests': [{'query': 'cats'}]}
    )))
    "
"""

import sys

print("DISABLED (OPE-342): rewrite to use the in-process SkillRegistry — see module docstring.")
sys.exit(1)

import json  # noqa: E402  (unreachable, kept for reference)
import urllib.request  # noqa: E402

# Configuration
API_URL = "http://app-videos:8000/skills/search"  # legacy, no longer reachable


def search_video(query: str) -> dict:
    """
    Search for videos and display the video data.
    
    Args:
        query: Search query string
        
    Returns:
        Dict containing the API response
    """
    # Prepare request payload
    payload = {
        "requests": [
            {
                "id": 1,
                "query": query,
                "count": 10  # Return top 10 most viewed videos
            }
        ]
    }
    
    # Convert payload to JSON
    data = json.dumps(payload).encode('utf-8')
    
    print(f"🔍 Searching for videos: '{query}'")
    print(f"   Endpoint: {API_URL}")
    print()
    
    # Create request
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        print("📡 Sending request...")
        with urllib.request.urlopen(req, timeout=60.0) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            print(f"✅ Response received (Status: {response.status})")
            print()
            
            # Display video data
            if result.get("results"):
                for result_group in result.get("results", []):
                    videos = result_group.get("results", [])
                    if videos:
                        print("=" * 80)
                        print(f"📹 TOP {len(videos)} VIDEOS (sorted by view count)")
                        print("=" * 80)
                        print()
                        
                        for idx, video in enumerate(videos, 1):
                            print(f"--- Video #{idx} ---")
                            print(f"Title: {video.get('title', 'N/A')}")
                            print(f"URL: {video.get('url', 'N/A')}")
                            print(f"Description: {video.get('description', 'N/A')[:150]}...")
                            print()
                            print("📊 Statistics:")
                            print(f"   Views: {video.get('viewCount', 0):,}")
                            print(f"   Likes: {video.get('likeCount', 0):,}")
                            print(f"   Comments: {video.get('commentCount', 0):,}")
                            print()
                            print("👤 Channel:")
                            print(f"   Name: {video.get('channelTitle', 'N/A')}")
                            print(f"   Published: {video.get('publishedAt', 'N/A')}")
                            print(f"   Duration: {video.get('duration', 'N/A')}")
                            print()
                            print("🖼️  Images:")
                            thumbnail = video.get('thumbnail', {})
                            thumbnail_url = thumbnail.get('original') if isinstance(thumbnail, dict) else None
                            if thumbnail_url:
                                print(f"   Thumbnail: {thumbnail_url}")
                            else:
                                print("   Thumbnail: N/A")
                            
                            profile_image = video.get('meta_url', {}).get('profile_image') if isinstance(video.get('meta_url'), dict) else None
                            if profile_image:
                                print(f"   Profile Image: {profile_image}")
                            else:
                                print("   Profile Image: N/A")
                            print()
                            print("🏷️  Tags:")
                            tags = video.get('tags', [])
                            if tags:
                                print(f"   {', '.join(tags[:8])}{'...' if len(tags) > 8 else ''} ({len(tags)} total)")
                            else:
                                print("   No tags")
                            print()
                            if idx < len(videos):
                                print("-" * 80)
                                print()
                    else:
                        print("⚠️  No videos found in results")
            else:
                print("⚠️  No results returned")
            
            if result.get("error"):
                print(f"⚠️  Error in response: {result.get('error')}")
            
            return result
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ HTTP Error {e.code}: {error_body}", file=sys.stderr)
        try:
            error_json = json.loads(error_body)
            print(f"Error details: {json.dumps(error_json, indent=2)}", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_search_to_json.py <query>", file=sys.stderr)
        print("Example: python test_search_to_json.py 'Meiji Restoration Japan'", file=sys.stderr)
        sys.exit(1)
    
    query = sys.argv[1]
    result = search_video(query)
    
    sys.exit(0)
