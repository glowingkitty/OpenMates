#!/usr/bin/env python3
"""
Test script for app skills.
Usage: python test_skills.py <app_name> <skill_id> [json_payload]

Examples:
  python test_skills.py web read '{"requests": [{"url": "https://example.com"}]}'
  python test_skills.py videos search '{"requests": [{"query": "python tutorial"}]}'
  python test_skills.py news search '{"requests": [{"query": "latest AI news"}]}'
"""

import sys
import json
import urllib.request
import urllib.parse

def test_skill(app_name: str, skill_id: str, payload: dict):
    """Test a skill endpoint."""
    url = f"http://localhost:8000/skills/{skill_id}"
    
    # Convert payload to JSON
    data = json.dumps(payload).encode('utf-8')
    
    # Create request
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(json.dumps(result, indent=2))
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"HTTP Error {e.code}: {error_body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    
    app_name = sys.argv[1]
    skill_id = sys.argv[2]
    
    if len(sys.argv) > 3:
        payload = json.loads(sys.argv[3])
    else:
        # Default payloads for each skill
        if skill_id == "read":
            payload = {"requests": [{"url": "https://docs.firecrawl.dev/api-reference/endpoint/scrape"}]}
        elif skill_id == "search":
            if app_name == "videos":
                payload = {"requests": [{"query": "python tutorial"}]}
            elif app_name == "news":
                payload = {"requests": [{"query": "latest AI news"}]}
            else:
                payload = {"requests": [{"query": "open source AI"}]}
        else:
            print(f"Unknown skill: {skill_id}", file=sys.stderr)
            sys.exit(1)
    
    test_skill(app_name, skill_id, payload)

