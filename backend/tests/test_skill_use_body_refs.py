"""An assistant answer body references only result embeds, never a skill-use embed."""

from __future__ import annotations

from backend.shared.python_utils.generated_media_graph import (
    authenticated_generated_outputs,
    finalize_trusted_inline_refs,
    generated_media_embed_ref,
    generated_media_parent_ref,
)
from backend.shared.python_utils.skill_use_body_refs import (
    is_skill_use_content,
    remove_skill_use_body_refs,
)

PARENT_ID = "018f8888-8888-7888-8888-888888888888"
FIRST_ID = "018f9999-9999-7999-8999-999999999999"
SECOND_ID = "018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
PARENT_REF = generated_media_parent_ref("images", PARENT_ID)
FIRST_REF = generated_media_embed_ref("images", FIRST_ID)
SECOND_REF = generated_media_embed_ref("images", SECOND_ID)
CHILDREN = {PARENT_REF: [FIRST_REF, SECOND_REF]}


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_parent_card_is_removed_and_a_referenced_child_card_is_kept():
    answer = f"Here are your images.\n\n[!](embed:{PARENT_REF})\n[!](embed:{FIRST_REF})\n[!](embed:{SECOND_REF})\n"
    result, removed = remove_skill_use_body_refs(answer, CHILDREN)
    assert removed == 1
    assert PARENT_REF not in result
    assert result == f"Here are your images.\n\n[!](embed:{FIRST_REF})\n[!](embed:{SECOND_REF})\n"


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_parent_only_answer_gets_its_child_cards_in_its_place():
    answer = f"I made two versions.\n\n[!](embed:{PARENT_REF})\n\nWant changes?"
    result, removed = remove_skill_use_body_refs(answer, CHILDREN)
    assert removed == 1
    assert result == (
        f"I made two versions.\n\n[!](embed:{FIRST_REF})\n[!](embed:{SECOND_REF})\n\nWant changes?"
    )
    # Only the children not already in the answer are added.
    partial = f"[!](embed:{PARENT_REF})\n[!](embed:{SECOND_REF})"
    assert remove_skill_use_body_refs(partial, CHILDREN)[0] == (
        f"[!](embed:{FIRST_REF})\n[!](embed:{SECOND_REF})"
    )


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_inline_parent_link_keeps_its_text_as_plain_prose():
    answer = f"See [the image set](embed:{PARENT_REF}) and [the first one](embed:{FIRST_REF})."
    result, removed = remove_skill_use_body_refs(answer, CHILDREN)
    assert removed == 1
    # The second child is not referenced yet, so it follows as its own card.
    assert result == (
        f"See the image set and [the first one](embed:{FIRST_REF}).\n\n[!](embed:{SECOND_REF})"
    )
    # A parent ref is recognised by its form even without a known child list.
    assert remove_skill_use_body_refs(f"A [set](embed:{PARENT_REF}) here.")[0] == "A set here."


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_generic_app_skill_use_ref_is_removed_and_results_take_its_place():
    search_ref = "web-search-k8D"
    results = ["wikipedia.org-a1B", "example.org-c2D"]
    answer = (
        f"I searched the web [here](embed:{search_ref}).\n"
        f"[](embed:{search_ref})\n"
        f"According to [Wikipedia](embed:wikipedia.org-a1B), it is tall."
    )
    result, removed = remove_skill_use_body_refs(answer, {search_ref: results})
    assert removed == 2
    assert search_ref not in result
    assert result == (
        "I searched the web here.\n\n"
        "[!](embed:example.org-c2D)\n"
        "According to [Wikipedia](embed:wikipedia.org-a1B), it is tall."
    )
    assert is_skill_use_content({"app_id": "web", "skill_id": "search", "result_count": 2,
                                 "embed_ids": ["a", "b"], "embed_ref": search_ref})
    assert is_skill_use_content({"type": "app_skill_use", "embed_ref": search_ref})
    # A result that records its producing skill is still a result.
    assert not is_skill_use_content({"type": "code", "app_id": "code", "skill_id": "image_to_html"})
    assert not is_skill_use_content({"app_id": "code", "skill_id": "image_to_html", "code": "<html>"})
    assert not is_skill_use_content({"type": "generated_image", "app_id": "images", "skill_id": "generated_image"})


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_result_refs_code_and_container_blocks_are_untouched():
    answer = (
        f"[Wikipedia](embed:wikipedia.org-a1B) and [!](embed:{FIRST_REF})\n"
        f"Inline code `[!](embed:{PARENT_REF})` stays.\n"
        "```json\n"
        f'{{"type": "app_skill_use", "embed_id": "{PARENT_ID}", "embed_ref": "{PARENT_REF}"}}\n'
        f"[!](embed:{PARENT_REF})\n"
        "```\n"
    )
    assert remove_skill_use_body_refs(answer, CHILDREN) == (answer, 0)


# contract-test: supporting surface=rest_api assertions=app-skills.answer.only-result-embeds-in-body
def test_parent_rows_never_gain_answer_authority_or_get_forced_inline():
    rows = [
        {"app_id": "images", "skill_id": "generate", "status": "finished",
         "embed_ref": FIRST_REF, "embed_id": FIRST_ID},
        # A row sealed before the result-only rule still names the parent.
        {"app_id": "images", "skill_id": "generate", "status": "finished",
         "embed_ref": PARENT_REF, "embed_id": PARENT_ID},
    ]
    assert set(authenticated_generated_outputs(rows)) == {FIRST_REF}
    finalized = finalize_trusted_inline_refs("Done.", rows, required_refs=[FIRST_REF, PARENT_REF])
    assert finalized == f"Done.\n\n[!](embed:{FIRST_REF})"
