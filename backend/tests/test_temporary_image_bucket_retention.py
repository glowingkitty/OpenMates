"""Existing temporary-image storage retains its privacy and expiration policy."""
from backend.core.api.app.services.s3.config import BUCKETS


# contract-test: supporting surface=rest_api assertions=storage.media.explicit-exceptions
def test_existing_temporary_images_remain_private_and_expire():
    config = BUCKETS["temp_images"]
    assert config["access"] == "private"
    assert config["lifecycle_policy"] == 1
    assert config["name"] == "openmates-temp-images"
    assert config["dev_name"] == "dev-openmates-temp-images"
