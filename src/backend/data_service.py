import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import xlrd
from docx import Document


class DataService:
    """Load, normalize and expose data from the project data directory."""

    def __init__(self, workspace_root: str):
        self.src_root = Path(workspace_root)
        self.data_root = self._resolve_data_root(self.src_root)
        self.system_relations: List[Dict[str, Any]] = []
        self.application_registry: List[Dict[str, Any]] = []
        self.alarm_records: List[Dict[str, Any]] = []
        self.postmortem_reports: List[Dict[str, Any]] = []
        self._application_index: Dict[str, Dict[str, Any]] = {}
        self._system_index: Dict[str, Dict[str, Any]] = {}
        self.load_all()

    def _resolve_data_root(self, root: Path) -> Path:
        if root.name == 'data':
            return root
        candidate = root / 'data'
        if candidate.exists():
            return candidate
        candidate = root.parent / 'data'
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f'Cannot find data directory from workspace root: {root}')

    def load_all(self) -> None:
        self.system_relations = self.load_system_relations()
        self.application_registry = self.load_application_registry()
        self.alarm_records = self.load_alarm_records()
        self.postmortem_reports = self.load_postmortems()
        self._application_index = self._build_application_index()
        self._system_index = self._build_system_index()

    def reload(self) -> Dict[str, Any]:
        self.load_all()
        return self.summary()

    def summary(self) -> Dict[str, Any]:
        return {
            'data_root': str(self.data_root),
            'system_relations': len(self.system_relations),
            'application_registry': len(self.application_registry),
            'alarm_records': len(self.alarm_records),
            'postmortem_reports': len(self.postmortem_reports),
            'source_files': {
                'system_relations': [str(p.name) for p in sorted((self.data_root / '系统上下游关系').glob('*'))]
                if (self.data_root / '系统上下游关系').exists() else [],
                'application_registry': [str(p.name) for p in sorted((self.data_root / '系统基本信息').glob('*'))]
                if (self.data_root / '系统基本信息').exists() else [],
                'alarm_records': [str(p.name) for p in sorted((self.data_root / '告警信息').glob('*'))]
                if (self.data_root / '告警信息').exists() else [],
                'postmortem_reports': [str(p.name) for p in sorted((self.data_root / '故障复盘报告').glob('*'))]
                if (self.data_root / '故障复盘报告').exists() else [],
            },
        }

    def _normalize_text(self, value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if isinstance(value, float) and math.isnan(value):
                return ''
            return str(value)
        text = str(value).strip()
        text = re.sub(r'[\u00A0\u2002\u2003\u2009]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _clean_column_name(self, name: Any) -> str:
        text = self._normalize_text(name)
        if not text:
            return ''
        text = re.sub(r'\s+', '_', text)
        text = re.sub(r'[^\w\u4e00-\u9fff_]+', '', text)
        if text and text[0].isdigit():
            text = '_' + text
        return text

    def _read_xls(self, path: Path, sheet_name: Optional[str] = None) -> pd.DataFrame:
        workbook = xlrd.open_workbook(path.as_posix())
        sheet = workbook.sheet_by_name(sheet_name) if sheet_name and sheet_name in workbook.sheet_names() else workbook.sheet_by_index(0)
        rows = [sheet.row_values(r) for r in range(sheet.nrows)]
        return self._rows_to_dataframe(rows)

    def _read_xlsx(self, path: Path, sheet_name: Optional[str] = None) -> pd.DataFrame:
        return pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl', dtype=str)

    def _read_excel(self, path: Path, sheet_name: Optional[str] = None) -> pd.DataFrame:
        if path.suffix.lower() == '.xls':
            return self._read_xls(path, sheet_name=sheet_name)
        return self._read_xlsx(path, sheet_name=sheet_name)

    def _rows_to_dataframe(self, rows: List[List[Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        header_row = self._detect_header_row(rows)
        headers = [self._clean_column_name(cell) or f'column_{idx}' for idx, cell in enumerate(rows[header_row])]
        data_rows = rows[header_row + 1:]
        df = pd.DataFrame(data_rows, columns=headers)
        return df

    def _detect_header_row(self, rows: List[List[Any]]) -> int:
        for index, row in enumerate(rows[:5]):
            text_row = [self._normalize_text(cell).lower() for cell in row]
            if any(re.search(r'publish_system_code|subscribe_system_code|relation_type|system|name|biz_serial|告警|关联系统|关键系统', cell) for cell in text_row):
                return index
        return 0

    def _dataframe_to_records(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        if df.empty:
            return []
        df = df.where(pd.notnull(df), None)
        records: List[Dict[str, Any]] = []
        for row in df.to_dict(orient='records'):
            record = {self._clean_column_name(k): self._normalize_text(v) for k, v in row.items()}
            if any(value for value in record.values()):
                records.append(record)
        return records

    def _guess_sheet_name(self, sheet_names: List[str], candidates: List[str]) -> Optional[str]:
        lower_names = [name.lower() for name in sheet_names]
        for candidate in candidates:
            for name in lower_names:
                if candidate.lower() in name:
                    return sheet_names[lower_names.index(name)]
        return None

    def load_system_relations(self) -> List[Dict[str, Any]]:
        folder = self.data_root / '系统上下游关系'
        if not folder.exists():
            return []
        relations: List[Dict[str, Any]] = []
        for path in sorted(folder.glob('*.xls')) + sorted(folder.glob('*.xlsx')):
            if path.suffix.lower() == '.xls':
                df = self._read_xls(path)
            else:
                sheet_name = self._guess_sheet_name(pd.ExcelFile(path).sheet_names, ['user', '系统使用关系', 'SysAccessRelation'])
                df = self._read_excel(path, sheet_name=sheet_name)
            records = self._dataframe_to_records(df)
            for record in records:
                relation = {
                    'source_file': path.name,
                    'publish_system_code': record.get('publish_system_code') or record.get('publish_system') or record.get('发布系统编码') or record.get('source_system'),
                    'subscribe_system_code': record.get('subscribe_system_code') or record.get('subscribe_system') or record.get('订阅系统编码') or record.get('target_system'),
                    'relation_type': record.get('relation_type') or record.get('关系类型') or record.get('relation') or 'depends_on',
                    'access_mode': record.get('access_mode') or record.get('access方式') or '',
                    'description': record.get('descript') or record.get('description') or record.get('备注') or '',
                    'application_list': record.get('application_list') or '',
                    'ci_owner': record.get('ci_owner') or record.get('system_owner') or '',
                }
                if relation['publish_system_code'] or relation['subscribe_system_code']:
                    relations.append(relation)
        return relations

    def load_application_registry(self) -> List[Dict[str, Any]]:
        folder = self.data_root / '系统基本信息'
        if not folder.exists():
            return []
        applications: List[Dict[str, Any]] = []
        for path in sorted(folder.glob('*.xlsx')):
            workbook = pd.ExcelFile(path, engine='openpyxl')
            for sheet in workbook.sheet_names:
                df = self._read_excel(path, sheet_name=sheet)
                if df.empty:
                    continue
                if self._is_schema_sheet(df):
                    continue
                records = self._dataframe_to_records(df)
                for record in records:
                    app = {
                        'source_file': path.name,
                        'source_sheet': sheet,
                        'name': record.get('name') or record.get('系统名称') or record.get('名称') or record.get('biz_serial') or '',
                        'en_short_name': record.get('en_short_name') or record.get('英文简称') or '',
                        'biz_serial': record.get('biz_serial') or record.get('业务识别') or record.get('system_code') or record.get('系统编码') or '',
                        'availability_rating': record.get('availability_rating') or record.get('可用性等级') or '',
                        'importance': record.get('systematic_importance_classification') or record.get('系统重要性分类') or '',
                        'details': {k: v for k, v in record.items() if k not in {'source_file', 'source_sheet', 'name', 'en_short_name', 'biz_serial', 'availability_rating', 'importance'}},
                    }
                    applications.append(app)
        return applications

    def _is_schema_sheet(self, df: pd.DataFrame) -> bool:
        first_row = [self._normalize_text(value).lower() for value in df.iloc[0].tolist()]
        return any('字段名' in value or '字段描述' in value or 'field_name' in value or '字段值' in value for value in first_row)

    def load_alarm_records(self) -> List[Dict[str, Any]]:
        folder = self.data_root / '告警信息'
        if not folder.exists():
            return []
        alarms: List[Dict[str, Any]] = []
        sequence = 1
        for path in sorted(folder.glob('*')):
            if path.suffix.lower() not in {'.xls', '.xlsx', '.csv'}:
                continue
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(path, dtype=str, encoding='utf-8', keep_default_na=False)
            else:
                df = self._read_excel(path)
            records = self._dataframe_to_records(df)
            for row in records:
                alarm_record = {
                    'alarm_id': f'{path.stem}-{sequence:04d}',
                    'source_file': path.name,
                    'severity': int(row.get('告警当前级别') or row.get('severity') or 1),
                    'system': row.get('系统') or row.get('system') or '',
                    'alarm_name': row.get('告警名称') or row.get('alarm_name') or '',
                    'alarm_source': row.get('告警来源') or row.get('alarm_source') or '',
                    'alarm_description': row.get('告警描述') or row.get('告警信息') or row.get('description') or '',
                    'related_systems': self._collect_system_fields(row),
                    'alert_time': row.get('告警发出时间') or row.get('alert_time') or '',
                    'resolved_time': row.get('结束时间') or row.get('resolved_time') or '',
                    'tags': row.get('标签') or row.get('tags') or '',
                    'ci_owner': row.get('ci_owner') or row.get('mainTeam_ciProperty') or row.get('applicationTeam_ciProperty') or '',
                    'metadata': row,
                }
                alarm_record['keywords'] = self.extract_alarm_keywords(alarm_record['alarm_description'])
                alarms.append(alarm_record)
                sequence += 1
        return alarms

    def _collect_system_fields(self, record: Dict[str, Any]) -> List[str]:
        candidates = []
        for key in ['关联系统', '关键系统', 'sourceSystem', '系统', 'system', '告警范围', '告警来源']:
            value = record.get(key)
            if value:
                candidates.extend([item.strip() for item in re.split(r'[\|,;/\\]+', str(value)) if item.strip()])
        return list(dict.fromkeys(candidates))

    def extract_alarm_keywords(self, text: str) -> List[str]:
        text = self._normalize_text(text)
        if not text:
            return []
        tokens = [token for token in re.split(r'[\s，。；；,;:\-\/\[\]()]+', text) if len(token) > 1]
        keywords: List[str] = []
        for token in tokens:
            if token not in keywords and len(token) <= 20:
                keywords.append(token)
        return keywords[:20]

    def load_postmortems(self) -> List[Dict[str, Any]]:
        folder = self.data_root / '故障复盘报告'
        if not folder.exists():
            return []
        reports: List[Dict[str, Any]] = []
        for path in sorted(folder.glob('*.docx')):
            document = Document(path)
            paragraphs = [self._normalize_text(paragraph.text) for paragraph in document.paragraphs if self._normalize_text(paragraph.text)]
            content = '\n'.join(paragraphs)
            report = {
                'report_id': path.stem,
                'file_name': path.name,
                'title': paragraphs[0] if paragraphs else path.stem,
                'content': content,
                'created_at': datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                'keywords': self.extract_alarm_keywords(content),
            }
            reports.append(report)
        return reports

    def _build_application_index(self) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for app in self.application_registry:
            for key in [app.get('name'), app.get('en_short_name'), app.get('biz_serial')]:
                if key:
                    index[key.strip().lower()] = app
        return index

    def _build_system_index(self) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for relation in self.system_relations:
            for key in [relation.get('publish_system_code'), relation.get('subscribe_system_code')]:
                if key:
                    index[key.strip().lower()] = relation
        return index

    def get_alarm_by_id(self, alarm_id: str) -> Optional[Dict[str, Any]]:
        return next((alarm for alarm in self.alarm_records if alarm.get('alarm_id') == alarm_id), None)

    def search_postmortems(self, keywords: List[str]) -> List[Dict[str, Any]]:
        lower_keywords = [keyword.lower() for keyword in keywords if keyword]
        matches: List[Dict[str, Any]] = []
        for report in self.postmortem_reports:
            text = report.get('content', '').lower()
            if any(keyword in text for keyword in lower_keywords):
                matches.append(report)
        return matches
