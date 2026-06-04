"""
Test script to query and verify ADS-B flight tracking data.

Supports both:
1. Official ADS-B Exchange API (via RapidAPI, requires key).
2. adsb.lol (Free public community ADS-B API, no key required).

Usage:
    python3 test_adsb_exchange.py [--api-key YOUR_RAPID_API_KEY]
"""

import argparse
import asyncio
import httpx
import sys
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Constants & Endpoints
# ---------------------------------------------------------------------------

# Coordinates for testing (Center of Germany - Frankfurt area)
TEST_LAT = 50.1109
TEST_LON = 8.6821
TEST_RADIUS_NM = 100

ADSB_LOL_BASE = "https://api.adsb.lol"
RAPID_API_HOST = "adsbexchange-com1.p.rapidapi.com"
RAPID_API_BASE = f"https://{RAPID_API_HOST}"


# ---------------------------------------------------------------------------
# API Query Functions
# ---------------------------------------------------------------------------

async def fetch_adsb_data(
    url: str,
    headers: Dict[str, str],
    params: Dict[str, Any],
    provider_name: str,
) -> Dict[str, Any]:
    """Fetch raw ADS-B data from the given endpoint."""
    print(f"\n[+] Querying {provider_name} API...")
    print(f"    URL: {url}")
    if params:
        print(f"    Params: {params}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 403:
                print("    [!] Auth Error (403): Your API key may be invalid or unauthorized.")
                return {}
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"    [!] Error fetching from {provider_name}: {e}")
            return {}


def print_aircraft_summary(aircraft_list: List[Dict[str, Any]]) -> None:
    """Print a clean summary table of found aircraft."""
    if not aircraft_list:
        print("    No aircraft found matching the criteria.")
        return

    print(f"    Found {len(aircraft_list)} aircraft:")
    print("-" * 110)
    print(f"{'Hex':<8} | {'Callsign':<8} | {'Reg':<8} | {'Type':<6} | {'Alt (ft)':<8} | {'Speed (kt)':<10} | {'Lat':<9} | {'Lon':<9} | {'Flags'}")
    print("-" * 110)

    for ac in aircraft_list[:15]:  # Limit output to 15 rows for readability
        hex_code = ac.get("hex", "N/A")
        callsign = (ac.get("flight") or "").strip() or "N/A"
        reg = ac.get("r", "N/A")
        type_code = ac.get("t", "N/A")
        alt = ac.get("alt_baro", "N/A")
        speed = ac.get("gs", "N/A")
        lat = ac.get("lat", "N/A")
        lon = ac.get("lon", "N/A")

        # Parse flags
        db_flags = ac.get("dbFlags", 0)
        flags = []
        if db_flags & 1:
            flags.append("MIL")
        if db_flags & 2:
            flags.append("INT")
        if db_flags & 4:
            flags.append("PIA")
        if db_flags & 8:
            flags.append("LADD")
        
        flags_str = ",".join(flags) if flags else "-"

        print(f"{hex_code:<8} | {callsign:<8} | {reg:<8} | {type_code:<6} | {str(alt):<8} | {str(speed):<10} | {str(lat)[:9]:<9} | {str(lon)[:9]:<9} | {flags_str}")

    if len(aircraft_list) > 15:
        print(f"... and {len(aircraft_list) - 15} more aircraft.")
    print("-" * 110)


# ---------------------------------------------------------------------------
# Main Execution Flow
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="ADS-B Exchange & adsb.lol API Tester")
    parser.add_argument(
        "--api-key",
        type=str,
        help="RapidAPI Key for ADS-B Exchange. If omitted, the script falls back to adsb.lol (free).",
    )
    args = parser.parse_args()

    # Determine provider and endpoint details
    if args.api_key:
        provider = "ADS-B Exchange (RapidAPI)"
        base_url = RAPID_API_BASE
        headers = {
            "X-RapidAPI-Key": args.api_key,
            "X-RapidAPI-Host": RAPID_API_HOST,
        }
        # ADS-B Exchange standard path for radius searches
        url_radius = f"{base_url}/v2/lat/{TEST_LAT}/lon/{TEST_LON}/dist/{TEST_RADIUS_NM}"
        url_mil = f"{base_url}/v2/mil"
        params = {}
    else:
        provider = "adsb.lol (Free Community API)"
        base_url = ADSB_LOL_BASE
        headers = {}
        # adsb.lol scheme uses queries for distance/lat/lon or path parameters
        url_radius = f"{base_url}/v2/lat/{TEST_LAT}/lon/{TEST_LON}/dist/{TEST_RADIUS_NM}"
        url_mil = f"{base_url}/v2/mil"
        params = {}

    print("=== ADS-B FLIGHT DATA INTEGRATION TEST ===")
    print(f"Using Provider: {provider}")

    # 1. Test Radius Query (Around Frankfurt / German Airspace)
    print(f"\n[1] Testing Radius Search (Center: {TEST_LAT}, {TEST_LON} | Radius: {TEST_RADIUS_NM} NM)")
    data = await fetch_adsb_data(url_radius, headers, params, provider)
    
    if data:
        aircraft = data.get("aircraft") or data.get("ac") or []
        print_aircraft_summary(aircraft)
        
        # Look for private jets specifically in the radius
        private_jets = [
            ac for ac in aircraft
            if (ac.get("dbFlags", 0) & 8) or (ac.get("dbFlags", 0) & 4)
        ]
        print(f"    [➔] Private Jets (LADD/PIA) detected in area: {len(private_jets)}")
        for pj in private_jets[:5]:
            print(f"        - Jet Hex: {pj.get('hex')} | Reg: {pj.get('r')} | Type: {pj.get('t')} | Alt: {pj.get('alt_baro')} ft")
    else:
        print("    [!] Radius query returned no data.")

    # 2. Test Military Query (Global active military transponders)
    print("\n[2] Testing Active Military Aircraft Query (Global/Active)")
    mil_data = await fetch_adsb_data(url_mil, headers, params, provider)
    
    if mil_data:
        mil_aircraft = mil_data.get("aircraft") or mil_data.get("ac") or []
        print_aircraft_summary(mil_aircraft)
    else:
        print("    [!] Military query returned no data.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
