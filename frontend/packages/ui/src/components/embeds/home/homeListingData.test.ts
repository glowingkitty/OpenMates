import { describe, expect, it } from 'vitest';
import { homeListingContent, homeImages, homeHasAmenity, homeMatchesFilters } from './homeListingData';

describe('persisted home listing evidence hydration', () => {
  // contract-test: direct surface=gui.web assertions=home-search.listings.rich-provider-evidence,home-search.vision.evidence-and-conflicts,home-search.neighborhood.sourced-facts
  it('reconstructs actual flattened TOON namespaces without splitting underscore field names', () => {
    const place = {name: 'Canal', distance_m: 120, distance_method: 'shoreline_geometry', checked_at: '2026-10-21', walk_target_latitude: 52.49};
    const listing = homeListingContent({
      title: 'Apartment', location_source: 'Listing provider', amenities_pets_allowed: false,
      match_evidence_status: 'conflicting', match_evidence_amenities_pets_allowed_status: 'conflicting',
      match_evidence_amenities_pets_allowed_source_conflict: true,
      match_evidence_amenities_pets_allowed_text_status: 'present',
      visual_assessment_status: 'partial', visual_assessment_photo_count: 2,
      visual_assessment_features_balcony_photo_indices: '0|1', visual_assessment_features_balcony_status: 'uncertain',
      neighborhood_source: 'Geoapify', neighborhood_checked_at: '2026-10-21',
      neighborhood_features_water: [place], neighborhood_features_park: '', neighborhood_coverage_water_status: 'partial',
    });
    expect(listing.location).toMatchObject({source: 'Listing provider'});
    expect(listing.amenities).toEqual({pets_allowed: false});
    expect(listing.match_evidence).toEqual({status: 'conflicting', amenities: {pets_allowed: {status: 'conflicting', source_conflict: true, text_status: 'present'}}});
    expect(listing.visual_assessment).toMatchObject({status: 'partial', photo_count: 2, features: {balcony: {photo_indices: '0|1', status: 'uncertain'}}});
    expect(listing.neighborhood).toMatchObject({source: 'Geoapify', checked_at: '2026-10-21', features: {water: [place], park: []}, coverage: {water: {status: 'partial'}}});
  });
  // contract-test: supporting surface=gui.web assertions=home-search.images.complete-gallery,home-search.vision.evidence-and-conflicts
  it('accepts nested JSON evidence and preserves all gallery photos', () => {
    const listing = homeListingContent({match_evidence: JSON.stringify({amenities: {balcony: {status: 'confirmed', expectation: 'present', text_status: 'present'}}}), visual_assessment: JSON.stringify({photo_count: 2, total_photo_count: 18}), neighborhood: JSON.stringify({features: {water: [{name: 'Canal'}]}}), image_urls: 'one|two|three'});
    expect(homeHasAmenity(listing, 'balcony')).toBe(true);
    expect(listing.visual_assessment).toMatchObject({photo_count: 2, total_photo_count: 18});
    expect(listing.neighborhood).toMatchObject({features: {water: [{name: 'Canal'}]}});
    expect(homeImages(listing.image_urls)).toEqual(['one', 'two', 'three']);
  });
  // contract-test: direct surface=gui.web assertions=home-search.filters.explicit-and-unknown
  it('keeps provider false, unknown and conflicts from satisfying hard amenity filters', () => {
    const filters = {priceBasis: 'warm' as const, maxPrice: 1500, requiredAmenity: 'balcony'};
    expect(homeMatchesFilters({warm_rent_eur: 1200, amenities_balcony: false, match_evidence_amenities_balcony_status: 'confirmed'}, filters)).toBe(false);
    expect(homeMatchesFilters({warm_rent_eur: 1200, match_evidence_amenities_balcony_status: 'unknown'}, filters)).toBe(false);
    expect(homeMatchesFilters({warm_rent_eur: 1200, balcony: true, match_evidence_amenities_balcony_source_conflict: true}, filters)).toBe(false);
    expect(homeMatchesFilters({warm_rent_eur: 1200, match_evidence_amenities_balcony_status: 'confirmed', match_evidence_amenities_balcony_expectation: 'absent'}, filters)).toBe(false);
    expect(homeMatchesFilters({warm_rent_eur: 1200, match_evidence_amenities_balcony_status: 'confirmed', match_evidence_amenities_balcony_expectation: 'present', match_evidence_amenities_balcony_text_status: 'present'}, filters)).toBe(true);
    expect(homeMatchesFilters({cold_rent_eur: 1200, amenities_balcony: true}, filters)).toBe(false);
  });
});
