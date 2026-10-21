"""HTTP fixture evidence for home-search rich-provider-evidence and complete-gallery.

Specification: feature.app-skill.home-search@1
Assertions: home-search.listings.rich-provider-evidence,
home-search.images.complete-gallery, home-search.location.precision,
home-search.enrichment.bounded-and-reusable.
"""
import asyncio

import httpx
import pytest

from backend.apps.home.providers import immoscout24, kleinanzeigen, wg_gesucht
from backend.shared.providers.housing import details


@pytest.fixture(autouse=True)
def empty_response_cache():
    details._CACHE.clear()
    yield
    details._CACHE.clear()


def mock_client(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: client(*a, transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery
async def test_kleinanzeigen_all_eighteen_photos_and_rent_components(monkeypatch):
    cover = 'https://img.kleinanzeigen.de/0.jpg'
    search = f'''<article data-adid="1234"><h2><a href="/s-anzeige/wohnung/1234-203">Wohnung</a></h2>
        <p>1.500 €</p><span>10115 Berlin</span><img src="{cover}"><span>65 m² 2 Zimmer</span></article>'''
    gallery = ''.join(f'<div class="galleryimage-element"><img data-src="https://img.kleinanzeigen.de/{n}.jpg"></div>' for n in range(18))
    page = f'''<main><div id="viewad-description-text">Apartment with advertised details.</div>
        <ul><li>Kaltmiete<span>1.200 €</span></li><li>Warmmiete<span>1.500 €</span></li>
        <li>Nebenkosten<span>300 €</span></li><li>Etage<span>3</span></li>
        <li>Balkon: Nein</li><li>Möbliert: Ja</li><li>Kaution<span>0 €</span></li></ul>{gallery}
        <img src="https://img.kleinanzeigen.de/avatar.jpg"></main>'''
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=page if '/s-anzeige/' in request.url.path else search)
    mock_client(monkeypatch, handler)
    listing = (await kleinanzeigen.search_listings('Berlin', max_results=1))[0]
    assert listing['image_urls'] == [f'https://img.kleinanzeigen.de/{n}.jpg' for n in range(18)]
    assert listing['image_url'] == cover
    assert listing['gallery_status'] == 'complete'
    assert listing['cold_rent_eur'] == 1200 and listing['warm_rent_eur'] == 1500
    assert listing['utilities_eur'] == 300 and listing['price_type'] == 'warm'
    assert listing['balcony'] is False and listing['furnished'] is True
    assert listing['elevator'] is None and listing['deposit'] == 0
    assert listing['floor'] == '3'
    await kleinanzeigen.search_listings('Berlin', max_results=1)
    assert sum('/s-anzeige/' in url for url in requests) == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery
async def test_immoscout_mobile_detail_sections_and_complete_gallery(monkeypatch):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'resultListItems': [{'type': 'AD'}, {'type': 'EXPOSE_RESULT', 'item': {'id': 123, 'title': 'Apartment', 'attributes': [{'value': '900 €'}, {'value': '55 m²'}, {'value': '2 Zi.'}], 'titlePicture': {'full': 'https://images.example/cover.jpg'}}}]})
        return httpx.Response(200, json={'realEstate': {'address': {'city': 'Berlin', 'quarter': 'Mitte', 'wgs84Coordinate': {'latitude': 52.5, 'longitude': 13.4}, 'approximate': True, 'precision': 'district'}, 'baseRent': 900, 'totalRent': 1150, 'lift': False, 'petsAllowed': 'NO_INFORMATION', 'descriptionNote': 'Advertised description', 'attachments': {'attachment': [{'urls': {'url': [{'@href': 'https://images.example/small.jpg'}, {'@href': 'https://images.example/photo2.jpg'}]}}]}, 'sections': [{'items': [{'label': 'Balkon', 'value': 'Ja'}, {'label': 'Etage', 'value': '3'}]}]}})
    mock_client(monkeypatch, handler)
    listing = (await immoscout24.search_listings('Berlin', max_results=1))[0]
    assert listing['image_urls'] == ['https://images.example/cover.jpg', 'https://images.example/photo2.jpg']
    assert listing['gallery_status'] == 'complete'
    assert listing['price_type'] == 'warm' and listing['price'] == 1150
    assert listing['cold_rent_eur'] == 900
    assert listing['balcony'] is True and listing['elevator'] is False
    assert listing['pets_allowed'] is None
    assert listing['latitude'] == 52.5 and listing['location_precision'] == 'district'
    assert listing['location_approximate'] is True


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery
async def test_wg_detail_api_plus_public_gallery_and_unknown_flags(monkeypatch):
    def handler(request):
        if '/api/offers/' in request.url.path:
            return httpx.Response(200, json={'offer_title': 'WG room', 'category': 0, 'rent_costs': 600, 'total_costs': 800, 'additional_costs': 200, 'furnished': '0', 'balcony': '1', 'bond_costs': 0, 'available_from_date': '01.11.2026', 'available_to_date': '31.12.2026', 'floor': 3, 'property_description': 'A sunny room.', 'street': 'Example road', 'postcode': '10115', 'latitude': 52.5, 'longitude': 13.4})
        if request.url.path.endswith('.12345.html'):
            return httpx.Response(200, text='<div class="gallery"><img src="https://img.wg-gesucht.de/media/cover.jpg"><img data-src="https://img.wg-gesucht.de/media/2.jpg"></div>')
        return httpx.Response(200, text='<main><div data-id="12345"><a href="/wg-zimmer-in-Berlin.12345.html"><img src="https://img.wg-gesucht.de/media/cover.jpg"></a></div></main>')
    mock_client(monkeypatch, handler)
    listing = (await wg_gesucht.search_listings('Berlin', property_type='shared_room'))[0]
    assert len(listing['image_urls']) == 2 and listing['gallery_status'] == 'complete'
    assert listing['furnished'] is False and listing['balcony'] is True and listing['garden'] is None
    assert listing['cold_rent_eur'] == 600 and listing['price_type'] == 'warm'
    assert listing['description'] == 'A sunny room.' and listing['floor'] == 3
    assert listing['available_to'] == '31.12.2026' and listing['deposit'] == 0
    assert listing['location_precision'] == 'unknown' and listing['location_approximate'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', [immoscout24, kleinanzeigen, wg_gesucht])
# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery
async def test_failed_detail_retains_cover_and_discloses_partial(monkeypatch, provider):
    cover = 'https://img.wg-gesucht.de/media/cover.jpg'
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'resultListItems': [{'type': 'EXPOSE_RESULT', 'item': {'id': 12345, 'title': 'Apartment', 'titlePicture': {'full': cover}}}]})
        if '/expose/' in request.url.path or '/api/offers/' in request.url.path or '/s-anzeige/' in request.url.path or '.12345.html' in request.url.path:
            return httpx.Response(503)
        if provider is kleinanzeigen:
            return httpx.Response(200, text=f'<article data-adid="12345"><h2><a href="/s-anzeige/flat/12345-203">Apartment</a></h2><img src="{cover}"></article>')
        return httpx.Response(200, text=f'<div data-id="12345"><img src="{cover}"></div>')
    mock_client(monkeypatch, handler)
    results = await provider.search_listings('Berlin', max_results=1)
    assert len(results) == 1 and results[0]['image_urls'] == [cover]
    assert results[0]['gallery_status'] == 'partial' and results.warnings
    assert results[0]['detail_status'] == 'unavailable'


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_detail_concurrency_and_total_deadline(monkeypatch):
    active = peak = 0
    async def fetch(listing):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.02)
            listing['detail_status'] = 'available'
        finally:
            active -= 1
    monkeypatch.setattr(details, 'DETAIL_DEADLINE_SECONDS', .03)
    listings = [details.defaults({'id': str(n), 'provider': 'fixture'}) for n in range(20)]
    warnings = await details.enrich(listings, fetch)
    assert peak == details.DETAIL_CONCURRENCY and active == 0
    assert warnings and sum(item['detail_status'] == 'available' for item in listings) == 4


# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.location.precision
def test_unsupported_location_and_amenity_values_remain_unknown():
    listing = wg_gesucht._normalize_listing('123', {'furnished': 'NO_INFORMATION'})
    assert listing['furnished'] is None and listing['balcony'] is None
    assert listing['latitude'] is None and listing['gallery_status'] == 'unavailable'
    assert details.number('1.200,50 €') == 1200.5
    assert details.number('52.51') == 52.51


# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.location.precision
def test_html_address_map_point_and_conflicting_flags():
    listing = details.defaults({'provider': 'Kleinanzeigen', 'url': 'https://www.kleinanzeigen.de/s-anzeige/1', 'listing_type': 'buy', 'price': 250000})
    details.html_details(listing, '''<div id="viewad-locality">10115 Berlin - Mitte</div>
        <div id="viewad-map" data-latitude="52.512" data-longitude="13.412"></div>
        <div id="viewad-description-text">Description</div>
        <p>Balkon: Ja</p><p>Balkon: Nein</p>''')
    assert listing['city'] == 'Berlin' and listing['district'] == 'Mitte' and listing['postcode'] == '10115'
    assert listing['latitude'] == 52.512
    assert listing['location_precision'] == 'unknown' and listing['location_approximate'] is True
    assert listing['price_type'] == 'purchase'
    assert listing['balcony'] is None and listing['amenity_conflicts']['balcony'] == [True, False]
    assert listing['gallery_status'] == 'unavailable'


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.enrichment.bounded-and-reusable
async def test_streamed_response_byte_limit_is_not_cached(monkeypatch):
    monkeypatch.setattr(details, 'MAX_RESPONSE_BYTES', 8)
    mock_client(monkeypatch, lambda request: httpx.Response(200, text='too much response data'))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match='byte limit'):
            await details.response_text(client, 'https://example.org/detail', {})
    assert not details._CACHE


