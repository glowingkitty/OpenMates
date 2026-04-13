"""
Gmail OAuth2 Refresh Token Generator

One-time script to generate a refresh token for the Gmail API.
Used by E2E tests to read verification emails from a dedicated test inbox.

Usage:
    python3 scripts/generate-gmail-token.py --client-id YOUR_ID --client-secret YOUR_SECRET

Opens a browser for Google consent, then prints the refresh token to copy
into your GitHub Actions secrets (GMAIL_REFRESH_TOKEN).
"""

import argparse
import http.server
import sys
import urllib.parse
import urllib.request
import json
import webbrowser
from functools import partial

REDIRECT_PORT = 3847
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange the authorization code for access + refresh tokens."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that catches the OAuth redirect and exchanges the code."""

    def __init__(self, client_id: str, client_secret: str, *args, **kwargs):
        self.client_id = client_id
        self.client_secret = client_secret
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        error = params.get("error", [None])[0]
        if error:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Authorization failed</h1><p>{error}</p>".encode())
            print(f"\nAuthorization failed: {error}")
            sys.exit(1)

        code = params.get("code", [None])[0]
        if not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>No authorization code received</h1>")
            return

        try:
            tokens = exchange_code_for_tokens(code, self.client_id, self.client_secret)

            if "error" in tokens:
                raise RuntimeError(f"{tokens['error']}: {tokens.get('error_description', '')}")

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h1>Success!</h1><p>You can close this tab. Check the terminal for your refresh token.</p>"
            )

            print("\n=== SUCCESS ===\n")
            print("Add these as GitHub Actions secrets:\n")
            print(f"  GMAIL_CLIENT_ID:      {self.client_id}")
            print(f"  GMAIL_CLIENT_SECRET:   {self.client_secret}")
            print(f"  GMAIL_REFRESH_TOKEN:   {tokens['refresh_token']}")
            print("\nDone! You can close this terminal.\n")

        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Token exchange failed</h1><p>{exc}</p>".encode())
            print(f"Token exchange failed: {exc}")

        # Shut down the server after handling the callback
        raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Generate Gmail OAuth2 refresh token for E2E tests")
    parser.add_argument("--client-id", required=True, help="OAuth Client ID from GCP")
    parser.add_argument("--client-secret", required=True, help="OAuth Client Secret from GCP")
    args = parser.parse_args()

    # Build the consent URL
    auth_params = urllib.parse.urlencode({
        "client_id": args.client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{auth_params}"

    print("\n=== Gmail OAuth2 Token Generator ===\n")
    print("Open this URL in your browser:\n")
    print(auth_url)
    print("\nWaiting for authorization...\n")

    # Try to open the browser automatically
    webbrowser.open(auth_url)

    # Start local server to catch the redirect
    handler = partial(OAuthCallbackHandler, args.client_id, args.client_secret)
    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
