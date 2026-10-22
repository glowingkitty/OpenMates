/** Local media fixture: galleries are independent of the bounded analysis coverage. */
export const listing = {
  title: 'Canal apartment with balcony', price_label: '1,250 EUR warm / month',
  price_type: 'warm', cold_rent_eur: 1000, warm_rent_eur: 1250, utilities_eur: 250,
  size_sqm: 65, rooms: 2, address: 'Kreuzberg, Berlin', floor: 3,
  available_from: '2026-12-01', deposit: 3000, provider: 'WG-Gesucht',
  url: 'https://www.wg-gesucht.de/wohnungen-in-Berlin.12345.html',
  description: 'Bright apartment with a private balcony. Separate kitchen and a canal nearby.',
  image_url: '/store-examples/home-1.webp',
  image_urls: ['/store-examples/home-1.webp', '/store-examples/home-2.webp', '/store-examples/home-3.webp'],
  gallery_status: 'complete', balcony: true, furnished: false, pets_allowed: null,
  latitude: 52.49, longitude: 13.42, location_precision: 'district',
  location: {exact_address: false, area: {latitude: 52.49, longitude: 13.42, radius_m: 1200, basis: 'district', method: 'district_extent', source: 'Provider district location', checked_at: '2026-10-21'}},
  location_approximate: true, location_source: 'Provider district location',
  match_evidence: {status: 'unconfirmed', amenities: {balcony: {status: 'confirmed', expectation: 'present', advertised: true, text_status: 'present', visual_status: 'uncertain'}}},
  visual_assessment: {status: 'partial', photo_count: 2, total_photo_count: 3, features: {balcony: {status: 'uncertain', photo_indices: [1]}}},
  neighborhood: {status: 'partial', source: 'Geoapify', checked_at: '2026-10-21', location_precision: 'district', coverage: {water: {status: 'partial', exhaustive: false}, park: {status: 'no_features_returned', exhaustive: false}}, features: {water: [{name: 'Landwehr Canal', distance_m: null, distance_method: 'unknown', walk_minutes: null, walk_status: 'access_unknown', source: 'Geoapify', checked_at: '2026-10-21', location_precision: 'approximate'}], park: []}}
};
const defaultProps = { data: {decodedContent: listing}, onClose: () => {} };
export default defaultProps;
export const variants = {
  rentDetails: {data: {decodedContent: {...listing, price: 1250, heating_costs_eur: 80, available_to: '2027-06-30'}}},
  legacyApproximate: {data: {decodedContent: {...listing, location: {exact_address: false}}}},
  cityArea: {data: {decodedContent: {...listing, location_precision: 'city', location: {area: {latitude: 52.52, longitude: 13.405, radius_m: 18000, basis: 'city', method: 'city_extent', source: 'Provider city', checked_at: '2026-10-21'}}}}},
  persistedFlattened: {data: {decodedContent: {
    title: 'Persisted canal apartment', provider: 'WG-Gesucht', address: 'Kreuzberg, Berlin', price: 1250, price_label: '1,250 EUR warm / month', price_type: 'warm', warm_rent_eur: 1250,
    image_url: '/store-examples/home-1.webp', image_urls: '/store-examples/home-1.webp|/store-examples/home-2.webp|/store-examples/home-3.webp', gallery_status: 'complete',
    location_area_latitude: 52.49, location_area_longitude: 13.42, location_area_radius_m: 650, location_area_basis: 'description', location_area_method: 'description_landmark', location_area_source: 'Listing description', location_area_checked_at: '2026-10-21', location_area_evidence_quote: 'near the canal',
    location_precision: 'district', location_approximate: true, location_source: 'Provider district location', latitude: 52.49, longitude: 13.42,
    amenities_balcony: true, amenities_furnished: false, amenities_pets_allowed: false,
    match_evidence_status: 'confirmed', match_evidence_amenities_balcony_status: 'confirmed', match_evidence_amenities_balcony_expectation: 'present', match_evidence_amenities_balcony_advertised: true, match_evidence_amenities_balcony_text_status: 'present', match_evidence_amenities_balcony_visual_status: 'uncertain', match_evidence_amenities_balcony_source_conflict: false,
    visual_assessment_status: 'partial', visual_assessment_photo_count: 2, visual_assessment_total_photo_count: 3, visual_assessment_features_balcony_status: 'uncertain', visual_assessment_features_balcony_photo_indices: '0|1',
    neighborhood_status: 'partial', neighborhood_source: 'Geoapify', neighborhood_checked_at: '2026-10-21', neighborhood_location_precision: 'district', neighborhood_coverage_water_status: 'partial', neighborhood_coverage_water_exhaustive: false,
    neighborhood_features_water: [{name: 'Landwehr Canal', distance_m: null, distance_method: 'unknown', walk_minutes: null, walk_status: 'access_unknown', source: 'Geoapify', checked_at: '2026-10-21', location_precision: 'approximate', latitude: 52.48, longitude: 13.41}]
  }}},
  nearbyEvidence: {data: {decodedContent: {...listing, address: 'Example Street 12, Berlin', location: {exact_address: true}, location_precision: 'building', location_approximate: false, neighborhood: {...listing.neighborhood, location_precision: 'building', features: {water: [
    {name: 'Canal shoreline', distance_m: 120, distance_method: 'shoreline_geometry', walk_minutes: 8, walk_status: 'routed', source: 'Geoapify', checked_at: '2026-10-21', location_precision: 'building'},
    {name: 'Lake map point', distance_m: 700, distance_method: 'representative_point', walk_minutes: 5, walk_status: 'access_unknown', source: 'Geoapify', checked_at: '2026-10-21', location_precision: 'building'}
  ]}}}}},
  longGallery: {data: {decodedContent: {...listing, image_url: '/store-examples/home-1.webp?photo=1', image_urls: Array.from({length: 18}, (_, index) => `/store-examples/home-${index % 3 + 1}.webp?photo=${index + 1}`), visual_assessment: {...listing.visual_assessment, photo_count: 2, total_photo_count: 18}}}},
  noPhotosWithMap: {data: {decodedContent: {...listing, image_url: '', image_urls: [], gallery_status: 'unavailable'}}},
  noPhotos: {data: {decodedContent: {...listing, image_url: '', image_urls: [], gallery_status: 'unavailable', location: {}, latitude: null, longitude: null, visual_assessment: {status: 'unavailable'}}}},
  partialGallery: {data: {decodedContent: {...listing, image_urls: [listing.image_url], gallery_status: 'partial'}}},
  serializedGallery: {data: {decodedContent: {...listing, image_urls: JSON.stringify([...listing.image_urls, listing.image_url]), match_evidence: JSON.stringify(listing.match_evidence)}}},
  precise: {data: {decodedContent: {...listing, address: 'Example Street 12, Berlin', location: {exact_address: true}, location_precision: 'building', location_approximate: false}}}
};