# contract-test: supporting surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery
def test_gallery_deduplicates_supplied_renditions_and_keeps_cover():
    cover = 'https://pictures.is24.de/pic/asset.jpg/ORIG/resize/100x100/format/jpg'
    listing = details.defaults({'image_url': cover})
    details.merge_gallery(listing, ['https://pictures.is24.de/pic/asset.jpg/ORIG/resize/1000x1000/format/jpg', 'https://pictures.is24.de/pic/second.jpg/ORIG/resize/1000x1000/format/jpg'], complete=True)
    assert len(listing['image_urls']) == 2
    assert listing['image_urls'][0] == 'https://pictures.is24.de/pic/asset.jpg/ORIG/resize/1000x1000/format/jpg'
    assert listing['image_url'] == listing['image_urls'][0]


# contract-test: direct surface=rest_api assertions=home-search.location.precision
def test_declared_approximation_survives_missing_provider_coordinates():
    listing = details.defaults({'provider': 'fixture'})
    details.location(listing, {'city': 'Berlin', 'approximate': True})
    assert listing['location_approximation_declared'] is True
    assert listing['latitude'] is None
    assert listing['location_precision'] == 'city'


# contract-test: supporting surface=rest_api assertions=home-search.images.complete-gallery
def test_wg_real_shape_renditions_upgrade_cover_without_reordering_or_cap():
    prefix = 'https://img.wg-gesucht.de/media/up/2026/42/'
    cover = prefix + 'sanitized-cover.small.JPEG'
    listing = details.defaults({'provider': 'WG-Gesucht', 'url': 'https://www.wg-gesucht.de/wohnungen-in-Berlin.12345.html', 'image_url': cover})
    # Supplied small/sized/large filename suffixes mirror the audited response;
    # photo IDs and document text are fabricated, not copied from the advert.
    supplied = ''.join(f'<a href="{prefix}photo-{index}.large.jpg"><img src="{prefix}photo-{index}.sized.jpg"></a>' for index in range(24))
    html = f'''<main class="listing-page" data-gallery-config="gallery-ready">
      <div id="gallery"><a href="{prefix}sanitized-cover.large.JPEG"><img src="{prefix}sanitized-cover.sized.JPEG"></a>{supplied}</div>
      <div class="profile"><img itemprop="image" src="{prefix}avatar.large.jpg"></div>
      <section id="recommended-offers"><div class="gallery"><img src="{prefix}other-ad.large.jpg"></div></section>
    </main>'''
    details.html_details(listing, html)
    expected = [prefix + 'sanitized-cover.large.JPEG', *[prefix + f'photo-{index}.large.jpg' for index in range(24)]]
    assert listing['image_urls'] == expected
    assert listing['image_url'] == expected[0] and listing['gallery_status'] == 'complete'


