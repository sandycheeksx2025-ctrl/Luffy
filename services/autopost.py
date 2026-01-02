"""
Luffy Agent-based autoposting service.

The agent creates a plan, executes tools step by step,
and generates the final post text in Monkey D. Luffy style.

All in one continuous conversation (user-assistant-user-assistant...).
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

# Fallback Luffy-style tweets
FALLBACK_TWEETS = [
    "Dream big and chase your freedom! Nothing can stop a determined heart! 🏴‍☠️💪",
    "Adventure waits beyond the horizon. Keep sailing toward your dreams! 🌊☀️",
    "Friends are your true treasure. Stick together and never give up! ❤️🏴‍☠️",
    "Even if the world says 'be realistic', keep following your own path! 🌟",
    "A pirate's spirit never fades. Stand tall and laugh in the face of danger! ☠️😄",
    "No storm can break someone with a will to live freely! 🌪️✊",
    "Eat, fight, laugh, and live fully—freedom is worth everything! 🍖⚡"
]


def get_agent_system_prompt() -> str:
    """
    Build agent system prompt with dynamic tools list.
    """
    tools_desc = get_tools_description()
    return AUTOPOST_AGENT_PROMPT.format(tools_desc=tools_desc)


class AutoPostService:
    """Luffy-style agent-based autoposting service."""

    def __init__(self, db: Database, tier_manager=None):
        self.db = db
        self.llm = LLMClient()
        self.twitter = TwitterClient()
        self.tier_manager = tier_manager

    def _sanitize_plan(self, plan: list[dict]) -> list[dict]:
        if not isinstance(plan, list):
            logger.warning("[AUTOPOST] Plan is not a list — stripping plan")
            return []

        sanitized = []
        has_image = False

        for step in plan:
            if not isinstance(step, dict):
                continue
            tool_name = step.get("tool")
            params = step.get("params", {})

            if tool_name not in TOOLS:
                logger.warning(f"[AUTOPOST] Unknown tool requested by agent: {tool_name} — skipping")
                continue

            if tool_name == "generate_image":
                if has_image:
                    logger.warning("[AUTOPOST] Multiple generate_image calls — skipping")
                    continue
                has_image = True

            sanitized.append({"tool": tool_name, "params": params})

            if len(sanitized) >= 3:
                logger.warning("[AUTOPOST] Plan exceeded max length — truncating")
                break

        image_steps = [s for s in sanitized if s["tool"] == "generate_image"]
        non_image_steps = [s for s in sanitized if s["tool"] != "generate_image"]

        final_plan = non_image_steps + image_steps[:1]
        logger.info(f"[AUTOPOST] Plan sanitized: {len(final_plan)} steps")
        return final_plan

    async def run(self) -> dict[str, Any]:
        start_time = time.time()
        logger.info("[AUTOPOST] === Starting ===")

        try:
            if self.tier_manager:
                can_post, reason = self.tier_manager.can_post()
                if not can_post:
                    logger.warning(f"[AUTOPOST] Blocked: {reason}")
                    return {
                        "success": False,
                        "error": f"posting_blocked: {reason}",
                        "tier": self.tier_manager.tier,
                        "usage_percent": self.tier_manager.get_usage_percent()
                    }

            logger.info("[AUTOPOST] [1/5] Loading context...")
            previous_posts = await self.db.get_recent_posts_formatted(limit=50)
            logger.info(f"[AUTOPOST] [1/5] Loaded {len(previous_posts)} chars of previous posts")

            system_prompt = SYSTEM_PROMPT + get_agent_system_prompt()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Create a Twitter post in Monkey D. Luffy style. Previous posts (don't repeat):

{previous_posts}

Now create your plan. What tools do you need (if any)?"""}
            ]

            logger.info("[AUTOPOST] [2/5] Creating plan - calling LLM...")
            plan_result_raw = await self.llm.chat(messages, PLAN_SCHEMA)

            plan_result = {}
            if isinstance(plan_result_raw, dict):
                plan_result = plan_result_raw
            elif isinstance(plan_result_raw, str):
                try:
                    plan_result = json.loads(plan_result_raw)
                except json.JSONDecodeError:
                    match = re.search(r"\{.*\}", plan_result_raw, re.DOTALL)
                    if match:
                        try:
                            plan_result = json.loads(match.group())
                        except Exception:
                            plan_result = {}

            raw_plan = plan_result.get("plan", [])
            reasoning = plan_result.get("reasoning", "")
            plan = self._sanitize_plan(raw_plan)

            tools_list = " -> ".join([s["tool"] for s in plan]) if plan else "none"
            logger.info(f"[AUTOPOST] [2/5] Plan: {len(plan)} tools ({tools_list})")
            logger.info(f"[AUTOPOST] [2/5] Reasoning: {reasoning[:100]}...")

            messages.append({"role": "assistant", "content": json.dumps(plan_result)})

            logger.info("[AUTOPOST] [3/5] Executing tools...")
            image_bytes = None
            tools_used = []

            for i, step in enumerate(plan):
                tool_name = step["tool"]
                params = step["params"]
                tools_used.append(tool_name)

                if tool_name == "web_search":
                    query = params.get("query", "")
                    result = await TOOLS[tool_name](query)
                    messages.append({"role": "user", "content": f"Tool result (web_search): {result.get('content', '')}"})

                elif tool_name == "generate_image":
                    prompt = params.get("prompt", "")
                    try:
                        image_bytes = await TOOLS[tool_name](prompt)
                        messages.append({"role": "user", "content": "Tool result (generate_image): completed"})
                    except Exception as e:
                        logger.error(f"[AUTOPOST] generate_image failed: {e}")
                        image_bytes = None

                reaction = await self.llm.chat(messages, TOOL_REACTION_SCHEMA)
                messages.append({"role": "assistant", "content": reaction.get("thinking", "")})

            logger.info("[AUTOPOST] [4/5] Generating tweet...")
            messages.append({"role": "user", "content": "Now write your final tweet text in Luffy style (max 280 characters). Just the tweet."})

            post_result_raw = await self.llm.chat(messages, POST_TEXT_SCHEMA)

            post_text = ""
            if isinstance(post_result_raw, dict):
                post_text = post_result_raw.get("post_text") or post_result_raw.get("post") or ""
            elif isinstance(post_result_raw, str):
                try:
                    post_json = json.loads(post_result_raw)
                    post_text = post_json.get("post_text") or post_json.get("post") or post_result_raw
                except json.JSONDecodeError:
                    post_text = post_result_raw

            post_text = post_text.strip()[:280]

            if not post_text:
                post_text = random.choice(FALLBACK_TWEETS)[:280]
                logger.info("[AUTOPOST] Using fallback Luffy tweet as LLM returned empty text.")

            logger.info(f"[AUTOPOST] Tweet ready ({len(post_text)} chars)")

            media_ids = None
            if image_bytes:
                try:
                    media_id = await self.twitter.upload_media(image_bytes)
                    media_ids = [media_id]
                except Exception as e:
                    logger.error(f"[AUTOPOST] Image upload failed: {e}")
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
            return {"success": False, "error": str(e), "duration_seconds": duration}
