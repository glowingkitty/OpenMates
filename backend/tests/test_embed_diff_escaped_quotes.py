"""Diff edits whose lines carry quote escapes copied from the TOON form of a stored embed."""

from backend.core.api.app.services.embed_diff_service import apply_patch, parse_unified_diff

SLIDES_TEMPLATE = """<deck title="Bold energy" kind="template">
  <slide id="title" layout="title">
    <text id="e1" x="160" y="420" w="1200" h="120" role="title" size="72" color="ink">Title</text>
    <shape id="e2" x="160" y="680" w="120" h="6" kind="rect" fill="accent"/>
  </slide>
</deck>"""


# contract-test: supporting surface=rest_api assertions=slides.assistant.create-and-diff-edit
def test_escaped_quotes_copied_from_toon_still_apply() -> None:
    diff_text = (
        "@@ -5,2 +5,2 @@\n"
        '     <text id="e1" x="160" y="420" w="1200" h="120" role=\\"title\\" size=\\"72\\" color=\\"ink\\">Title</text>\n'
        '-    <shape id="e2" x="160" y="680" w="120" h="6" kind=\\"rect\\" fill=\\"accent\\"/>\n'
        '+    <shape id="e2" x="160" y="680" w="120" h="6" kind=\\"rect\\" fill=\\"warm\\"/>\n'
    )
    result = apply_patch(SLIDES_TEMPLATE, parse_unified_diff(diff_text, "bold-energy"))
    assert result.success, result.error
    assert 'kind="rect" fill="warm"/>' in result.new_content
    assert '\\"' not in result.new_content


# contract-test: supporting surface=rest_api assertions=slides.assistant.create-and-diff-edit
def test_content_with_real_escaped_quotes_is_not_rewritten() -> None:
    content = 'line one\nprint("say \\"hi\\"")\nline three'
    diff_text = (
        "@@ -2,1 +2,1 @@\n"
        '-print(\\"say hi\\")\n'
        '+print(\\"say bye\\")\n'
    )
    result = apply_patch(content, parse_unified_diff(diff_text, "script.py"))
    assert not result.success
    assert "Unescaped quotes" not in result.error
