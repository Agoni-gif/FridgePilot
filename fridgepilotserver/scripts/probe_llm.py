import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.common.config import get_settings
from app.providers.llm import LLMProvider
from app.providers.tavily import TavilyProvider
from app.agent.prompts import PARSE_SYSTEM, SUMMARIZE_SYSTEM
from app.agent.search_filter import filter_search_results
from app.schemas.recipe import UserConstraints


async def main() -> None:
    settings = get_settings()
    llm = LLMProvider(settings)
    tavily = TavilyProvider(settings)

    parsed = await llm.chat_json(
        system=PARSE_SYSTEM,
        user="用户输入：我有鸡蛋、番茄和葱，想做20分钟内的晚饭\n用户偏好：max_time_minutes=20, servings=2, dietary_restrictions=['不吃辣']",
    )
    print("parsed ok", json.dumps(parsed, ensure_ascii=False)[:300])
    constraints = UserConstraints.model_validate(parsed)

    results = []
    for q in (constraints.search_queries or ["番茄 鸡蛋 菜谱"])[:2]:
        results.extend(await tavily.search(q))
    filtered = filter_search_results(
        results,
        ingredients=[i.name for i in constraints.ingredients],
        max_results=settings.max_search_results,
    )
    print("search count", len(filtered))

    payload = {
        "constraints": constraints.model_dump(),
        "search_results": [r.model_dump() for r in filtered],
    }
    try:
        summarized = await llm.chat_json(
            system=SUMMARIZE_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
        )
        print("summarize ok", json.dumps(summarized, ensure_ascii=False)[:400])
    except Exception as exc:
        print("summarize failed", exc)


if __name__ == "__main__":
    asyncio.run(main())
