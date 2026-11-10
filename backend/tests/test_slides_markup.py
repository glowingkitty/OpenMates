"""Slides markup normaliser (pure; no celery/toon dependencies)."""

import pytest

from backend.shared.python_utils.slides_markup import (
    SlidesMarkupError,
    normalise_slides_markup,
)

VALID = """<deck title="Q3 results" aspect="16:9" template="builtin:plain">
  <slide layout="title-and-content" transition="fade">
    <text role="title" x="80" y="60" w="1200" h="120">Q3 <b>results</b></text>
    <image src="embed:revenue-chart" x="1000" y="220" w="800" h="500" alt="Revenue chart"/>
    <video src="youtube:abc123xyz" x="80" y="220" w="860" h="484"/>
    <shape kind="rect" fill="accent" x="0" y="1000" w="1920" h="80"/>
    <notepad title="Ideas" x="80" y="740" w="860" h="260"/>
    <todo title="Next" x="1000" y="760" w="800" h="240"><item done="false">Book venue</item></todo>
    <notes>Speaker notes.</notes>
  </slide>
  <slide>
    <text role="title">Second</text>
  </slide>
</deck>"""

BLOCK_BODY = '<script>alert("kept")</script>\n  <div onclick="x()">raw & <b>html</b></div>\n'


# contract-test: direct surface=rest_api assertions=slides.format.positioned-elements
def test_valid_deck_is_normalised_with_stable_ids_and_is_idempotent() -> None:
    deck = normalise_slides_markup(VALID)
    assert (deck.title, deck.slide_count, deck.aspect) == ("Q3 results", 2, "16:9")
    assert '<slide id="s1" layout="title-and-content" transition="fade">' in deck.markup
    assert '<slide id="s2">' in deck.markup
    assert '<image id="e2" x="1000" y="220" w="800" h="500" src="embed:revenue-chart" alt="Revenue chart"/>' in deck.markup
    assert '<video id="e3"' in deck.markup and 'src="youtube:abc123xyz"' in deck.markup
    assert '<item done="false">Book venue</item>' in deck.markup
    assert normalise_slides_markup(deck.markup).markup == deck.markup


# contract-test: direct surface=rest_api assertions=slides.format.positioned-elements
def test_geometry_is_clamped_to_the_canvas_of_the_aspect() -> None:
    deck = normalise_slides_markup(
        '<deck aspect="4:3"><slide><shape kind="rect" x="1900" y="1400" w="900" h="900"/></slide></deck>'
    )
    assert deck.aspect == "4:3"
    assert 'x="1900" y="1400" w="20" h="40"' in deck.markup


# contract-test: direct surface=rest_api assertions=slides.security.host-rendered-and-isolated
def test_hostile_deck_is_cleaned() -> None:
    hostile = """<deck title="x">
      <slide onclick="steal()">
        <text role="title" onclick="steal()" style="x" data-x="1">Hi<script>evil()</script></text>
        <image src="https://evil.example/pixel.png" x="1" y="1" w="1" h="1"/>
        <image src="data:image/png;base64,AAAA"/>
        <script>alert(1)</script>
        <iframe src="https://evil.example"></iframe>
        <object data="x"></object>
        <marquee>unknown</marquee>
        <link href="javascript:alert(1)">bad</link>
        <link href="https://ok.example/page">ok</link>
        <video src="https://example.com/movie.mp4" x="5" y="5" w="50" h="50"/>
      </slide>
    </deck>"""
    markup = normalise_slides_markup(hostile).markup
    for forbidden in ("onclick", "script", "iframe", "<object", "evil", "style=", "data:", "javascript", "<image"):
        assert forbidden not in markup.lower(), forbidden
    assert "<marquee" not in markup
    assert '<link id=' in markup and 'href="https://ok.example/page">ok</link>' in markup
    assert 'href="https://example.com/movie.mp4"' in markup  # plain video address becomes a link
    assert "<video" not in markup


# contract-test: direct surface=rest_api assertions=slides.security.host-rendered-and-isolated
def test_block_content_is_preserved_byte_for_byte_and_attributes_cleaned() -> None:
    source = f'<deck><slide><block x="1" y="2" w="300" h="200" onclick="x()">{BLOCK_BODY}</block></slide></deck>'
    markup = normalise_slides_markup(source).markup
    assert f'<block id="e1" x="1" y="2" w="300" h="200">{BLOCK_BODY}</block>' in markup
    assert "onclick=\"x()\">" not in markup.split("<block", 1)[1].split(">", 1)[0]
    assert normalise_slides_markup(markup).markup == markup


# contract-test: direct surface=rest_api assertions=slides.format.positioned-elements
def test_empty_or_slideless_markup_is_rejected() -> None:
    with pytest.raises(SlidesMarkupError):
        normalise_slides_markup("   ")
    with pytest.raises(SlidesMarkupError):
        normalise_slides_markup("<deck><text>no slide</text></deck>")
