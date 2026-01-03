"""
Luffy Agent-based autoposting service.

Handles invalid JSON, empty plans, retries LLM requests, and always ensures
a tweet is posted in Monkey D. Luffy style.
"""

import json
import logging
import time
import random
import re
from typing import Any

from services.database import Database
from services.llm import LLMClient
from services.twitter import TwitterClient
from tools.registry import TOOLS, get_tools_description
from config.personality import SYSTEM_PROMPT
from config.prompts.agent_autopost import AUTOPOST_AGENT_PROMPT
from config.schemas import PLAN_SCHEMA, POST_TEXT_SCHEMA, TOOL_REACTION_SCHEMA

logger = logging.getLogger(__name__)

FALLBACK_TWEETS = [
    "Dream big and chase your freedom! Nothing can stop a determined heart! 🏴‍☠️💪",
    "Adventure waits beyond the horizon. Keep sailing toward your dreams! 🌊☀️",
    "Friends are your true treasure. Stick together and never give up! ❤️🏴‍☠️",
    "Even if the world says 'be realistic', keep following your own path! 🌟",
    "A pirate's spirit never fades. Stand tall and laugh in the face of danger! ☠️😄",
    "No storm can break someone with a will to live freely! 🌪️✊",
    "Eat, fight, laugh, and live fully—freedom is worth everything! 🍖⚡"
]

MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds, will increase exponentially

def get_agent_system_prompt() -> str:
    tools_desc = get_tools_description()
    return AUTOPOST_AGENT_PROMPT.format(tools_desc=tools_desc)


