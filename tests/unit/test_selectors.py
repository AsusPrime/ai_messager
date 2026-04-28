from __future__ import annotations

from unittest.mock import MagicMock

from ai_messager.selectors.chatgpt import ChatGPTSelectors

_EXPECTED = {
    "composer",
    "send_button",
    "stop_button",
    "user_avatar",
    "login_button",
    "new_chat_link",
    "cloudflare_prompt",
    "assistant_turns",
    "turn_action_button",
}


def test_all_required_selector_methods_exist() -> None:
    actual = {
        name
        for name in dir(ChatGPTSelectors)
        if not name.startswith("_") and callable(getattr(ChatGPTSelectors, name))
    }
    missing = _EXPECTED - actual
    assert not missing, f"missing selector methods: {missing}"


def test_composer_uses_textbox_role() -> None:
    page = MagicMock()
    ChatGPTSelectors.composer(page)
    page.get_by_role.assert_called_with("textbox")


def test_assistant_turns_uses_data_message_author_role() -> None:
    # Invariant: extraction relies on [data-message-author-role="assistant"].
    # Changing this without updating the bridge breaks every reply.
    page = MagicMock()
    ChatGPTSelectors.assistant_turns(page)
    selector_arg = page.locator.call_args[0][0]
    assert "data-message-author-role" in selector_arg
    assert "assistant" in selector_arg


def test_cloudflare_prompt_is_iframe_based_not_text_based() -> None:
    # Regression guard for AP-03: earlier detector matched English text only
    # and missed localized CF challenges. Must go through page.locator
    # (iframe query), not page.get_by_text.
    page = MagicMock()
    ChatGPTSelectors.cloudflare_prompt(page)
    page.locator.assert_called()
    page.get_by_text.assert_not_called()


def test_stop_button_uses_testid() -> None:
    page = MagicMock()
    ChatGPTSelectors.stop_button(page)
    page.get_by_test_id.assert_called_with("stop-button")


def test_send_button_uses_testid() -> None:
    page = MagicMock()
    ChatGPTSelectors.send_button(page)
    page.get_by_test_id.assert_called_with("send-button")


def test_turn_action_button_targets_post_stream_testids() -> None:
    # Invariant: end-of-generation detection in the bridge relies on
    # ChatGPT's per-turn action buttons (Copy / Good response / etc.)
    # being suffixed with "-turn-action-button". If this naming changes,
    # the primary signal silently falls back to text-stability and
    # responses get truncated again.
    turn = MagicMock()
    ChatGPTSelectors.turn_action_button(turn)
    selector_arg = turn.locator.call_args[0][0]
    assert "turn-action-button" in selector_arg
