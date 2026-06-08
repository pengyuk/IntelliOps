"""Quick test for Skill system."""
import asyncio
import sys
sys.path.insert(0, 'd:\\大模型\\IntelliOps')

from src.backend.skill_loader import SkillLoader
from src.backend.skill_router import SkillRouter


async def test_router():
    loader = SkillLoader()
    await loader.load_all()
    router = SkillRouter(loader)
    
    queries = [
        "支付延迟，帮我诊断一下",
        "查看最近的错误日志",
        "执行一个重启脚本",
        "生成复盘报告",
        "查一下有没有类似的历史案例",
        "通知DBA一起排查",
    ]
    
    for q in queries:
        result = await router.classify_intent(q)
        print(f"Query: {q}")
        print(f"  Intent: {result.intent}")
        print(f"  Primary Skill: {result.primary_skill.name if result.primary_skill else 'N/A'}")
        print(f"  Confidence: {result.confidence:.2f}")
        if result.alternative_skills:
            print(f"  Alternatives: {[(s.name, f'{sc:.1f}') for s, sc in result.alternative_skills[:2]]}")
        print()


async def test_match():
    loader = SkillLoader()
    await loader.load_all()
    
    test_queries = [
        "支付延迟，帮我诊断一下",
        "日志里有大量timeout错误",
        "帮我写个脚本检查MQ队列",
        "写个复盘报告",
        "有没有类似的故障案例",
    ]
    
    for q in test_queries:
        matches = loader.match(q, top_k=3)
        print(f"Query: {q}")
        for skill, score in matches:
            print(f"  {skill.name}: {score:.1f}")
        print()


if __name__ == '__main__':
    print("=" * 60)
    print("TEST 1: SkillRouter Intent Classification")
    print("=" * 60)
    asyncio.run(test_router())
    
    print("=" * 60)
    print("TEST 2: SkillLoader Keyword Matching")
    print("=" * 60)
    asyncio.run(test_match())
    
    print("All tests passed!")