# contract-test: supporting surface=rest_api assertions=home-search.images.complete-gallery
def test_kleinanzeigen_real_shape_rule_variants_exclude_avatar_and_recommendations():
    prefix = 'https://img.kleinanzeigen.de/api/v1/prod-ads/images/'
    cover = prefix + 'aa/sanitized-cover?rule=$_1.AUTO'
    first = prefix + 'aa/sanitized-cover?rule=$_59.AUTO'
    second = prefix + 'bb/sanitized-second?rule=$_59.AUTO'
    avatar = 'https://img.kleinanzeigen.de/api/v1/prod-user/images/cc/sanitized-avatar?rule=$_12.JPG'
    unrelated = prefix + 'dd/other-ad?rule=$_59.AUTO'
    listing = details.defaults({'provider': 'Kleinanzeigen', 'url': 'https://www.kleinanzeigen.de/s-anzeige/test/123-203', 'image_url': cover})
    # Parent attributes containing gallery config used to mark the entire page
    # as a gallery. Only actual gallery containers own apartment photos.
    html = f'''<main data-gallery-config="gallery-enabled">
      <div class="galleryimage-element"><a href="{first}"><img id="viewad-image" src="{cover}"></a></div>
      <div class="galleryimage-element"><img data-src="{second}"></div>
      <div class="galleryimage-element"><img src="{avatar}"></div>
      <aside class="seller-profile"><img itemprop="image" src="{avatar}"></aside>
      <section class="recommendations"><div class="gallery"><img itemprop="image" src="{unrelated}"></div></section>
      <a href="/s-anzeige/other/999-203"><img itemprop="image" src="{unrelated}"></a>
    </main>'''
    details.html_details(listing, html)
    assert listing['image_urls'] == [first, second]
    assert listing['image_url'] == first
    assert listing['gallery_status'] == 'complete'
    # Subsequent lower-quality discoveries cannot downgrade the cover.
    details.merge_gallery(listing, [cover], complete=True)
    assert listing['image_url'] == first and listing['image_urls'] == [first, second]


# contract-test: supporting surface=rest_api assertions=home-search.images.complete-gallery
def test_structured_images_belong_to_current_listing_not_recommended_product():
    listing_url = 'https://www.kleinanzeigen.de/s-anzeige/test/123-203'
    listing = details.defaults({'provider': 'Kleinanzeigen', 'url': listing_url})
    html = '''<script type="application/ld+json">{"@graph":[
      {"@type":"Product","url":"https://www.kleinanzeigen.de/s-anzeige/other/999-203","image":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/other"},
      {"@type":"Product","url":"https://www.kleinanzeigen.de/s-anzeige/test/123-203","description":"A supplied apartment description.","image":[
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/first?rule=$_59.AUTO",
        "https://img.kleinanzeigen.de/api/v1/prod-user/images/avatar",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/bb/second?rule=$_59.AUTO"]}
    ]}</script><img itemprop="image" src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/other">'''
    details.html_details(listing, html)
    assert listing['image_urls'] == ['https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/first?rule=$_59.AUTO', 'https://img.kleinanzeigen.de/api/v1/prod-ads/images/bb/second?rule=$_59.AUTO']
    assert listing['gallery_status'] == 'complete'


# contract-test: supporting surface=rest_api assertions=home-search.images.complete-gallery
def test_avatar_only_recognized_gallery_is_unavailable_with_no_primary():
    avatar = 'https://img.kleinanzeigen.de/api/v1/prod-user/images/aa/sanitized-avatar?rule=$_12.JPG'
    listing = details.defaults({'provider': 'Kleinanzeigen', 'url': 'https://www.kleinanzeigen.de/s-anzeige/test/123-203', 'image_url': avatar})
    details.html_details(listing, f'<div class="galleryimage-element"><img src="{avatar}"></div>')
    assert listing['image_urls'] == []
    assert listing['image_url'] is None
    assert listing['gallery_status'] == 'unavailable'
