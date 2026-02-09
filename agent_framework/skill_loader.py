#!/usr/bin/env python3
"""Agent Framework Skills Loader - Skills 加载模块"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class SkillStatus(Enum):
    """技能状态"""
    LOADED = "loaded"
    UNLOADED = "unloaded"
    ERROR = "error"


@dataclass
class SkillMetadata:
    """技能元数据"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class Skill:
    """技能定义"""
    name: str
    description: str
    path: Path
    dir: Path
    metadata: SkillMetadata
    body: str = ""
    status: SkillStatus = SkillStatus.UNLOADED
    scripts_dir: Optional[Path] = None
    references_dir: Optional[Path] = None
    assets_dir: Optional[Path] = None
    loaded_at: Optional[float] = None


class SkillLoader:
    """Skills 加载器"""

    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self._lock = __import__('threading').Lock()

    def scan(self) -> List[str]:
        """扫描 skills 目录"""
        if not self.skills_dir.exists():
            return []
        loaded_skills = []
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                skill = self._parse_skill_file(skill_md)
                if skill:
                    self.skills[skill.name] = skill
                    loaded_skills.append(skill.name)
            except Exception as e:
                print(f"[SkillLoader] Error parsing skill {skill_dir.name}: {e}")
        return loaded_skills

    def _parse_skill_file(self, path: Path) -> Optional[Skill]:
        """解析 SKILL.md 文件"""
        content = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return None

        frontmatter, body = match.groups()
        metadata = self._parse_frontmatter(frontmatter)
        if not metadata or "name" not in metadata or "description" not in metadata:
            return None

        skill_dir = path.parent
        return Skill(
            name=metadata["name"],
            description=metadata["description"],
            path=path,
            dir=skill_dir,
            metadata=SkillMetadata(
                name=metadata["name"],
                description=metadata["description"],
                version=metadata.get("version", "1.0.0"),
                author=metadata.get("author", ""),
                tags=metadata.get("tags", []),
                dependencies=metadata.get("dependencies", []),
            ),
            body=body.strip(),
            status=SkillStatus.LOADED,
            loaded_at=time.time(),
            scripts_dir=skill_dir / "scripts" if (skill_dir / "scripts").exists() else None,
            references_dir=skill_dir / "references" if (skill_dir / "references").exists() else None,
            assets_dir=skill_dir / "assets" if (skill_dir / "assets").exists() else None,
        )

    def _parse_frontmatter(self, content: str) -> Dict[str, Any]:
        """解析 YAML-like frontmatter"""
        metadata = {}
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if key in ["metadata", "dependencies", "tags"] and value in ["", None]:
                continue
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
            elif value:
                value = value.strip("\"'")
            metadata[key] = value
        return metadata

    def load_skill(self, name: str) -> Optional[Skill]:
        """加载技能"""
        if name not in self.skills:
            return None
        skill = self.skills[name]
        skill.status = SkillStatus.LOADED
        skill.loaded_at = time.time()
        return skill

    def get_skill_content(self, name: str) -> Optional[str]:
        """获取技能内容"""
        skill = self.load_skill(name)
        if not skill:
            return None
        return f"# Skill: {skill.name}\n\n{skill.body}"

    def get_descriptions(self) -> str:
        """获取技能描述列表"""
        if not self.skills:
            return "(no skills available)"
        return "\n".join(f"- {name}: {s.description}" for name, s in self.skills.items())

    def list_skills(self) -> List[str]:
        """列出技能"""
        return list(self.skills.keys())

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_skills": len(self.skills),
            "loaded_skills": sum(1 for s in self.skills.values() if s.status == SkillStatus.LOADED),
            "skills_dir": str(self.skills_dir),
        }

    def reload(self, name: str = None) -> List[str]:
        """重新加载技能"""
        with self._lock:
            if name:
                if name in self.skills:
                    del self.skills[name]
                return self.scan()
            self.skills.clear()
            return self.scan()


_skills_loader: Optional[SkillLoader] = None


def get_skills_loader(skills_dir: str = None) -> SkillLoader:
    global _skills_loader
    if skills_dir is not None:
        return SkillLoader(skills_dir)
    if _skills_loader is None:
        from .config import get_config
        _skills_loader = SkillLoader(get_config().skills_dir)
    return _skills_loader


def scan_skills(skills_dir: str = None) -> List[str]:
    if skills_dir is not None:
        return SkillLoader(skills_dir).scan()
    return get_skills_loader().scan()


def get_skill_content(name: str) -> Optional[str]:
    return get_skills_loader().get_skill_content(name)


def list_skills() -> List[str]:
    return get_skills_loader().list_skills()
