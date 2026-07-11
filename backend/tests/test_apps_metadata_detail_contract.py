# backend/tests/test_apps_metadata_detail_contract.py
#
# Focused contract tests for the metadata consumed by native Apps settings.
# Fixtures use shared AppYAML/provider schemas and never call provider services.
# The response must carry enough data for native details without web fallbacks.

from backend.core.api.app.routes.apps import (
    AppMetadataItem,
    AppMetadataResponse,
    build_app_metadata_item,
)
from backend.shared.python_schemas.app_metadata_schemas import AppYAML


def test_build_app_metadata_item_preserves_native_detail_contract() -> None:
    app = AppYAML.model_validate(
        {
            "id": "images",
            "name_translation_key": "images",
            "description_translation_key": "images.description",
            "icon_image": "images.svg",
            "category": "work",
            "last_updated": "2026-07-01",
            "provider_display_order": ["Recraft"],
            "skills": [
                {
                    "id": "generate",
                    "name_translation_key": "app_skills.images.generate",
                    "description_translation_key": "app_skills.images.generate.description",
                    "icon_image": "image.svg",
                    "pricing": {"per_unit": {"credits": 50, "unit_name": "image"}},
                    "providers": ["Recraft"],
                }
            ],
            "focus_modes": [
                {
                    "id": "art_director",
                    "name_translation_key": "images.art_director",
                    "description_translation_key": "images.art_director.description",
                    "icon_image": "planning.svg",
                    "process": ["Clarify the visual goal", "Create the image"],
                    "systemprompt": "Direct the visual work.",
                    "how_to_use": ["Create a **launch image**"],
                }
            ],
            "settings_and_memories": [
                {
                    "id": "preferred_styles",
                    "name_translation_key": "images.preferred_styles",
                    "description_translation_key": "images.preferred_styles.description",
                    "icon_image": "image.svg",
                    "type": "list",
                    "example_translation_keys": ["images.preferred_styles.example_1"],
                }
            ],
            "embed_types": [
                {
                    "id": "image",
                    "category": "direct",
                    "frontend_type": "image",
                    "backend_type": "image",
                    "icon": "image",
                    "content_catalog": {
                        "enabled": True,
                        "id": "images.image",
                        "content_type_id": "image",
                        "name": "Image",
                        "description": "Generated or uploaded image.",
                        "order": 10,
                    },
                }
            ],
        }
    )
    providers = {
        "recraft": {
            "provider_id": "recraft",
            "name": "Recraft",
            "description": "Image generation provider.",
            "logo_svg": "icons/recraft.svg",
            "country": "US",
            "privacy_policy": "https://example.invalid/privacy",
            "models": [
                {
                    "id": "recraft-v4",
                    "name": "Recraft V4",
                    "description": "Raster generation model.",
                    "for_app_skill": "images.generate",
                    "pricing": {"per_unit": {"credits": 50, "unit_name": "image"}},
                }
            ],
        }
    }

    item = build_app_metadata_item(
        app_id="images",
        app_metadata=app,
        translation_service=None,
        provider_configs=providers,
    )
    payload = item.model_dump(mode="json", exclude_none=True)
    response_payload = AppMetadataResponse(apps={"images": item}).model_dump(mode="json")

    assert payload["icon_image"] == "images.svg"
    assert payload["last_updated"] == "2026-07-01"
    assert payload["provider_display_order"] == ["Recraft"]
    assert payload["skills"][0]["icon_image"] == "image.svg"
    assert payload["skills"][0]["pricing"]["per_unit"]["credits"] == 50
    assert payload["skills"][0]["provider_details"][0]["id"] == "recraft"
    assert payload["skills"][0]["models"][0]["id"] == "recraft-v4"
    assert payload["focus_modes"][0]["process"] == [
        "Clarify the visual goal",
        "Create the image",
    ]
    assert payload["focus_modes"][0]["system_prompt"] == "Direct the visual work."
    assert payload["focus_modes"][0]["how_to_use"] == ["Create a **launch image**"]
    assert payload["settings_and_memories"][0]["type"] == "list"
    assert payload["settings_and_memories"][0]["icon_image"] == "image.svg"
    assert payload["content_types"][0]["content_type_id"] == "image"
    assert response_payload["apps"]["images"]["skills"][0]["id"] == "generate"


def test_rich_response_remains_compatible_with_specific_app_shape() -> None:
    item = AppMetadataItem.model_validate(
        {
            "id": "travel",
            "name": "Travel",
            "description": "Travel tools",
            "skills": [],
            "focus_modes": [],
            "settings_and_memories": [
                {"id": "trips", "name": "Trips", "description": "Saved trips"}
            ],
        }
    )

    assert item.settings_and_memories[0].type == ""
    assert item.content_types == []
