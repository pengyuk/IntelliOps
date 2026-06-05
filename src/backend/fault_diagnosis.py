from typing import Any, Dict, List, Optional

from .alarm_analyze import AlarmAnalyzer


class FaultDiagnosisService:
    """Analyze alarm content, impact range, and recommend root-cause candidates."""

    @staticmethod
    def describe_severity(severity: int) -> str:
        if severity >= 4:
            return 'critical'
        if severity >= 3:
            return 'high'
        if severity == 2:
            return 'medium'
        return 'low'

    @classmethod
    def build_root_cause_candidates(cls, alarm: Dict[str, Any], matched_systems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keywords = alarm.get('keywords', [])
        candidates: List[Dict[str, Any]] = []
        if '超时' in keywords or '延迟' in keywords or '响应' in keywords:
            candidates.append({
                'cause': '应用服务性能或连接延迟',
                'confidence': 0.85,
                'detail': '告警描述中出现延迟或响应异常，通常与服务性能、网络或数据库连接相关。'
            })
        if '失败率' in keywords or '错误' in keywords or '异常' in keywords:
            candidates.append({
                'cause': '业务逻辑或下游依赖异常',
                'confidence': 0.78,
                'detail': '告警文本中包含失败率或错误信息，可能来自业务层或下游服务故障。'
            })
        if '连接' in keywords or '断开' in keywords or '阻塞' in keywords:
            candidates.append({
                'cause': '下游依赖链路异常',
                'confidence': 0.76,
                'detail': '连接、断开或阻塞相关关键词指向网络、网关或中间件通道问题。'
            })
        if not candidates:
            candidates.append({
                'cause': '待补充数据的根因分析',
                'confidence': 0.45,
                'detail': '当前告警文本未直接命中已知根因模式，需要补充日志、关联变更和系统监控指标。'
            })
        if matched_systems:
            for candidate in candidates:
                candidate['related_systems'] = [system.get('name') for system in matched_systems if system.get('name')]
        return candidates

    @classmethod
    def diagnose_alarm(cls, alarm_id: str, data_service: Any, kg: Any, depth: int = 2) -> Dict[str, Any]:
        alarm = data_service.get_alarm_by_id(alarm_id)
        if not alarm:
            raise KeyError(f'alarm_id {alarm_id} not found')

        parsed_alarm = AlarmAnalyzer.parse_alarm_record(alarm)
        match_info = AlarmAnalyzer.match_alarm_to_systems(alarm, data_service, kg)
        server_match = AlarmAnalyzer.match_alarm_to_servers(alarm, data_service)
        impact = kg.impact_scope(match_info.get('system_ids', []), max_hops=depth) if kg else {}
        related_reports = data_service.search_postmortems(match_info.get('system_ids', []) + parsed_alarm.get('keywords', []))

        root_causes = cls.build_root_cause_candidates(parsed_alarm, match_info.get('matched_systems', []))
        recommendations = [
            {
                'step': '先确认告警描述中的关键系统与关联上下游',
                'reason': '通过知识图谱快速锁定影响范围，避免误判故障边界。',
                'confidence': 0.83,
            },
            {
                'step': '根据匹配到的系统负责人发起协同沟通',
                'reason': '业务/开发/运维负责人可以提供系统状态和最近变更信息。',
                'confidence': 0.79,
            },
            {
                'step': '优先采集故障时间窗口内的日志与链路指标',
                'reason': '日志和链路指标是验证候选根因的关键证据。',
                'confidence': 0.82,
            },
        ]
        if not match_info.get('matched_systems'):
            recommendations.append({
                'step': '补充系统映射信息或使用应用管理表进行模糊匹配',
                'reason': '当告警未明确匹配系统时，先补齐系统-告警映射关系。',
                'confidence': 0.65,
            })

        return {
            'alarm_id': alarm_id,
            'severity': parsed_alarm.get('severity'),
            'severity_label': cls.describe_severity(parsed_alarm.get('severity', 1)),
            'alarm_name': parsed_alarm.get('alarm_name'),
            'alarm_description': parsed_alarm.get('alarm_description'),
            'keywords': parsed_alarm.get('keywords'),
            'matched_systems': match_info.get('matched_systems', []),
            'owners': match_info.get('owners', []),
            'server_matches': server_match.get('server_matches', []),
            'impact_scope': impact,
            'root_cause_candidates': root_causes,
            'recommendations': recommendations,
            'related_postmortems': related_reports,
        }
