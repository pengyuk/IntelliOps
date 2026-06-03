import json
import re
from typing import Any, Dict, List

from .llm_client import LLMClient

class IncidentReasoner:
    @staticmethod
    def _build_prompt(incident: Dict[str, Any], kg_context: Dict[str, List[Dict[str, Any]]]) -> str:
        prompt_lines = [
            '你是一个故障根因推理助手。根据下面的事件和知识图谱上下文，输出仅包含一个 JSON 对象，字段如下：',
            '- incident_id',
            '- candidate_root_causes (数组，包含 cause、confidence、detail)',
            '- reasoning_steps (数组)',
            '- evidence (数组)',
            '- confidence_summary (0-1 浮点数)',
            '不要输出任何额外文本。',
            '',
            '事件：',
            json.dumps(incident, ensure_ascii=False, indent=2),
            '',
            'KG 上下文：',
            json.dumps(kg_context, ensure_ascii=False, indent=2),
        ]
        return '\n'.join(prompt_lines)

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        json_text = None
        start = text.find('{')
        if start >= 0:
            brace_level = 0
            for i, ch in enumerate(text[start:], start=start):
                if ch == '{':
                    brace_level += 1
                elif ch == '}':
                    brace_level -= 1
                    if brace_level == 0:
                        json_text = text[start:i + 1]
                        break
        if json_text is None:
            raise ValueError('未能找到 JSON 对象')
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'JSON 解析失败: {exc}') from exc

    @staticmethod
    def _rule_based_fallback(incident: Dict[str, Any], kg_context: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        summary = incident.get('summary', '')
        related_alerts = incident.get('related_alerts', [])
        related_changes = incident.get('related_changes', [])
        affected_services = incident.get('affected_services', [])
        alert_nodes = kg_context.get('alerts', [])
        change_nodes = kg_context.get('changes', [])
        service_nodes = kg_context.get('services', [])

        candidate_root_causes = []
        evidence = []
        reasoning_steps = []

        if '延迟' in summary or '慢' in summary:
            candidate_root_causes.append({
                'cause': '服务响应延迟',
                'confidence': 0.78,
                'detail': '摘要包含延迟类描述，说明可能为服务性能或网络资源问题。'
            })
            reasoning_steps.append('识别故障现象为延迟/慢响应。')
            evidence.append('事件摘要包含延迟相关词语。')

        if related_alerts:
            alert_names = [node.get('name') for node in alert_nodes]
            candidate_root_causes.append({
                'cause': '监控告警触发的系统异常',
                'confidence': 0.65,
                'detail': f'检测到相关告警 {alert_names}，需要关联告警详情进行确认。'
            })
            reasoning_steps.append('关联告警记录，准备提取告警上下文。')
            evidence.append(f'相关告警：{alert_names}。')

        if related_changes:
            change_names = [node.get('name') for node in change_nodes]
            candidate_root_causes.append({
                'cause': '近期变更引发的配置或部署异常',
                'confidence': 0.72,
                'detail': f'发现相关变更 {change_names}，可能引起故障。'
            })
            reasoning_steps.append('检查相关变更记录，判断变更是否与当前故障相关。')
            evidence.append(f'关联变更：{change_names}。')

        if affected_services:
            service_names = [node.get('name') for node in service_nodes]
            candidate_root_causes.append({
                'cause': '核心服务相关依赖异常',
                'confidence': 0.7,
                'detail': f'受影响服务：{service_names}，可能涉及依赖链问题。'
            })
            reasoning_steps.append('分析受影响服务及其依赖链。')
            evidence.append(f'影响服务：{service_names}。')

        if not candidate_root_causes:
            candidate_root_causes.append({
                'cause': '未知根因，需要更多数据',
                'confidence': 0.45,
                'detail': '当前事件信息不足，需补充日志、性能指标和告警详情。'
            })
            reasoning_steps.append('根据现有事件信息，暂无法确定高置信度根因。')
            evidence.append('事件摘要、关联变更或告警信息不足。')

        return {
            'incident_id': incident.get('incident_id'),
            'candidate_root_causes': candidate_root_causes,
            'reasoning_steps': reasoning_steps,
            'evidence': evidence,
            'confidence_summary': round(sum([c['confidence'] for c in candidate_root_causes]) / len(candidate_root_causes), 2),
        }

    @staticmethod
    def infer_root_causes(incident: Dict[str, Any], kg_context: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        client = LLMClient()
        if client.provider in ('openai', 'anthropic'):
            prompt = IncidentReasoner._build_prompt(incident, kg_context)
            response = client.infer(prompt, metadata={'incident': incident, 'kg_context': kg_context})
            try:
                parsed = IncidentReasoner._extract_json(response.get('text', ''))
                if parsed.get('incident_id') is None:
                    parsed['incident_id'] = incident.get('incident_id')
                return parsed
            except ValueError:
                pass

        return IncidentReasoner._rule_based_fallback(incident, kg_context)