class AutoPostService:
    """Luffy-style agent-based autoposting service."""

    def __init__(self, db: Database, tier_manager=None):
        self.db = db
        self.llm = LLMClient()
        self.twitter = TwitterClient()
        self.tier_manager = tier_manager

    async def _llm_chat_retry(self, messages, schema) -> Any:
        """Call LLM with retries on failure."""
        attempt = 0
        delay = RETRY_DELAY
        while attempt < MAX_RETRIES:
            try:
                return await self.llm.chat(messages, schema)
            except Exception as e:
                attempt += 1
                logger.warning(f"[LLM RETRY] Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt >= MAX_RETRIES:
                    logger.error("[LLM RETRY] Max attempts reached. Raising exception.")
                    raise
                await asyncio.sleep(delay)
                delay *= 2  # exponential backoff

    def _sanitize_plan(self, plan: list[dict]) -> list[dict]:
        if not isinstance(plan, list):
            return []

        sanitized = []
        has_image = False

        for step in plan:
            if not isinstance(step, dict):
                continue
            tool_name = step.get("tool")
            params = step.get("params", {})

            if tool_name not in TOOLS:
                continue

            if tool_name == "generate_image":
                if has_image:
                    continue
                has_image = True

            sanitized.append({"tool": tool_name, "params": params})
            if len(sanitized) >= 3:
                break

        image_steps = [s for s in sanitized if s["tool"] == "generate_image"]
        non_image_steps = [s for s in sanitized if s["tool"] != "generate_image"]
        return non_image_steps + image_steps[:1]

    def _parse_json_safe(self, raw: str) -> dict:
        """Safely parse a string into JSON."""
        if not raw:
            return {}

        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    return {}
        return {}

    def _extract_tweet(self, text: str) -> str:
        """Extract tweet text from plain LLM output."""
        if not text:
            return ""
        cleaned = re.sub(r"^```.*?```", "", text, flags=re.DOTALL).strip()
        cleaned = re.sub(r"\*\*|__|\*|_", "", cleaned)
        match = re.search(r'"(.*?)"', cleaned, re.DOTALL)
        if match:
            return match.group(1).strip()
        return cleaned.strip()

    async def run(self) -> dict[str, Any]:
        import asyncio  # needed for retry sleep
        start_time = time.time()
        logger.info("[AUTOPOST] === Starting ===")

        try:
            if self.tier_manager:
                can_post, reason = self.tier_manager.can_post()
                if not can_post:
                    return {"success": False, "error": reason}

            previous_posts = await self.db.get_recent_posts_formatted(limit=50)
            system_prompt = SYSTEM_PROMPT + get_agent_system_prompt()

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Create a Twitter post in Monkey D. Luffy style. Previous posts (don't repeat):

{previous_posts}

Now create your plan. What tools do you need (if any)?"""}
            ]

            plan_result_raw = await self._llm_chat_retry(messages, PLAN_SCHEMA)
            logger.debug(f"[AUTOPOST] Raw LLM plan response: {plan_result_raw}")

            plan_result = plan_result_raw if isinstance(plan_result_raw, dict) else self._parse_json_safe(plan_result_raw)
            raw_plan = plan_result.get("plan", [])
            plan = self._sanitize_plan(raw_plan)

            # --- EXECUTE TOOLS ---
            image_bytes = None
            tools_used = []
            for step in plan:
                tool_name = step["tool"]
                params = step["params"]
                tools_used.append(tool_name)

                if tool_name == "web_search":
                    query = params.get("query", "")
                    result = await TOOLS[tool_name](query)
                    messages.append({"role": "user", "content": f"Tool result (web_search): {result.get('content', '')}"})

                elif tool_name == "generate_image":
                    try:
                        prompt = params.get("prompt", "")
                        image_bytes = await TOOLS[tool_name](prompt)
                        messages.append({"role": "user", "content": "Tool result (generate_image): completed"})
                    except Exception:
                        image_bytes = None

                reaction_raw = await self._llm_chat_retry(messages, TOOL_REACTION_SCHEMA)
                reaction = reaction_raw if isinstance(reaction_raw, dict) else self._parse_json_safe(reaction_raw)
                messages.append({"role": "assistant", "content": reaction.get("thinking", "")})

            # --- GENERATE FINAL TWEET ---
            messages.append({"role": "user", "content": "Write your final tweet in Luffy style (max 280 chars)."})
            post_result_raw = await self._llm_chat_retry(messages, POST_TEXT_SCHEMA)

            post_text = ""
            if isinstance(post_result_raw, dict):
                post_text = post_result_raw.get("post_text") or post_result_raw.get("post") or ""
            elif isinstance(post_result_raw, str):
                post_json = self._parse_json_safe(post_result_raw)
                post_text = post_json.get("post_text") or post_json.get("post") or self._extract_tweet(post_result_raw)

            post_text = post_text.strip()[:280]
            if not post_text:
                post_text = random.choice(FALLBACK_TWEETS)[:280]
                logger.info("[AUTOPOST] Using fallback Luffy tweet.")

            media_ids = None
            if image_bytes:
                try:
                    media_id = await self.twitter.upload_media(image_bytes)
                    media_ids = [media_id]
                except Exception:
                    image_bytes = None

            tweet_data = await self.twitter.post(post_text, media_ids=media_ids)
            await self.db.save_post(post_text, tweet_data["id"], image_bytes is not None)

            duration = round(time.time() - start_time, 1)
            logger.info(f"[AUTOPOST] === Completed in {duration}s ===")

            return {
                "success": True,
                "tweet_id": tweet_data["id"],
                "text": post_text,
                "tools_used": tools_used,
                "has_image": image_bytes is not None,
                "duration_seconds": duration
            }

        except Exception as e:
            duration = round(time.time() - start_time, 1)
            logger.error(f"[AUTOPOST] === FAILED after {duration}s ===")
            logger.exception(e)

            fallback_text = random.choice(FALLBACK_TWEETS)[:280]
            try:
                tweet_data = await self.twitter.post(fallback_text)
                await self.db.save_post(fallback_text, tweet_data["id"], False)
            except Exception as e2:
                logger.error(f"[AUTOPOST] Failed to post fallback: {e2}")

            return {"success": False, "error": str(e), "duration_seconds": duration, "fallback_posted": True}
