# backend/tests/test_result_pictures.py
#
# Search-result pictures as videos.generate inputs: exact ref binding, owner-checked
# lookup through indexed search parents, and the full-size public picture limits.
# No network: the cache reader and the HTTP fetch are stubbed.

import hashlib
import uuid
from io import BytesIO

import pytest
from PIL import Image

from backend.shared.python_utils import public_images, result_pictures as rp

OWNER = hashlib.sha256(b"user-1").hexdigest()


def _png(width, height, mode="RGB"):
    out = BytesIO()
    Image.new(mode, (width, height), "red").save(out, format="PNG")
    return out.getvalue()


def _reader(rows):
    async def read(embed_id):
        return rows.get(embed_id)
    return read


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_same_turn_refs_bind_only_with_one_child_per_result():
    children = [str(uuid.uuid4()), str(uuid.uuid4())]
    results = [{"embed_ref": "photo-1"}, {"embed_ref": "photo-2"}]
    index = rp.collect_result_ref_index(app_id="images", skill_id="search", results=results,
                                        authored_embeds=[{"status": "finished", "child_embed_ids": children}])
    assert index == {"photo-1": children[0], "photo-2": children[1]}
    assert rp.collect_result_ref_index(app_id="images", skill_id="search", results=results,
                                       authored_embeds=[{"child_embed_ids": children[:1]}]) == {}
    assert rp.collect_result_ref_index(app_id="maps", skill_id="search", results=results,
                                       authored_embeds=[{"child_embed_ids": children}]) == {}


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_earlier_results_resolve_by_exact_ref_and_owner():
    parent, mine, foreign = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    rows = {
        parent: ({"hashed_user_id": OWNER}, {"app_id": "news", "skill_id": "search",
                                             "embed_ids": f"{mine}|{foreign}"}),
        mine: ({"hashed_user_id": OWNER}, {"embed_ref": "headline-1"}),
        foreign: ({"hashed_user_id": "someone-else"}, {"embed_ref": "headline-2"}),
    }
    found = await rp.resolve_result_refs(["headline-1", "headline-2", "headline-3"], {"news-search-1": parent},
                                         read_content=_reader(rows), owner_hash=OWNER)
    assert found == {"headline-1": mine}


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_read_result_picture_carries_title_and_fails_explicitly():
    embed = str(uuid.uuid4())
    rows = {embed: ({"hashed_user_id": OWNER}, {"title": "  Rocket   launch ", "thumbnail": {
        "original": "https://images.example.org/rocket.jpg"}})}
    picture = await rp.read_result_picture(embed, read_content=_reader(rows), owner_hash=OWNER)
    assert (picture.url, picture.title) == ("https://images.example.org/rocket.jpg", "Rocket launch")
    with pytest.raises(rp.ResultPictureUnavailable):
        await rp.read_result_picture(str(uuid.uuid4()), read_content=_reader(rows), owner_hash=OWNER)
    rows[embed] = ({"hashed_user_id": OWNER}, {"title": "no picture", "image_url": "http://insecure.example.org/a"})
    with pytest.raises(rp.ResultPictureUnavailable):
        await rp.read_result_picture(embed, read_content=_reader(rows), owner_hash=OWNER)


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_full_image_keeps_size_up_to_2560_and_alpha():
    small = public_images.prepare_full_image(_png(1200, 800))
    assert (small.width, small.height, small.mime_type) == (1200, 800, "image/jpeg")
    large = public_images.prepare_full_image(_png(5120, 2560))
    assert (large.width, large.height) == (2560, 1280)
    assert public_images.prepare_full_image(_png(40, 40, "RGBA")).mime_type == "image/png"
    with pytest.raises(ValueError):
        public_images.prepare_full_image(b"x" * (public_images.MAX_FULL_SOURCE_BYTES + 1))


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_full_download_uses_the_20_mb_budget(monkeypatch):
    seen = {}

    async def fake_fetch(url, *, max_bytes, timeout):
        seen.update(url=url, max_bytes=max_bytes)
        return _png(300, 200)

    monkeypatch.setattr(public_images, "_fetch_public_image_bytes", fake_fetch)
    full = await public_images.download_public_image_full("https://images.example.org/a.png")
    assert seen["max_bytes"] == 20 * 1024 * 1024 and (full.width, full.height) == (300, 200)


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_fetch_refuses_non_https_before_any_connection():
    with pytest.raises(ValueError):
        await public_images.download_public_image_full("http://images.example.org/a.png")
