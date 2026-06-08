"""Test that Copilot chat uses skill context in its prompts (not just API response fields).

This test verifies:
1. copilot._build_user_prompt injects skill context block
2. copilot._inject_skill_into_system modifies system prompt
3. copilot._rule_based_chat uses skill context for response tagging
"""

import sys
sys.path.insert(0, 'd:\\大模型\\IntelliOps')

from src.backend.copilot import (
    Copilot,
    _format_skill_context_for_user_prompt,
    _inject_skill_into_system,
    COPILOT_SYSTEM,
    COPILOT_USER_TEMPLATE,
)

def test_skill_context_injection():
    skill_context = {
        'active_skills': ['incident-diagnosis', 'log-analysis', 'script-operations'],
        'primary_skill': 'incident-diagnosis',
        'active_agents': [
            {'name': 'incident-diagnosis', 'display_name': '诊断 Agent', 'is_primary': True},
            {'name': 'log-analysis', 'display_name': '日志分析 Agent', 'is_primary': False},
        ],
        'route_intent': 'diagnose',
    }
    
    # Test 1: _format_skill_context_for_user_prompt
    print("=" * 60)
    print("Test 1: Skill context block for user prompt")
    print("=" * 60)
    block = _format_skill_context_for_user_prompt(skill_context)
    print(block)
    
    assert '激活的智能体' in block, "Should mention active agents"
    assert '诊断 Agent' in block, "Should mention primary agent"
    assert '★' in block, "Should mark primary agent"
    assert 'diagnose' in block, "Should show intent"
    print("✅ PASS\n")
    
    # Test 2: _inject_skill_into_system
    print("=" * 60)
    print("Test 2: System prompt injection")
    print("=" * 60)
    modified_system = _inject_skill_into_system(COPILOT_SYSTEM, skill_context)
    assert len(modified_system) > len(COPILOT_SYSTEM), "System prompt should grow with skill context"
    assert '激活的智能体' in modified_system, "Skill block should be in system prompt"
    print(f"Original system prompt: {len(COPILOT_SYSTEM)} chars")
    print(f"Modified system prompt: {len(modified_system)} chars")
    print("✅ PASS\n")
    
    # Test 3: _build_user_prompt with skill context
    print("=" * 60)
    print("Test 3: User prompt with skill context")
    print("=" * 60)
    diagnosis = {
        'diagnosis_id': 'diag-test',
        'incident_id': 'inc-test',
        'candidate_root_causes': [
            {'cause': 'DB连接池耗尽', 'confidence': 0.75, 'evidence_items': ['连接超时']}
        ],
        'log_analysis': {'summary': '发现大量timeout错误'},
        'conversation_history': [],
    }
    user_prompt = Copilot._build_user_prompt(
        diagnosis, "帮我分析一下延迟问题", [],
        skill_context=skill_context
    )
    assert '激活的智能体' in user_prompt, "User prompt should contain skill block"
    assert '诊断 Agent' in user_prompt, "Should mention primary agent"
    assert '★' in user_prompt, "Should mark primary agent"
    print(f"User prompt length: {len(user_prompt)} chars")
    print("✅ PASS\n")
    
    # Test 4: User prompt WITHOUT skill context (backward compat)
    print("=" * 60)
    print("Test 4: User prompt without skill context (backward compat)")
    print("=" * 60)
    user_prompt_no_skill = Copilot._build_user_prompt(
        diagnosis, "帮我分析", [], skill_context=None
    )
    assert '激活的智能体' not in user_prompt_no_skill, "Should NOT have skill block when no context"
    print(f"User prompt length (no skill): {len(user_prompt_no_skill)} chars")
    print("✅ PASS\n")
    
    # Test 5: _rule_based_chat with skill context
    print("=" * 60)
    print("Test 5: Rule-based chat with skill context")
    print("=" * 60)
    result = Copilot._rule_based_chat(
        diagnosis=diagnosis,
        user_message="日志里有很多timeout",
        action_logs=[],
        skill_context=skill_context,
    )
    assert 'response' in result, "Should have response"
    assert '[🔍 故障诊断]' in result['response'], f"Response should be tagged with skill name. Got: {result['response'][:80]}"
    print(f"Response: {result['response'][:120]}")
    print("✅ PASS\n")
    
    print("=" * 60)
    print("ALL TESTS PASSED — Skill context flows into Copilot prompts!")
    print("=" * 60)


if __name__ == '__main__':
    test_skill_context_injection()
