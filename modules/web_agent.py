"""
Web Agent — zero-cost browser automation via Playwright + keyword parsing.
No LLM calls. No screenshot-based AI loops. Just pattern matching and Playwright actions.
"""

import re
import json
import base64
import logging
import asyncio
from urllib.parse import quote_plus, urlparse
from typing import Optional

logger = logging.getLogger("web_agent")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

VIEWPORT = {"width": 1280, "height": 720}
NAV_TIMEOUT = 15000  # 15s in ms


def _result(success: bool, action: str, result: str, url: str = "") -> dict:
    return {"success": success, "action": action, "result": result, "url": url}


class WebAgent:
    """Headless Chromium browser agent driven by simple keyword instructions."""

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self._pw = None  # playwright context manager instance
        self._pw_obj = None  # the actual playwright object
        logger.info("[WebAgent] Initialized (browser not yet launched)")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Launch headless Chromium and open a blank page."""
        from playwright.async_api import async_playwright

        self._pw = async_playwright()
        self._pw_obj = await self._pw.start()
        self.browser = await self._pw_obj.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        self.context.set_default_navigation_timeout(NAV_TIMEOUT)
        self.context.set_default_timeout(NAV_TIMEOUT)
        self.page = await self.context.new_page()
        logger.info("[WebAgent] Browser started (headless Chromium)")

    async def stop(self):
        """Close browser and release resources."""
        try:
            if self.browser:
                await self.browser.close()
            if self._pw_obj:
                await self._pw_obj.stop()
        except Exception as e:
            logger.warning("[WebAgent] Error during shutdown: %s", e)
        finally:
            self.browser = None
            self.context = None
            self.page = None
            self._pw = None
            self._pw_obj = None
            logger.info("[WebAgent] Browser stopped")

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes:
        """Take a PNG screenshot of the current page."""
        if not self.page:
            raise RuntimeError("[WebAgent] Browser not started")
        return await self.page.screenshot(type="png", full_page=False)

    async def get_page_text(self) -> str:
        """Return visible text content of the current page (trimmed)."""
        if not self.page:
            raise RuntimeError("[WebAgent] Browser not started")
        text = await self.page.inner_text("body")
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        # Cap at ~8000 chars to stay reasonable for voice readback
        if len(text) > 8000:
            text = text[:8000] + "\n...[truncated]"
        return text

    # ------------------------------------------------------------------
    # Instruction parser + executor
    # ------------------------------------------------------------------

    async def execute(self, instruction: str) -> dict:
        """Parse a natural-language instruction and execute it via Playwright.

        Returns dict: {success, action, result, url}
        """
        if not self.page:
            await self.start()

        inst = instruction.strip()
        inst_lower = inst.lower()
        logger.info("[WebAgent] execute: %s", inst)

        try:
            # --- Navigation ---------------------------------------------------
            nav_match = re.match(
                r"(?:go\s+to|open|navigate\s+to|visit)\s+(.+)", inst_lower
            )
            if nav_match:
                url = nav_match.group(1).strip().strip("'\"")
                url = self._normalise_url(url)
                await self.page.goto(url, wait_until="domcontentloaded")
                title = await self.page.title()
                logger.info("[WebAgent] Navigated to %s", url)
                return _result(True, "navigate", f"Opened {title}", self.page.url)

            # --- Search / Google ----------------------------------------------
            search_match = re.match(
                r"(?:search|search\s+for|google|look\s+up|find)\s+(.+)", inst_lower
            )
            if search_match:
                query = search_match.group(1).strip().strip("'\"")
                url = f"https://www.google.com/search?q={quote_plus(query)}"
                await self.page.goto(url, wait_until="domcontentloaded")
                text = await self.get_page_text()
                # Return first ~2000 chars of results
                snippet = text[:2000]
                logger.info("[WebAgent] Searched: %s", query)
                return _result(True, "search", snippet, self.page.url)

            # --- Click --------------------------------------------------------
            click_match = re.match(r"click\s+(?:on\s+)?(.+)", inst_lower)
            if click_match:
                target = click_match.group(1).strip().strip("'\"")
                return await self._do_click(target)

            # --- Type / fill --------------------------------------------------
            type_match = re.match(
                r"type\s+['\"]?(.+?)['\"]?\s+in(?:to)?\s+(.+)", inst_lower
            )
            if type_match:
                text_val = type_match.group(1).strip()
                field = type_match.group(2).strip().strip("'\"")
                return await self._do_type(text_val, field)

            # --- Scroll -------------------------------------------------------
            if re.match(r"scroll\s+down", inst_lower):
                await self.page.mouse.wheel(0, 600)
                logger.info("[WebAgent] Scrolled down")
                return _result(True, "scroll_down", "Scrolled down", self.page.url)

            if re.match(r"scroll\s+up", inst_lower):
                await self.page.mouse.wheel(0, -600)
                logger.info("[WebAgent] Scrolled up")
                return _result(True, "scroll_up", "Scrolled up", self.page.url)

            # --- Back / Forward -----------------------------------------------
            if inst_lower in ("back", "go back"):
                await self.page.go_back(wait_until="domcontentloaded")
                logger.info("[WebAgent] Went back")
                return _result(True, "back", "Went back", self.page.url)

            if inst_lower in ("forward", "go forward"):
                await self.page.go_forward(wait_until="domcontentloaded")
                logger.info("[WebAgent] Went forward")
                return _result(True, "forward", "Went forward", self.page.url)

            # --- Read / extract text ------------------------------------------
            if re.match(r"(?:read|get\s+text|extract|get\s+content|read\s+page)", inst_lower):
                text = await self.get_page_text()
                logger.info("[WebAgent] Read page text (%d chars)", len(text))
                return _result(True, "read", text, self.page.url)

            # --- Screenshot ---------------------------------------------------
            if "screenshot" in inst_lower:
                png = await self.screenshot()
                b64 = base64.b64encode(png).decode()
                logger.info("[WebAgent] Screenshot taken (%d bytes)", len(png))
                return _result(True, "screenshot", b64, self.page.url)

            # --- Unrecognised -------------------------------------------------
            text = await self.get_page_text()
            logger.warning("[WebAgent] Unrecognised instruction: %s", inst)
            return _result(
                False,
                "unknown",
                f"Command not understood: '{inst}'. Current page text:\n{text[:2000]}",
                self.page.url,
            )

        except Exception as e:
            logger.error("[WebAgent] Error executing '%s': %s", inst, e)
            url = self.page.url if self.page else ""
            return _result(False, "error", str(e), url)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_url(raw: str) -> str:
        """Ensure a URL has a scheme."""
        raw = raw.strip()
        if not re.match(r"https?://", raw):
            raw = "https://" + raw
        return raw

    async def _do_click(self, target: str) -> dict:
        """Find an element by visible text and click it."""
        # Try exact text match first, then partial
        for selector in [
            f"text=\"{target}\"",
            f"text=/{re.escape(target)}/i",
            f"a:has-text(\"{target}\")",
            f"button:has-text(\"{target}\")",
            f"[aria-label=\"{target}\"]",
            f"[title=\"{target}\"]",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=5000)
                    await self.page.wait_for_load_state("domcontentloaded")
                    logger.info("[WebAgent] Clicked: %s", target)
                    return _result(True, "click", f"Clicked '{target}'", self.page.url)
            except Exception:
                continue

        logger.warning("[WebAgent] Could not find clickable element: %s", target)
        return _result(False, "click", f"Could not find element with text '{target}'", self.page.url)

    async def _do_type(self, text: str, field: str) -> dict:
        """Find an input by label/placeholder/name and type into it."""
        for selector in [
            f"input[placeholder*=\"{field}\" i]",
            f"textarea[placeholder*=\"{field}\" i]",
            f"input[name*=\"{field}\" i]",
            f"textarea[name*=\"{field}\" i]",
            f"input[aria-label*=\"{field}\" i]",
            f"label:has-text(\"{field}\") >> input",
            f"label:has-text(\"{field}\") >> textarea",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    await loc.fill(text)
                    logger.info("[WebAgent] Typed '%s' into '%s'", text, field)
                    return _result(True, "type", f"Typed '{text}' into '{field}'", self.page.url)
            except Exception:
                continue

        logger.warning("[WebAgent] Could not find input field: %s", field)
        return _result(False, "type", f"Could not find input field '{field}'", self.page.url)


# ----------------------------------------------------------------------
# Quick self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def _test():
        agent = WebAgent()
        await agent.start()
        try:
            r = await agent.execute("search Python playwright tutorial")
            print(json.dumps({k: v[:120] if isinstance(v, str) else v for k, v in r.items()}, indent=2))

            r = await agent.execute("scroll down")
            print(json.dumps(r, indent=2))

            r = await agent.execute("read")
            print(f"Page text length: {len(r['result'])}")
        finally:
            await agent.stop()

    asyncio.run(_test())
