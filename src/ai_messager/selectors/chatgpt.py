from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class ChatGPTSelectors:
    """One place to update if ChatGPT reshuffles its DOM.

    Prefer ARIA roles / data-testid — they survive class-name churn better.
    """

    @staticmethod
    def composer(page: Page) -> Locator:
        """Prompt textarea. ChatGPT renders it as a contenteditable with role=textbox."""
        return page.get_by_role("textbox").first

    @staticmethod
    def send_button(page: Page) -> Locator:
        return page.get_by_test_id("send-button")

    @staticmethod
    def stop_button(page: Page) -> Locator:
        return page.get_by_test_id("stop-button")

    @staticmethod
    def user_avatar(page: Page) -> Locator:
        """Top-right user/profile button — only present when logged in."""
        return page.get_by_test_id("profile-button")

    @staticmethod
    def login_button(page: Page) -> Locator:
        """Match both <button> and <a> variants of 'Log in' that ChatGPT uses."""
        as_button = page.get_by_role(
            "button", name=re.compile(r"log\s*in", re.IGNORECASE)
        )
        as_link = page.get_by_role("link", name=re.compile(r"log\s*in", re.IGNORECASE))
        return as_button.or_(as_link).first

    @staticmethod
    def new_chat_link(page: Page) -> Locator:
        return page.get_by_role("link", name=re.compile(r"New chat", re.IGNORECASE))

    @staticmethod
    def cloudflare_prompt(page: Page) -> Locator:
        """Detect Cloudflare Turnstile regardless of page language.

        The challenge widget is always served from challenges.cloudflare.com in an
        iframe — the URL is language-independent, unlike the "Verify you are human"
        text which is localized.
        """
        by_iframe = page.locator('iframe[src*="challenges.cloudflare.com"]')
        by_title = page.locator('iframe[title*="Cloudflare" i]')
        return by_iframe.or_(by_title).first

    @staticmethod
    def assistant_turns(page: Page) -> Locator:
        return page.locator('[data-message-author-role="assistant"]')

    @staticmethod
    def turn_action_button(turn: Locator) -> Locator:
        # Per-turn buttons (Copy / Good response / Bad response / ...) are
        # deferred-rendered AFTER ChatGPT finishes streaming — their
        # appearance is the most reliable end-of-generation signal.
        #
        # ChatGPT now mounts these buttons inside the parent
        # <section data-testid="conversation-turn-N"> as a sibling subtree
        # of the [data-message-author-role="assistant"] div we anchor
        # `turn` to, NOT as descendants of it. Walk up to the nearest
        # conversation-turn ancestor (or `turn` itself if it already is
        # one), then search descendants for the buttons.
        return (
            turn.locator(
                'xpath=ancestor-or-self::*[starts-with(@data-testid,"conversation-turn-")][1]'
            )
            .locator('[data-testid$="-turn-action-button"]')
            .first
        )
