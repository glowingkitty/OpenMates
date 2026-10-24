"""Provider evidence helpers: no inferred amenities or exact coordinates.

Only source responses are cached; image URLs are retained without downloading
photos. The finite response cache is process-local and expires after five minutes.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from html import unescape
from html.parser import HTMLParser
import json
import logging
import math
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)
MAX_CANDIDATES = 40
DETAIL_CONCURRENCY = 4
DETAIL_DEADLINE_SECONDS = 12
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 128
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
AMENITIES = ('balcony', 'furnished', 'elevator', 'garden', 'terrace', 'parking', 'pets_allowed')


def number(value: Any) -> float | None:
    """Read provider numbers, including German formatted labelled amounts."""
    if isinstance(value, dict):
        value = value.get('value')
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    match = re.search(r'-?\d[\d.\s]*(?:,\d+)?', str(value))
    if not match:
        return None
    token = match.group().replace(' ', '').strip()
    if ',' in token:
        token = token.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', token):
        token = token.replace('.', '')
    try:
        result = float(token)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def flag(value: Any) -> bool | None:
    """Unknown and provider no-information enums remain distinct from false."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in {'1', 'true', 'yes', 'ja', 'y', 'vorhanden', 'allowed'}:
        return True
    if value in {'0', 'false', 'no', 'nein', 'n', 'nicht vorhanden', 'not_allowed'}:
        return False
    return None


def amenity(listing: dict[str, Any], key: str, value: Any) -> None:
    """Keep conflicting advertised flags distinct instead of choosing a winner."""
    supplied = flag(value)
    previous = listing['amenities'].get(key)
    conflicts = listing.get('amenity_conflicts', {})
    if key in conflicts:
        return
    if supplied is not None and previous is not None and supplied != previous:
        listing.setdefault('amenity_conflicts', {})[key] = [previous, supplied]
        listing['amenities'][key] = None
    elif supplied is not None:
        listing['amenities'][key] = supplied


def text(value: Any) -> str:
    """Strip markup from advertised text, preserving readable boundaries."""
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def photo_url(value: Any) -> str | None:
    """Accept supplied HTTP photo URLs, never fabricate URL variants."""
    if not isinstance(value, str):
        return None
    value = unescape(value).strip()
    parsed = urlsplit(value)
    return value if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and '%' not in parsed.netloc else None


def photos(value: Any) -> list[str]:
    """Read known photo containers; pick one supplied rendition per photo."""
    if isinstance(value, str):
        return [value] if photo_url(value) else []
    if isinstance(value, list):
        return list(dict.fromkeys(url for item in value for url in photos(item)))
    if not isinstance(value, dict):
        return []
    if 'video' in str(value.get('type', value.get('@xsi.type', ''))).lower():
        return []
    for key in ('full', 'large', 'original', 'contentUrl', 'image_url', 'src', 'url', '@href', 'href', 'preview'):
        candidate = value.get(key)
        if isinstance(candidate, str) and photo_url(candidate):
            return [unescape(candidate)]
    if 'urls' in value:
        variants = value['urls']
        if isinstance(variants, dict):
            variants = variants.get('url', [])
        variants = variants if isinstance(variants, list) else [variants]
        supplied = [url for variant in variants for url in photos(variant) if '%WIDTH%' not in url and '%HEIGHT%' not in url]
        return list(dict.fromkeys(supplied))
    return [url for key in ('image', 'images', 'pictures', 'picture', 'attachment', 'attachments', 'gallery') for url in photos(value.get(key))]


def defaults(listing: dict[str, Any]) -> dict[str, Any]:
    """Add a consistent explicit-unknown evidence schema without losing fields."""
    for key in ('description', 'cold_rent_eur', 'warm_rent_eur', 'utilities_eur', 'heating_costs_eur', 'deposit', 'floor', 'available_from', 'available_to', 'street', 'house_number', 'postcode', 'city', 'district', 'latitude', 'longitude', 'location_source'):
        listing.setdefault(key, None)
    listing.setdefault('price_type', 'purchase' if listing.get('listing_type') == 'buy' else 'advertised' if listing.get('price') is not None else 'unknown')
    listing.setdefault('location_precision', 'unknown')
    listing.setdefault('location_approximate', None)
    listing.setdefault('gallery_status', 'partial' if listing.get('image_url') else 'unavailable')
    listing['amenities'] = {key: listing.get('amenities', {}).get(key, listing.get(key)) for key in AMENITIES}
    for key, value in listing['amenities'].items():
        listing[key] = value
    listing['image_urls'] = list(dict.fromkeys(filter(None, [listing.get('image_url'), *listing.get('image_urls', [])])))
    return listing


