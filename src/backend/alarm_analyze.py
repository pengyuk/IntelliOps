import re
from typing import Any, Dict, List, Optional


class AlarmAnalyzer:
    """Text-level parsing and system matching for alarm records."""

    KEY_TERMS = [
        '超时', '失败率', '延迟', '异常', '连接', '资源', 'CPU', '内存', '响应', '阻塞', '压力', '断开', '错误', '降级', '漏单', '重试', '报错', '吞吐量', '超载'
    ]

    @staticmethod
    def normalize_text(value: Any) -> str:
        if value is None:
            return ''
        text = str(value).strip()
        text = re.sub(r'[\u00A0\u2002\u2003\u2009]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    @classmethod
    def extract_keywords(cls, text: str) -> List[str]:
        text = cls.normalize_text(text)
        if not text:
            return []
        keywords = []
        for term in cls.KEY_TERMS:
            if term in text and term not in keywords:
                keywords.append(term)
        tokens = [token for token in re.split(r'[\s，。；；,;:\-\/\[\]()【】\u00A0]+', text) if len(token) > 1]
        for token in tokens:
            if token not in keywords and len(keywords) < 15:
                keywords.append(token)
        return keywords[:20]

    @classmethod
    def parse_alarm_record(cls, alarm: Dict[str, Any]) -> Dict[str, Any]:
        description = cls.normalize_text(alarm.get('alarm_description') or alarm.get('description') or '')
        extracted = cls.extract_keywords(description)
        return {
            'alarm_id': alarm.get('alarm_id'),
            'severity': alarm.get('severity'),
            'alarm_name': alarm.get('alarm_name'),
            'alarm_description': description,
            'related_systems': alarm.get('related_systems', []),
            'keywords': extracted,
            'owner': cls.normalize_text(alarm.get('ci_owner') or ''),
            'alert_time': alarm.get('alert_time'),
            'source_file': alarm.get('source_file'),
        }

    @classmethod
    def match_alarm_to_systems(cls, alarm: Dict[str, Any], data_service: Any, kg: Any) -> Dict[str, Any]:
        candidates = list(alarm.get('related_systems', []))
        if alarm.get('alarm_name'):
            candidates.append(alarm['alarm_name'])
        if alarm.get('alarm_source'):
            candidates.append(alarm['alarm_source'])
        if alarm.get('system'):
            candidates.append(alarm['system'])
        match_text = ' | '.join([str(value) for value in candidates if value])
        matched_nodes = kg.match_nodes(match_text) if kg else []
        owner_candidates = []
        for node in matched_nodes:
            owner = node.get('owner')
            if owner and owner not in owner_candidates:
                owner_candidates.append(owner)
        if alarm.get('ci_owner'):
            owner_candidates.append(alarm.get('ci_owner'))
        owner_candidates = [owner for owner in owner_candidates if owner]
        if not matched_nodes and data_service:
            for system_text in candidates:
                lower = str(system_text).strip().lower()
                if lower in data_service._application_index:
                    app = data_service._application_index[lower]
                    matched_nodes.append({'id': app.get('biz_serial') or app.get('name'), 'name': app.get('name'), 'owner': app.get('details', {}).get('ci_owner')})
        return {
            'alarm_id': alarm.get('alarm_id'),
            'match_text': match_text,
            'matched_systems': matched_nodes,
            'system_ids': [node.get('id') for node in matched_nodes if node.get('id')],
            'owners': owner_candidates,
        }

    @classmethod
    def match_alarm_to_servers(cls, alarm: Dict[str, Any], data_service: Any) -> Dict[str, Any]:
        targets = []
        for key in ['system', 'alarm_name', 'alarm_source', 'related_systems']:
            value = alarm.get(key)
            if isinstance(value, list):
                targets.extend(value)
            elif value:
                targets.append(value)
        candidates = [cls.normalize_text(item) for item in targets if item]
        hosts = []
        for app_key, app_value in data_service._application_index.items():
            if any(candidate.lower() in app_key for candidate in candidates):
                hosts.append({
                    'app_key': app_key,
                    'app_name': app_value.get('name'),
                    'biz_serial': app_value.get('biz_serial'),
                    'owner': app_value.get('details', {}).get('ci_owner'),
                })
        return {
            'alarm_id': alarm.get('alarm_id'),
            'server_matches': hosts,
            'match_summary': 'matched by application registry or related system names',
        }
