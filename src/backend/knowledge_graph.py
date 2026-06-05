from collections import defaultdict, deque
from typing import Any, Dict, List, Optional


class KnowledgeGraph:
    """Build a lightweight system knowledge graph from relation and application data."""

    def __init__(self, relations: List[Dict[str, Any]], applications: List[Dict[str, Any]]):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.adjacency: Dict[str, List[str]] = defaultdict(list)
        self._load_applications(applications)
        self._load_relations(relations)

    def _add_node(self, node_id: str, node: Dict[str, Any]) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = {**node}
        else:
            self.nodes[node_id].update({k: v for k, v in node.items() if v})

    def _normalize_id(self, value: Optional[str]) -> str:
        if not value:
            return ''
        return value.strip()

    def _load_applications(self, applications: List[Dict[str, Any]]) -> None:
        for application in applications:
            node_id = self._normalize_id(application.get('biz_serial') or application.get('en_short_name') or application.get('name'))
            if not node_id:
                continue
            self._add_node(node_id, {
                'id': node_id,
                'type': 'application',
                'name': application.get('name') or application.get('en_short_name') or node_id,
                'owner': application.get('details', {}).get('ci_owner') or application.get('details', {}).get('application_owner') or '',
                'source_sheet': application.get('source_sheet'),
                'source_file': application.get('source_file'),
            })

    def _load_relations(self, relations: List[Dict[str, Any]]) -> None:
        for relation in relations:
            source = self._normalize_id(relation.get('publish_system_code') or relation.get('publish_system') or '')
            target = self._normalize_id(relation.get('subscribe_system_code') or relation.get('subscribe_system') or '')
            if not source or not target:
                continue
            self._add_node(source, {
                'id': source,
                'type': 'system',
                'name': source,
                'owner': relation.get('ci_owner') or '',
            })
            self._add_node(target, {
                'id': target,
                'type': 'system',
                'name': target,
                'owner': relation.get('ci_owner') or '',
            })
            edge = {
                'from': source,
                'to': target,
                'relation': relation.get('relation_type') or 'depends_on',
                'description': relation.get('description', ''),
                'source_file': relation.get('source_file', ''),
            }
            self.edges.append(edge)
            self.adjacency[source].append(target)
            self.adjacency[target].append(source)

    def match_nodes(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        normalized = text.strip().lower()
        matched: List[Dict[str, Any]] = []
        for node_id, node in self.nodes.items():
            name = str(node.get('name', '')).lower()
            if node_id.lower() in normalized or name in normalized or any(part in normalized for part in [node_id.lower(), name]):
                matched.append(node)
        return matched

    def impact_scope(self, start_ids: List[str], max_hops: int = 2) -> Dict[str, Any]:
        start_ids = [self._normalize_id(node_id) for node_id in start_ids if node_id]
        visited = set(start_ids)
        queue = deque([(node_id, 0, [node_id]) for node_id in start_ids])
        paths: List[List[str]] = []

        while queue:
            current, depth, route = queue.popleft()
            if depth >= max_hops:
                continue
            for neighbor in self.adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_route = route + [neighbor]
                    paths.append(new_route)
                    queue.append((neighbor, depth + 1, new_route))

        return {
            'root_systems': start_ids,
            'max_hops': max_hops,
            'affected_node_ids': list(visited),
            'affected_nodes': [self.nodes[node_id] for node_id in visited if node_id in self.nodes],
            'paths': paths,
            'edges': [edge for edge in self.edges if edge['from'] in visited or edge['to'] in visited],
        }

    def match_system_ids(self, candidates: List[str]) -> List[str]:
        ids = []
        for candidate in candidates:
            normalized = str(candidate).strip().lower()
            for node_id, node in self.nodes.items():
                if node_id.lower() in normalized or str(node.get('name', '')).lower() in normalized:
                    if node_id not in ids:
                        ids.append(node_id)
        return ids

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(self._normalize_id(node_id))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'nodes': list(self.nodes.values()),
            'edges': self.edges,
            'node_count': len(self.nodes),
            'edge_count': len(self.edges),
        }