def merge_gallery(listing: dict[str, Any], urls: list[str], complete: bool = False) -> None:
    """Keep unique supplied URLs in order without source-specific transformations."""
    supplied = filter(None, [listing.get('image_url'), *listing.get('image_urls', []), *urls])
    positions: dict[str, int] = {}
    unique: list[str] = []
    for url in supplied:
        if not photo_url(url):
            continue
        identity = url
        if identity not in positions:
            positions[identity] = len(unique)
            unique.append(url)
    listing['image_urls'] = unique
    listing['image_url'] = next(iter(unique), None)
    listing['gallery_status'] = ('complete' if complete else 'partial') if unique else 'unavailable'


def location(listing: dict[str, Any], address: dict[str, Any], coordinates: dict[str, Any] | None = None) -> None:
    """Retain advertised address and precision; coordinates alone prove no building."""
    for target, keys in {'street': ('street', 'streetAddress'), 'house_number': ('houseNumber', 'house_number'), 'postcode': ('postcode', 'postalCode'), 'city': ('city', 'addressLocality'), 'district': ('quarter', 'district', 'district_custom')}.items():
        for key in keys:
            if address.get(key) not in (None, ''):
                listing[target] = text(address[key])
                break
    coords = coordinates or address.get('wgs84Coordinate') or address.get('geo') or address
    def coordinate(value: Any) -> float | None:
        try:
            result = float(str(value).replace(',', '.'))
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None
    lat = coordinate(coords.get('latitude', coords.get('lat')))
    lon = coordinate(coords.get('longitude', coords.get('lng', coords.get('lon'))))
    precision = address.get('location_precision') or address.get('precision') or coords.get('precision')
    approximate = flag(address.get('approximate', coords.get('approximate')))
    if approximate is True:
        listing['location_approximation_declared'] = True
    if precision not in {'building', 'street', 'postcode', 'district', 'city'}:
        precision = 'unknown'
    if approximate is True and precision == 'building':
        precision = 'unknown'
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        listing.update(latitude=lat, longitude=lon, location_source=listing['provider'], location_precision=precision, location_approximate=approximate if approximate is not None else precision != 'building')
    elif listing.get('location_precision') == 'unknown' and listing.get('latitude') is None:
        listing['location_precision'] = 'street' if listing.get('street') else 'district' if listing.get('district') else 'city' if listing.get('city') else 'unknown'


async def response_text(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    """Fetch one bounded public source response with a small expiring LRU cache."""
    cached = _CACHE.get(url)
    if cached and cached[0] > time.monotonic():
        _CACHE.move_to_end(url)
        return cached[1]
    chunks: list[bytes] = []
    size = 0
    async with client.stream('GET', url, headers=headers, timeout=6, follow_redirects=False) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError('Housing detail response exceeds byte limit')
            chunks.append(chunk)
    result = b''.join(chunks).decode('utf-8', errors='replace')
    _CACHE[url] = (time.monotonic() + CACHE_TTL_SECONDS, result)
    _CACHE.move_to_end(url)
    while len(_CACHE) > CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return result


async def enrich(listings: list[dict[str, Any]], fetch: Callable[[dict[str, Any]], Awaitable[None]]) -> list[str]:
    """Bound total optional detail latency and concurrency; keep failed covers."""
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    warnings: list[str] = []

    async def one(listing: dict[str, Any]) -> None:
        async with semaphore:
            try:
                await fetch(listing)
            except Exception as exc:
                logger.debug('Housing details unavailable provider=%s id=%s: %s', listing.get('provider'), listing.get('id'), exc)
                listing['detail_status'] = 'unavailable'
                warnings.append(f"{listing['provider']} listing details or gallery unavailable")

    tasks = [asyncio.create_task(one(item)) for item in listings]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), DETAIL_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        warnings.append('Housing detail deadline reached; coverage is partial')
        for listing in listings:
            if listing.get('detail_status') != 'available':
                listing['detail_status'] = 'unavailable'
    return sorted(set(warnings))


