"""Source-neutral stored listing evidence keeps unknowns and supplied URLs."""
from backend.shared.providers.housing import details


# contract-test: direct surface=rest_api assertions=home-search.location.precision
def test_stored_listing_defaults_preserve_data_and_explicit_unknowns():
    row = {"provider": "Historical source", "price": 1000, "listing_type": "rent"}
    details.defaults(row)
    assert row["provider"] == "Historical source"
    assert row["warm_rent_eur"] is None
    assert row["location_precision"] == "unknown"
    assert row["location_approximate"] is None
    assert all(value is None for value in row["amenities"].values())


# contract-test: direct surface=rest_api assertions=home-search.images.complete-gallery
def test_gallery_preserves_supplied_variants_without_inventing_cdn_aliases():
    thumbnail = "https://images.example.invalid/asset.jpg?size=small"
    full = "https://images.example.invalid/asset.jpg?size=large"
    row = {"image_url": thumbnail}
    details.merge_gallery(row, [thumbnail, full, "javascript:bad"], complete=True)
    assert row["image_urls"] == [thumbnail, full]
    assert row["image_url"] == thumbnail
    assert row["gallery_status"] == "complete"


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown
def test_conflicting_stored_amenities_never_become_confirmed():
    row = details.defaults({"amenities": {"balcony": True}})
    details.amenity(row, "balcony", False)
    assert row["amenities"]["balcony"] is None
    assert row["amenity_conflicts"]["balcony"] == [True, False]
