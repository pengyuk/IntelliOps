"""
Skill Loader — discovers, validates, and loads all SKILL.md files at startup.

Each skill lives in src/skill/<skill-name>/SKILL.md with YAML frontmatter.
The loader parses metadata (name, description, triggers) and body (steps, API refs).
Loaded skills are indexed by name and by trigger keywords for fast routing.

Usage:
    loader = SkillLoader(skill_root="src/skill")
    await loader.load_all()
    skill = loader.get("incident-diagnosis")
    matches = loader.match("支付延迟，帮我诊断一下")
"""

from __future__ import annotations

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SkillMeta:
    """Parsed YAML frontmatter from SKILL.md."""
    name: str
    description: str = ""
    argument_hint: str = ""
    user_invocable: bool = True
    disable_model_invocation: bool = False

    # Extracted from description for fast matching
    trigger_keywords: List[str] = field(default_factory=list)
    # Chinese + English keywords
    trigger_keywords_cn: List[str] = field(default_factory=list)
    trigger_keywords_en: List[str] = field(default_factory=list)


@dataclass
class Skill:
    """A fully loaded skill with metadata and body content."""
    meta: SkillMeta
    body: str                          # Markdown body (steps, API refs, etc.)
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    
    # Parsed sections
    steps: List[Dict[str, Any]] = field(default_factory=list)
    api_refs: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    
    @property
    def name(self) -> str:
        return self.meta.name
    
    @property
    def description(self) -> str:
        return self.meta.description
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.meta.name,
            "description": self.meta.description,
            "argument_hint": self.meta.argument_hint,
            "user_invocable": self.meta.user_invocable,
            "trigger_keywords": self.meta.trigger_keywords,
            "steps_count": len(self.steps),
            "api_refs": self.api_refs,
        }


# ---------------------------------------------------------------------------
# YAML frontmatter parser
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)

# Keyword extraction: split on common delimiters
_KEYWORD_SPLIT_RE = re.compile(r'[、，,。；;：:\s]+')

# Chinese character detector
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _extract_keywords(description: str) -> Tuple[List[str], List[str], List[str]]:
    """Extract Chinese and English trigger keywords from description."""
    # The description in SKILL.md often has lines like:
    # "触发词：故障、事故、incident、诊断..."
    # Extract the trigger words part
    trigger_match = re.search(r'触发词[：:]\s*(.+?)(?:[。\.]|使用场景|$)', description)
    if trigger_match:
        raw = trigger_match.group(1)
    else:
        raw = description
    
    words = [w.strip() for w in _KEYWORD_SPLIT_RE.split(raw) if w.strip()]
    
    cn_words = [w for w in words if _CJK_RE.search(w)]
    en_words = [w for w in words if not _CJK_RE.search(w)]
    
    return words, cn_words, en_words


def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter and body from SKILL.md text."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    
    yaml_text = m.group(1)
    body = text[m.end():]
    
    try:
        meta = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        meta = {}
    
    return meta, body


def _parse_steps(body: str) -> List[Dict[str, Any]]:
    """Extract structured steps from body."""
    steps = []
    # Match "### 步骤 N：标题" pattern
    step_pattern = re.compile(r'###\s*步骤\s*(\d+)[：:]\s*(.+?)(?=\n###\s*步骤|\n##|\Z)', re.DOTALL)
    for m in step_pattern.finditer(body):
        step_num = int(m.group(1))
        title = m.group(2).strip().split('\n')[0].strip()
        content = m.group(2).strip()
        steps.append({
            "step": step_num,
            "title": title,
            "content": content[:500],  # truncated for context
        })
    return steps


def _parse_api_refs(body: str) -> List[str]:
    """Extract API endpoint references from body."""
    refs = []
    # Match patterns like: POST /copilot/diagnose, GET /kg/query, etc.
    api_pattern = re.compile(r'(?:GET|POST|PUT|DELETE)\s+(/\S+)')
    for m in api_pattern.finditer(body):
        refs.append(m.group(0))
    return list(dict.fromkeys(refs))  # dedup preserving order


def _parse_references(body: str) -> List[str]:
    """Extract reference file paths."""
    refs = []
    ref_pattern = re.compile(r'\[.*?\]\(\./(.*?)\)')
    for m in ref_pattern.finditer(body):
        refs.append(m.group(1))
    return refs


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------

