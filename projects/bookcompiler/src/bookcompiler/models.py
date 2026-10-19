from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Chapter:
    index: int
    title: str
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class Chunk:
    chunk_id: str
    book_id: str
    chapter_index: int
    chapter_title: str
    position: int
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class ParsedBook:
    book_id: str
    title: str
    author: str
    path: str
    format: str
    disciplines: list[str]
    chapters: list[Chapter]
    chunks: list[Chunk]
    pages: int | None = None


@dataclass
class Evidence:
    book_id: str
    quote: str
    chunk_id: str = ""
    chapter: str = ""
    page: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BookCard:
    book_id: str
    title: str
    author: str
    one_line_thesis: str
    core_questions: list[str]
    key_concepts: list[str]
    assumptions: list[str]
    limitations: list[str]
    best_for: list[str]
    not_for: list[str]
    chapter_coverage: list[dict[str, Any]]
    lenses: list[str]
    confidence: str = "medium"
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameworkCard:
    framework_id: str
    book_id: str
    name: str
    one_liner: str
    lenses: list[str]
    applicable_when: list[str]
    inputs: list[str]
    steps: list[str]
    outputs: list[str]
    failure_modes: list[str]
    counterexamples: list[str]
    citations: list[Evidence]
    related_frameworks: list[str] = field(default_factory=list)
    confidence: str = "medium"
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["citations"] = [c.to_dict() for c in self.citations]
        return payload


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompileResult:
    book_id: str
    book_card: BookCard
    frameworks: list[FrameworkCard]
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "book_card": self.book_card.to_dict(),
            "frameworks": [f.to_dict() for f in self.frameworks],
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class AnalysisPacket:
    analysis_id: str
    question: str
    mode: str
    lenses: list[str]
    selection: dict[str, Any]
    frameworks: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    counterevidence: list[dict[str, Any]]
    cross_lens_conflicts: list[dict[str, Any]]
    conclusion: str
    uncertainty: str
    next_checks: list[str]
    citations: list[dict[str, Any]]
    jurisdiction: str
    not_legal_advice: bool
    status: str
    created_at: str
    memory_context: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    reader_notes: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] = field(default_factory=dict)
    orchestration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectionProposal:
    mode: str
    query: str
    lenses: list[str]
    direction: str
    specified_books: list[dict[str, Any]]
    specified_frameworks: list[dict[str, Any]]
    recommended_books: list[dict[str, Any]]
    recommended_frameworks: list[dict[str, Any]]
    coverage_gaps: list[str]
    requires_confirmation: bool
    options: list[str]
    rationale: str
    source_recommendations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)