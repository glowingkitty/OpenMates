import pytest

def get_nested(dictionary, key_path, stop_at_last_key=False):
    if dictionary is None:
        return None

    if not isinstance(dictionary, dict):
        raise ValueError(f"dictionary must be a dictionary, but got: {type(dictionary)}")

    if not key_path:
        return dictionary

    keys = key_path.split('.')
    for i, key in enumerate(keys):
        while isinstance(dictionary, dict) and key not in dictionary:
            if "attributes" in dictionary:
                dictionary = dictionary["attributes"]
            elif "data" in dictionary:
                if isinstance(dictionary["data"], list) and dictionary["data"]:
                    dictionary = dictionary["data"][0]
                elif isinstance(dictionary["data"], dict) and dictionary["data"]:
                    dictionary = dictionary["data"]
                else:
                    return None
            else:
                return None

        if isinstance(dictionary, dict):
            if stop_at_last_key and i == len(keys) - 1:
                return dictionary.get(key)
            dictionary = dictionary.get(key)
        elif isinstance(dictionary, list):
            try:
                index = int(key)
                if 0 <= index < len(dictionary):
                    dictionary = dictionary[index]
                else:
                    return None
            except ValueError:
                return None
        else:
            return None

    # Automatically return the "data" if it's present in the final result
    if isinstance(dictionary, dict) and "data" in dictionary and isinstance(dictionary["data"], list):
        return dictionary["data"]

    return dictionary


@pytest.fixture
def sample_data():
    return {
    'data': [{
        'id': 1,
        'attributes': {
            'name': 'Transcript',
            'description': 'Transcribe a video.',
            'slug': 'transcript',
            'requires_cloud_to_run': True,
            'is_llm_endpoint': False,
            'is_llm_endpoint_and_supports_tool_selection': False,
            'icon': {
                'data': {
                    'id': 7,
                    'attributes': {
                        'createdAt': '2024-04-17T16:05:08.160Z',
                        'updatedAt': '2024-04-17T16:05:09.074Z',
                        'publishedAt': '2024-04-17T16:05:09.070Z',
                        'access_public': True,
                        'filename': 'transcript_651ca40516.png',
                        'file': {
                            'data': {
                                'id': 5,
                                'attributes': {
                                    'name': 'transcript.png',
                                    'alternativeText': None,
                                    'caption': None,
                                    'width': 389,
                                    'height': 389,
                                    'formats': {
                                        'thumbnail': {
                                            'ext': '.png',
                                            'url': '/uploads/thumbnail_transcript_651ca40516.png',
                                            'hash': 'thumbnail_transcript_651ca40516',
                                            'mime': 'image/png',
                                            'name': 'thumbnail_transcript.png',
                                            'path': None,
                                            'size': 9.68,
                                            'width': 156,
                                            'height': 156,
                                            'sizeInBytes': 9679
                                        }
                                    },
                                    'hash': 'transcript_651ca40516',
                                    'ext': '.png',
                                    'mime': 'image/png',
                                    'size': 15.73,
                                    'url': '/uploads/transcript_651ca40516.png',
                                    'previewUrl': None,
                                    'provider': 'local',
                                    'provider_metadata': None,
                                    'createdAt': '2024-04-11T14:08:46.546Z',
                                    'updatedAt': '2024-04-11T14:47:09.069Z'
                                }
                            }
                        }
                    }
                }
            },
            'software': {
                'data': {
                    'id': 1,
                    'attributes': {
                        'name': 'YouTube',
                        'slug': 'youtube',
                        'createdAt': '2024-04-11T14:08:16.127Z',
                        'updatedAt': '2024-04-17T16:06:25.298Z',
                        'publishedAt': '2024-04-11T14:26:49.078Z',
                        'icon': {
                            'data': {
                                'id': 5,
                                'attributes': {
                                    'createdAt': '2024-04-17T16:02:15.830Z',
                                    'updatedAt': '2024-04-17T16:02:42.963Z',
                                    'publishedAt': '2024-04-17T16:02:17.238Z',
                                    'access_public': True,
                                    'filename': 'youtube_501c194d2d.png',
                                    'file': {
                                        'data': {
                                            'id': 4,
                                            'attributes': {
                                                'name': 'youtube.png',
                                                'alternativeText': None,
                                                'caption': None,
                                                'width': 389,
                                                'height': 389,
                                                'formats': {
                                                    'thumbnail': {
                                                        'ext': '.png',
                                                        'url': '/uploads/thumbnail_youtube_501c194d2d.png',
                                                        'hash': 'thumbnail_youtube_501c194d2d',
                                                        'mime': 'image/png',
                                                        'name': 'thumbnail_youtube.png',
                                                        'path': None,
                                                        'size': 9.65,
                                                        'width': 156,
                                                        'height': 156,
                                                        'sizeInBytes': 9652
                                                    }
                                                },
                                                'hash': 'youtube_501c194d2d',
                                                'ext': '.png',
                                                'mime': 'image/png',
                                                'size': 13.2,
                                                'url': '/uploads/youtube_501c194d2d.png',
                                                'previewUrl': None,
                                                'provider': 'local',
                                                'provider_metadata': None,
                                                'createdAt': '2024-04-11T14:07:58.417Z',
                                                'updatedAt': '2024-04-11T14:47:21.640Z'
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
    }],
    'meta': {
        'pagination': {
            'page': 1,
            'pageSize': 25,
            'pageCount': 1,
            'total': 1
        }
    }
}

def test_get_nested(sample_data):
    assert get_nested(sample_data, "name") == "Transcript"
    assert get_nested(sample_data, "description") == "Transcribe a video."
    assert get_nested(sample_data, "slug") == "transcript"
    assert get_nested(sample_data, "requires_cloud_to_run") == True
    assert get_nested(sample_data, "is_llm_endpoint") == False
    assert get_nested(sample_data, "is_llm_endpoint_and_supports_tool_selection") == False
    assert get_nested(sample_data, "icon.file.url") == "/uploads/transcript_651ca40516.png"
    assert get_nested(sample_data, "software.id") == 1
    assert get_nested(sample_data, "software.name") == "YouTube"
    assert get_nested(sample_data, "software.icon.file.url") == "/uploads/youtube_501c194d2d.png"
    assert get_nested(sample_data, "software.slug") == "youtube"

def test_get_nested_nonexistent_key(sample_data):
    assert get_nested(sample_data, "nonexistent.key") is None

def test_get_nested_partial_path(sample_data):
    assert get_nested(sample_data, "software") == sample_data['data'][0]['attributes']['software']

def test_get_nested_empty_path(sample_data):
    assert get_nested(sample_data, "") == sample_data

def test_get_nested_none_input():
    assert get_nested(None, "any.path") is None

def test_get_nested_list_input():
    list_data = {'data': [{'attributes': {'items': [1, 2, 3]}}]}
    assert get_nested(list_data, "items.0") == 1
    assert get_nested(list_data, "items.3") is None