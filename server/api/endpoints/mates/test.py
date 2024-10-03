def get_nested(dictionary, key_path):
    keys = key_path.split('.')
    for key in keys:
        while isinstance(dictionary, dict) and key not in dictionary:
            if "attributes" in dictionary:
                dictionary = dictionary["attributes"]
            elif "data" in dictionary:
                dictionary = dictionary["data"]
            else:
                return None
        if isinstance(dictionary, dict):
            dictionary = dictionary.get(key)
        else:
            return None
    return dictionary

# Example tests
def test_get_nested():
    example_data = {
        "id": 1,
        "attributes": {
            "name": "Test Mate",
            "config": {
                "data": {
                    "attributes": {
                        "llm_endpoint": {
                            "data": {
                                "attributes": {
                                    "slug": "test-slug",
                                    "app": {
                                        "data": {
                                            "attributes": {
                                                "slug": "app-slug"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    complex_data = {
        "id": 2,
        "attributes": {
            "profile": {
                "data": {
                    "attributes": {
                        "details": {
                            "data": {
                                "attributes": {
                                    "info": {
                                        "data": {
                                            "attributes": {
                                                "username": "complex_user",
                                                "settings": {
                                                    "data": {
                                                        "attributes": {
                                                            "theme": "dark"
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "another": "value"
        }
    }

    # Test cases
    assert get_nested(example_data, "id") == 1
    
    assert get_nested(example_data, "name") == "Test Mate"
    assert get_nested(example_data, "config.llm_endpoint.slug") == "test-slug"
    assert get_nested(example_data, "config.llm_endpoint.app.slug") == "app-slug"
    assert get_nested(example_data, "nonexistent") is None
    assert get_nested(example_data, "config.nonexistent") is None

    assert get_nested(complex_data, "id") == 2
    assert get_nested(complex_data, "another") == "value"
    assert get_nested(complex_data, "profile.details.info.username") == "complex_user"
    assert get_nested(complex_data, "profile.details.info.settings.theme") == "dark"
    assert get_nested(complex_data, "profile.details.info.nonexistent") is None

    print("All tests passed!")

if __name__ == "__main__":
    test_get_nested()