import json
import re
from collections import Counter

from rapidfuzz import fuzz, process

from hireability.config import SKILLS_PATH

TOKEN_RE = re.compile(r"[a-z0-9+#./-]+", re.IGNORECASE)

# Industry layoffs tend to flood these skill buckets.
INDUSTRY_SKILL_MAP: dict[str, list[str]] = {
    "technology": ["backend", "frontend", "python", "javascript", "devops", "data_engineering"],
    "search/ai": ["python", "machine_learning", "deep_learning", "nlp", "ai", "backend"],
    "enterprise software": ["java", "csharp", "backend", "sql", "devops", "aws"],
    "saas": ["javascript", "react", "backend", "sql", "product_management"],
    "fintech": ["python", "java", "backend", "security", "sql"],
    "crypto": ["javascript", "blockchain", "backend", "security"],
    "e-commerce": ["java", "python", "backend", "devops", "data_engineering"],
    "social media": ["python", "machine_learning", "backend", "mobile", "data_engineering"],
    "streaming": ["python", "backend", "data_engineering", "mobile"],
    "gaming": ["cpp", "csharp", "mobile", "backend"],
    "semiconductors": ["cpp", "embedded", "linux"],
    "hardware": ["cpp", "embedded", "linux"],
    "automotive": ["cpp", "embedded", "machine_learning", "python"],
}


class SkillNormalizer:
    def __init__(self, skills_path=SKILLS_PATH, score_cutoff: int = 82):
        with skills_path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        self.canonical_skills = list(raw.keys())
        self.alias_to_canonical: dict[str, str] = {}
        for canonical, aliases in raw.items():
            self.alias_to_canonical[canonical.lower()] = canonical
            for alias in aliases:
                self.alias_to_canonical[alias.lower()] = canonical

        self.choices = list(self.alias_to_canonical.keys())
        self.phrase_aliases = [
            (alias, canonical)
            for alias, canonical in self.alias_to_canonical.items()
            if " " in alias or len(alias) >= 6
        ]
        self.score_cutoff = score_cutoff

    def normalize_token(self, token: str) -> str | None:
        cleaned = token.strip().lower()
        if not cleaned:
            return None
        if cleaned in self.alias_to_canonical:
            return self.alias_to_canonical[cleaned]

        match = process.extractOne(
            cleaned,
            self.choices,
            scorer=fuzz.WRatio,
            score_cutoff=self.score_cutoff,
        )
        if match:
            return self.alias_to_canonical[match[0]]
        return None

    def _normalize_token_fast(self, token: str) -> str | None:
        return self.alias_to_canonical.get(token.strip().lower())

    def extract_from_text(self, text: str) -> Counter:
        counts: Counter = Counter()
        lowered = text.lower()
        for alias, canonical in self.phrase_aliases:
            if alias in lowered:
                counts[canonical] += 1

        for token in TOKEN_RE.findall(lowered):
            canonical = self._normalize_token_fast(token)
            if canonical:
                counts[canonical] += 1
        return counts

    def extract_from_tags(self, tags: list[str]) -> Counter:
        counts: Counter = Counter()
        for tag in tags:
            canonical = self._normalize_token_fast(tag) or self.normalize_token(tag)
            if canonical:
                counts[canonical] += 1
            else:
                counts.update(self.extract_from_text(tag))
        return counts

    def skills_for_industry(self, industry: str) -> list[str]:
        key = industry.strip().lower()
        return INDUSTRY_SKILL_MAP.get(key, INDUSTRY_SKILL_MAP["technology"])

    def aliases_for(self, canonical: str) -> list[str]:
        target = canonical.strip().lower()
        aliases = {canonical}
        for alias, name in self.alias_to_canonical.items():
            if name.lower() == target:
                aliases.add(alias)
                aliases.add(name)
        return sorted(aliases, key=len, reverse=True)
