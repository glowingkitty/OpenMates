#!/usr/bin/env python3
"""
Simple script to fetch and display Open Graph (OG) meta tags from a URL.
Useful for testing social media preview metadata.

Usage:
    python3 scripts/check_og_tags.py
    # Or make it executable:
    chmod +x scripts/check_og_tags.py
    ./scripts/check_og_tags.py
"""

import sys
import re
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser


class OGTagParser(HTMLParser):
    """HTML parser that extracts Open Graph meta tags."""

    def __init__(self):
        super().__init__()
        self.og_tags = {}
        self.twitter_tags = {}
        self.title = None
        self.description = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Extract OG tags
        if tag == 'meta':
            property_val = attrs_dict.get('property', '')
            content_val = attrs_dict.get('content', '')

            if property_val.startswith('og:'):
                self.og_tags[property_val] = content_val
            elif property_val.startswith('twitter:'):
                self.twitter_tags[property_val] = content_val

            # Also check for name attribute (Twitter uses this too)
            name_val = attrs_dict.get('name', '')
            if name_val.startswith('twitter:'):
                self.twitter_tags[name_val] = content_val
            elif name_val == 'description':
                self.description = content_val

        # Extract title tag
        elif tag == 'title':
            self.in_title = True

    def handle_data(self, data):
        if hasattr(self, 'in_title') and self.in_title:
            self.title = data.strip()

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False


def fetch_og_tags(url):
    """
    Fetch and parse OG tags from a URL.

    Args:
        url: The URL to fetch OG tags from

    Returns:
        Tuple of (og_tags, twitter_tags, title, description)
    """
    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # Create request with user agent to avoid being blocked
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; OG Tag Checker/1.0)'
    }
    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')

        # Parse HTML
        parser = OGTagParser()
        parser.feed(html)

        return parser.og_tags, parser.twitter_tags, parser.title, parser.description

    except HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        return None, None, None, None
    except URLError as e:
        print(f"❌ URL Error: {e.reason}", file=sys.stderr)
        return None, None, None, None
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return None, None, None, None


def print_tags(og_tags, twitter_tags, title, description):
    """Pretty print the extracted tags."""

    print("\n" + "="*70)
    print("📄 HTML Meta Tags")
    print("="*70)

    if title:
        print(f"\n🏷️  Title: {title}")

    if description:
        print(f"📝 Description: {description}")

    print("\n" + "-"*70)
    print("📱 Open Graph Tags")
    print("-"*70)

    if og_tags:
        for prop, content in sorted(og_tags.items()):
            prop_name = prop.replace('og:', '')
            print(f"{prop_name:20} : {content}")
    else:
        print("❌ No Open Graph tags found")

    print("\n" + "-"*70)
    print("🐦 Twitter Card Tags")
    print("-"*70)

    if twitter_tags:
        for name, content in sorted(twitter_tags.items()):
            name_clean = name.replace('twitter:', '')
            print(f"{name_clean:20} : {content}")
    else:
        print("❌ No Twitter Card tags found")

    print("\n" + "="*70 + "\n")


def main():
    """Main function."""
    print("\n🔍 Open Graph Tag Checker")
    print("="*70)

    # Get URL from user
    url = input("\nEnter URL to check: ").strip()

    if not url:
        print("❌ No URL provided", file=sys.stderr)
        sys.exit(1)

    print(f"\n🌐 Fetching: {url}")
    print("⏳ Please wait...")

    # Fetch and parse
    og_tags, twitter_tags, title, description = fetch_og_tags(url)

    if og_tags is None:
        sys.exit(1)

    # Display results
    print_tags(og_tags, twitter_tags, title, description)


if __name__ == '__main__':
    main()
