"""Opt-in one-credit provider diagnostic; not a substitute for skill E2E."""
import asyncio
from datetime import date, timedelta
import json
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

async def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Run only in the isolated GitHub coordinator')
    key = os.environ.pop('CODEX_3D8A_SERPAPI_ONCE', '')
    if not key:
        raise RuntimeError('One-use provider credential missing; no request made')
    # Consume the authorization before importing or calling provider code.
    marker = Path(os.environ['RUNNER_TEMP']) / 'openmates-serpapi-once-consumed'
    with marker.open('x'):
        pass
    os.environ['SECRET__SERPAPI__API_KEY'] = key
    logging.disable(logging.CRITICAL)
    from backend.apps.travel.providers.serpapi_provider import SerpApiProvider
    provider = SerpApiProvider()
    original = provider._serpapi_get
    calls = 0
    async def bounded_get(params):
        nonlocal calls
        if calls or params.get('engine') != 'google_flights':
            raise RuntimeError('One-search authorization exhausted')
        calls += 1
        return await original(params)
    provider._serpapi_get = bounded_get
    result = {'scope': 'live Google Flights provider + normalized connection parser', 'max_search_requests': 1, 'max_authorized_eur': 0.10}
    try:
        connections = await provider.search_connections(
            legs=[{'origin': 'BER', 'destination': 'MAD', 'date': (date.today() + timedelta(days=30)).isoformat()}],
            passengers=1, travel_class='economy', max_results=3, non_stop_only=False, currency='EUR',
        )
        result.update(search_requests=calls, connection_count=len(connections), status='success' if connections else 'empty')
        if not connections:
            raise RuntimeError('Provider returned no connections')
    except Exception as error:
        result.update(search_requests=calls, status='failed', error_type=type(error).__name__)
        raise RuntimeError('Capped provider diagnostic failed; see redacted receipt') from None
    finally:
        os.environ.pop('SECRET__SERPAPI__API_KEY', None)
        Path('test-results/ci-travel-provider-once.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))

if __name__ == '__main__':
    asyncio.run(main())
