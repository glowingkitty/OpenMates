"""Diff edits whose hunk line numbers are far off while their lines match one place exactly."""

from backend.core.api.app.services.embed_diff_service import apply_patch, parse_unified_diff

SLIDES = "\n".join(
    ['<deck title="Robotics" kind="template">']
    + [
        line
        for index in range(1, 9)
        for line in (
            f'  <slide id="s{index}" layout="content">',
            f'    <text id="e{index}" x="140" y="140" w="1640" h="100" role="title" size="68">Slide {index}</text>',
            '  </slide>',
        )
    ]
    + ['</deck>']
)


# contract-test: supporting surface=rest_api assertions=slides.assistant.create-and-diff-edit
def test_hunk_with_wrong_line_numbers_applies_where_its_lines_occur_once() -> None:
    diff_text = (
        "@@ -2,3 +2,4 @@\n"
        '   <slide id="s7" layout="content">\n'
        '-    <text id="e7" x="140" y="140" w="1640" h="100" role="title" size="68">Slide 7</text>\n'
        '+    <text id="e7" x="140" y="140" w="1640" h="100" role="title" size="80">Slide 7</text>\n'
        '+    <shape id="e70" x="140" y="260" w="200" h="8" kind="rect" fill="accent"/>\n'
        "   </slide>\n"
    )
    result = apply_patch(SLIDES, parse_unified_diff(diff_text, "robotics"))
    assert result.success, result.error
    assert 'size="80">Slide 7</text>' in result.new_content
    assert 'size="68">Slide 6</text>' in result.new_content
    assert result.new_content.index('id="e70"') > result.new_content.index('id="e7"')


# contract-test: supporting surface=rest_api assertions=slides.assistant.create-and-diff-edit
def test_hunk_whose_lines_occur_more_than_once_is_not_guessed() -> None:
    diff_text = (
        "@@ -40,2 +40,3 @@\n"
        "   </slide>\n"
        '+  <slide id="extra" layout="closing"></slide>\n'
    )
    result = apply_patch(SLIDES, parse_unified_diff(diff_text, "robotics"))
    assert not result.success
    assert "Unique-context fallback expected one match" in result.error