class DetailHTML(HTMLParser):
    """Read gallery scopes, description, label/value rows and listing JSON-LD.

    Image extraction is deliberately confined to a gallery or image itemprop,
    avoiding advertiser avatars, recommendations and tracking pixels.
    """
    def __init__(self, html: str, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.images: list[str] = []
        self.gallery_seen = False
        self.description: list[str] = []
        self.lines: list[str] = []
        self.metadata: dict[str, str] = {}
        self.address_text: dict[str, list[str]] = {}
        self.jsonld: list[Any] = []
        self._script: list[str] | None = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or '' for k, v in attrs}
        identity = ' '.join((attr.get('id', ''), attr.get('class', ''), attr.get('data-testid', ''))).lower()
        def gallery_container(attributes: dict[str, str]) -> bool:
            identifiers = {attributes.get('id', '').lower(), attributes.get('data-testid', '').lower(), *attributes.get('class', '').lower().split()}
            return bool(identifiers & {
                'gallery', 'image-gallery', 'imagegallery', 'gallery-container',
                'gallery-wrapper', 'galleryimage', 'gallery-image', 'gallery-item',
                'galleryimage-element', 'galleryimage-large',
            })

        def unrelated(attributes: dict[str, str]) -> bool:
            labels = ' '.join(attributes.get(key, '').lower() for key in ('id', 'class', 'data-testid'))
            return bool(re.search(r'(?:^|[\s_-])(?:recommendations?|recommended|related|similar|avatar|profile|seller|user-gallery)(?:[\s_-]|$)', labels))

        ancestry = [attributes for _, attributes in self.stack] + [attr]
        gallery = any(gallery_container(attributes) for attributes in ancestry) and not any(unrelated(attributes) for attributes in ancestry)
        self.gallery_seen |= gallery
        if tag == 'script' and attr.get('type') == 'application/ld+json':
            self._script = []
        if 'map' in identity:
            for key in ('latitude', 'longitude', 'lat', 'lng', 'lon', 'precision', 'approximate'):
                if attr.get(f'data-{key}'):
                    self.metadata[key] = attr[f'data-{key}']
        if tag == 'meta':
            self.metadata[attr.get('property', attr.get('itemprop', attr.get('name', '')))] = attr.get('content', '')
        if gallery and tag in {'img', 'a', 'source', 'div', 'meta'}:
            lazy_keys = ('data-imgsrc', 'data-large', 'data-src', 'data-medium', 'data-small')
            has_lazy_photo = any(photo_url(urljoin(self.base_url, attr[key])) for key in lazy_keys if attr.get(key))
            for key in (*lazy_keys, 'src', 'href', 'content'):
                if key == 'src' and has_lazy_photo:
                    continue  # A supplied lazy source takes precedence over a placeholder.
                if key in attr:
                    url = photo_url(urljoin(self.base_url, attr[key]))
                    if url and (tag != 'a' or re.search(r'\.(?:jpe?g|png|webp)(?:[?/#]|$)', url, re.I)):
                        self.images.append(url)
            for key in ('srcset', 'data-srcset'):
                for candidate in attr.get(key, '').split(','):
                    parts = candidate.strip().split()
                    url = photo_url(urljoin(self.base_url, parts[0])) if parts else None
                    if url:
                        self.images.append(url)
        if tag not in {'img', 'meta', 'link', 'source', 'input', 'br', 'hr', 'wbr', 'area', 'embed', 'param'}:
            self.stack.append((tag, attr))
        if tag in {'br', 'li', 'p', 'div', 'span', 'dt', 'dd'}:
            self.lines.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script' and self._script is not None:
            try:
                self.jsonld.append(json.loads(''.join(self._script)))
            except (ValueError, TypeError):
                logger.debug('Unrecognized housing JSON-LD')
            self._script = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        self.lines.append('\n')

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
            return
        if any(tag in {'script', 'style'} for tag, _ in self.stack):
            return
        self.lines.append(data)
        for _, attr in self.stack:
            key = attr.get('itemprop', '')
            if key in {'streetAddress', 'postalCode', 'addressLocality', 'latitude', 'longitude'}:
                self.address_text.setdefault(key, []).append(data)
        if any(a.get('id') in {'description'} or a.get('itemprop') == 'description' for _, a in self.stack):
            self.description.append(data)

    def listing_json(self) -> dict[str, Any]:
        """Prefer the current listing JSON-LD node; ignore other listing URLs."""
        candidates: list[dict[str, Any]] = []
        page = urlsplit(self.base_url)
        def current_url(value: Any) -> bool:
            candidate = urlsplit(urljoin(self.base_url, str(value)))
            return (candidate.hostname or '').removeprefix('www.') == (page.hostname or '').removeprefix('www.') and candidate.path.rstrip('/') == page.path.rstrip('/')
        def walk(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
            if isinstance(value, dict):
                types = value.get('@type', [])
                types = types if isinstance(types, list) else [types]
                if set(types) & {'Apartment', 'House', 'Residence', 'Accommodation', 'RealEstateListing', 'Product', 'Offer'}:
                    candidates.append(value)
                # mainEntity and @graph describe the current page. ItemList and
                # offers/recommendation collections are not listing galleries.
                walk(value.get('@graph', []))
                walk(value.get('mainEntity', []))
        walk(self.jsonld)
        for candidate in candidates:
            if candidate.get('url') and current_url(candidate['url']):
                return candidate
        unspecified = [candidate for candidate in candidates if not candidate.get('url') and (not candidate.get('@id') or current_url(candidate['@id']))]
        return unspecified[0] if len(unspecified) == 1 else {}


def html_details(listing: dict[str, Any], html: str) -> None:
    """Merge available public detail HTML, JSON-LD and advertised feature rows."""
    parsed = DetailHTML(html, listing['url'])
    structured = parsed.listing_json()
    listing['description'] = text(' '.join(parsed.description)) or text(structured.get('description')) or listing.get('description')
    address = structured.get('address', {})
    if isinstance(address, dict):
        location(listing, address, structured.get('geo'))
    advertised_address = {key: text(' '.join(parts)) for key, parts in parsed.address_text.items()}
    locality = advertised_address.get('locality', '')
    postal = re.match(r'(\d{5})\s+(.+)', locality)
    if postal:
        advertised_address.setdefault('postalCode', postal.group(1))
        city, separator, district = postal.group(2).partition(' - ')
        advertised_address.setdefault('addressLocality', city)
        if separator:
            advertised_address['district'] = district
    if advertised_address:
        location(listing, advertised_address)
    # Provider metadata contains their published map point; precision stays unknown.
    meta_lat = parsed.metadata.get('latitude') or parsed.metadata.get('place:location:latitude') or parsed.metadata.get('og:latitude') or parsed.metadata.get('lat')
    meta_lon = parsed.metadata.get('longitude') or parsed.metadata.get('place:location:longitude') or parsed.metadata.get('og:longitude') or parsed.metadata.get('lng') or parsed.metadata.get('lon')
    if meta_lat and meta_lon:
        location(listing, {}, {'latitude': meta_lat, 'longitude': meta_lon, 'precision': parsed.metadata.get('precision'), 'approximate': parsed.metadata.get('approximate')})
    lines = [text(line) for line in ''.join(parsed.lines).splitlines() if text(line)]
    labels = {'Kaltmiete': 'cold_rent_eur', 'Warmmiete': 'warm_rent_eur', 'Gesamtmiete': 'warm_rent_eur', 'Nebenkosten': 'utilities_eur', 'Heizkosten': 'heating_costs_eur', 'Kaution': 'deposit', 'Kaution / Genoss.-Anteile': 'deposit', 'Etage': 'floor', 'Verfügbar ab': 'available_from', 'Verfügbar bis': 'available_to', 'Wohnfläche': 'size_sqm', 'Zimmer': 'rooms'}
    amenity_labels = {'Balkon': 'balcony', 'Möbliert': 'furnished', 'Aufzug': 'elevator', 'Garten': 'garden', 'Terrasse': 'terrace', 'Stellplatz': 'parking', 'Haustiere erlaubt': 'pets_allowed'}
    for index, line in enumerate(lines):
        label, separator, inline = line.partition(':')
        value = inline.strip() if separator else lines[index + 1] if index + 1 < len(lines) else ''
        if label in labels:
            key = labels[label]
            parsed_value = number(value) if key.endswith('_eur') or key in {'deposit', 'size_sqm', 'rooms'} else value
            if parsed_value is not None and parsed_value != '':
                listing[key] = parsed_value
        if label in amenity_labels:
            # A standalone feature badge establishes presence; no prose inference.
            amenity(listing, amenity_labels[label], value if separator or value.lower() in {'ja', 'nein', 'yes', 'no', '0', '1', 'keine angabe'} else True)
    for feature in structured.get('amenityFeature', []):
        if isinstance(feature, dict):
            key = amenity_labels.get(feature.get('name'), feature.get('name'))
            if key in AMENITIES:
                amenity(listing, key, feature.get('value'))
    for key, value in listing['amenities'].items():
        listing[key] = value
    if listing.get('listing_type') != 'buy':
        if listing.get('warm_rent_eur') is not None:
            listing.update(price=listing['warm_rent_eur'], price_type='warm')
        elif listing.get('cold_rent_eur') is not None:
            listing.update(price=listing['cold_rent_eur'], price_type='cold')
    if listing.get('price') is not None:
        suffix = 'EUR' if listing.get('listing_type') == 'buy' else 'EUR/month'
        listing['price_label'] = f"{listing['price']:,.0f} {suffix}".replace(',', '.')
    structured_images = structured.get('image')
    structured_photos = photos(structured_images)
    gallery_photos = [url for url in parsed.images if photo_url(url)]
    # A recognized but empty/lazy wrapper is no evidence that all photos were
    # obtained. JSON-LD's single image is often only the search cover. A typed
    # image array supplies an explicit collection; otherwise require photos
    # actually extracted from the listing's gallery container.
    structured_collection = isinstance(structured_images, list) and len({
        url for url in structured_photos if photo_url(url)
    }) > 1
    merge_gallery(listing, structured_photos + gallery_photos,
                  complete=bool(gallery_photos) or structured_collection)
    if not listing['description'] and not parsed.gallery_seen and not structured:
        raise ValueError('Unrecognized housing detail page')
    listing['detail_status'] = 'available'