class SkillLoader:
    """Discovers and loads all skills from the filesystem."""
    
    def __init__(self, skill_root: Optional[str] = None):
        if skill_root is None:
            # Default: src/skill/ relative to this file's package
            here = Path(__file__).resolve().parent.parent  # src/backend -> src
            skill_root = str(here / "skill")
        self.skill_root = Path(skill_root)
        self._skills: Dict[str, Skill] = {}
        self._keyword_index: Dict[str, List[str]] = {}  # keyword -> [skill_name]
        self._loaded = False
    
    @property
    def skills(self) -> Dict[str, Skill]:
        return self._skills
    
    @property
    def loaded(self) -> bool:
        return self._loaded
    
    def list_skills(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._skills.values()]
    
    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)
    
    async def load_all(self) -> Dict[str, Skill]:
        """Discover and load all SKILL.md files under skill_root."""
        if not self.skill_root.exists():
            print(f"[SkillLoader] Skill root not found: {self.skill_root}")
            self._loaded = True
            return {}
        
        count = 0
        for skill_dir in sorted(self.skill_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            
            try:
                skill = self._load_one(skill_md)
                self._skills[skill.name] = skill
                self._index_keywords(skill)
                count += 1
                print(f"[SkillLoader]   ✓ Loaded: {skill.name} ({len(skill.meta.trigger_keywords)} keywords)")
            except Exception as e:
                print(f"[SkillLoader]   ⚠ Failed to load {skill_md}: {e}")
        
        self._loaded = True
        print(f"[SkillLoader] Total skills loaded: {count}")
        return self._skills
    
    def _load_one(self, file_path: Path) -> Skill:
        """Load a single SKILL.md file."""
        text = file_path.read_text(encoding='utf-8')
        raw_meta, body = _parse_frontmatter(text)
        
        # Build SkillMeta
        name = raw_meta.get('name', file_path.parent.name)
        description = raw_meta.get('description', '')
        all_kw, cn_kw, en_kw = _extract_keywords(description)
        
        meta = SkillMeta(
            name=name,
            description=description,
            argument_hint=raw_meta.get('argument-hint', ''),
            user_invocable=raw_meta.get('user-invocable', True),
            disable_model_invocation=raw_meta.get('disable-model-invocation', False),
            trigger_keywords=all_kw,
            trigger_keywords_cn=cn_kw,
            trigger_keywords_en=en_kw,
        )
        
        # Parse body sections
        steps = _parse_steps(body)
        api_refs = _parse_api_refs(body)
        references = _parse_references(body)
        
        return Skill(
            meta=meta,
            body=body,
            raw_frontmatter=raw_meta,
            file_path=str(file_path),
            steps=steps,
            api_refs=api_refs,
            references=references,
        )
    
    def _index_keywords(self, skill: Skill) -> None:
        """Build keyword -> skill_name reverse index."""
        for kw in skill.meta.trigger_keywords:
            kw_lower = kw.lower()
            if kw_lower not in self._keyword_index:
                self._keyword_index[kw_lower] = []
            if skill.name not in self._keyword_index[kw_lower]:
                self._keyword_index[kw_lower].append(skill.name)
    
    def match(self, query: str, top_k: int = 3) -> List[Tuple[Skill, float]]:
        """Match a user query to the most relevant skills.
        
        Returns list of (Skill, score) sorted by relevance.
        """
        query_lower = query.lower()
        scores: Dict[str, float] = {}
        
        for skill_name, skill in self._skills.items():
            score = 0.0
            
            # 1. Exact keyword match (high weight)
            for kw in skill.meta.trigger_keywords:
                kw_lower = kw.lower()
                if kw_lower in query_lower:
                    # Longer keyword = more specific match
                    score += len(kw) * 0.5
            
            # 2. Description text overlap
            desc_lower = skill.meta.description.lower()
            desc_words = set(_KEYWORD_SPLIT_RE.split(desc_lower))
            query_words = set(_KEYWORD_SPLIT_RE.split(query_lower))
            overlap = desc_words & query_words
            score += len(overlap) * 0.3
            
            # 3. Step content match (bonus for matching step titles)
            for step in skill.steps:
                step_text = (step.get('title', '') + ' ' + step.get('content', '')).lower()
                step_words = set(_KEYWORD_SPLIT_RE.split(step_text))
                step_overlap = step_words & query_words
                score += len(step_overlap) * 0.15
            
            if score > 0:
                scores[skill_name] = score
        
        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [(self._skills[name], score) for name, score in ranked[:top_k]]
    
    def match_single(self, query: str) -> Optional[Skill]:
        """Return the best matching skill, or None."""
        matches = self.match(query, top_k=1)
        return matches[0][0] if matches else None
    
    def get_active_skills_for_context(self, incident: Dict[str, Any], 
                                       diagnosis: Optional[Dict[str, Any]] = None) -> List[Skill]:
        """Determine which skills should be active given the current incident state."""
        active = []
        summary = incident.get('summary', '')
        status = incident.get('status', '')
        
        # Always include incident-diagnosis for active incidents
        if status != 'Resolved':
            diag = self.get('incident-diagnosis')
            if diag:
                active.append(diag)
            
            log = self.get('log-analysis')
            if log:
                active.append(log)
            
            script = self.get('script-operations')
            if script:
                active.append(script)
        
        # Knowledge retrieval always useful
        kg = self.get('knowledge-retrieval')
        if kg:
            active.append(kg)
        
        # Postmortem only when resolved or explicitly requested
        if status == 'Resolved':
            pm = self.get('postmortem-generator')
            if pm:
                active.append(pm)
        
        # War room for collaborative scenarios
        war = self.get('war-room-coordination')
        if war:
            active.append(war)
        
        return active


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_loader: Optional[SkillLoader] = None


async def get_skill_loader(skill_root: Optional[str] = None) -> SkillLoader:
    """Get or create the global SkillLoader singleton."""
    global _loader
    if _loader is None:
        _loader = SkillLoader(skill_root=skill_root)
        await _loader.load_all()
    return _loader


def reset_skill_loader() -> None:
    """Reset the singleton (for testing)."""
    global _loader
    _loader = None
