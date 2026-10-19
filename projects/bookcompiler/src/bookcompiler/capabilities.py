"""Domain capability packs for a compiled book library.

A capability pack is deliberately *not* a per-book skill.  It is a small,
versioned, domain-level bundle that tells an agent which learned books are
authoritative, which frameworks encode its procedures, which claims/entities
provide evidence, how to route a new event, and how to evaluate the result.

The pack is generated from SQLite and written as JSON + Markdown under the
single host-facing ``book-library`` skill.  The host sees one skill; the
project maintains many internal packs without a routing explosion.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .config import project_root
from .modes import select_books
from .models import utc_now
from .store import Store, query_terms

SCHEMA_VERSION = 1
DEFAULT_ROOT = project_root() / "skills" / "book-library" / "references" / "packs"

RUBRIC = [
    ("source_fidelity", "Every factual claim is grounded in an exact book quote; no invented source."),
    ("retrieval_coverage", "The relevant books, chapters and frameworks were actually retrieved."),
    ("framework_fit", "The chosen frameworks genuinely fit the event and their inputs are available."),
    ("cross_book_synthesis", "At least two books are integrated, not merely listed side by side."),
    ("cross_lens_integration", "Economics, politics and law are combined without flattening their differences."),
    ("conflict_handling", "Cross-book contradictions are stated and not silently averaged away."),
    ("calibration", "Confidence matches the evidence; uncertainty and falsifiers are explicit."),
    ("actionability", "The answer gives conditional implications or decisions, not just description."),
    ("failure_mode_awareness", "The framework's failure modes and boundary conditions are applied."),
    ("causal_depth", "The answer traces mechanisms and transmission channels, not just correlations."),
    ("counterargument", "A serious rival explanation is stated and tested."),
    ("boundary_conditions", "The answer says when the conclusion would stop holding."),
    ("falsifiability", "Concrete indicators or observations that would change the judgment are named."),
]

DOMAIN_PRESETS: dict[str, dict[str, Any]] = {
    "political-economy": {
        "title": "政治经济分析",
        "description": "分析财政、货币、信贷、地方政府行为、央地关系、债务周期与政策传导，同时使用经济与政治镜头并保留两者冲突。",
        "lenses": ["economics", "politics"],
        "direction": "财政关系 地方政府行为 土地财政 央地关系 货币供给 基础货币 货币乘数 银行信贷 信用扩张 债务周期 去杠杆 金融危机 政策传导 国家能力",
        "triggers": [
            "财政", "地方债", "地方政府", "土地财政", "央地关系", "转移支付",
            "货币供给", "基础货币", "货币乘数", "银行信贷", "信贷", "信用扩张", "债务周期",
            "去杠杆", "金融危机", "货币政策", "财政政策", "产业政策", "国家能力",
            "政策传导", "金融稳定", "房地产", "城投", "化债", "流动性", "准备金",
            "专项债", "特别国债", "城投平台", "融资平台", "银行间市场",
            "汇率", "资本流动", "利率", "加息", "降息",
            "影子银行", "贸易", "监管", "降准", "地方财政", "消费", "产权",
            "统一大市场", "人口", "国企", "非税收入", "结构性货币政策",
        ],
        "book_titles": [
            "中央银行与货币供给",
            "以利为利：财政关系与地方政府行为",
            "Principles for Navigating Big Debt Crises",
            "当代中国政府与政治",
            "中国近代史",
            "中国的经济制度",
        ],
    },
    "macro-finance": {
        "title": "宏观金融分析",
        "description": "分析货币、信用、利率、汇率、资产价格与金融稳定之间的传导。",
        "lenses": ["economics", "finance"],
        "direction": "货币供给 信用创造 利率 汇率 金融稳定 银行体系 资产价格 金融危机",
        "triggers": ["货币政策", "利率", "汇率", "信贷", "货币供给", "金融稳定", "银行", "资产价格", "金融危机", "降准", "降息", "流动性", "汇率贬值", "加息", "资本流动", "结构性货币政策"],
        "book_titles": ["中央银行与货币供给", "货币数量、利率调控与政策转型", "信用创造、货币供求与经济结构", "稳定不稳定的经济：一种金融不稳定视角", "这次不一样：八百年金融危机史"],
    },
    "legal-reasoning": {
        "title": "法律推理分析",
        "description": "把规则、原则、先例与政策后果放进同一套推理结构；输出分析而非法律意见。",
        "lenses": ["law", "politics"],
        "direction": "法律规则 原则 先例 比例原则 程序正义 合法性 党规国法 权利冲突",
        "triggers": ["法律", "法规", "规章", "上位法", "适用规则", "司法", "合法性", "权利", "程序", "比例原则", "先例", "宪法", "党规", "国法", "监管", "处罚", "合规"],
        "book_titles": ["Introduction to Logic", "当代中国政府与政治", "通往奴役之路"],
    },
}


def _safe_domain(domain: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", (domain or "").strip().lower()).strip("-")
    if not value:
        raise ValueError("domain must contain at least one letter or digit")
    return value


def packs_root(root: str | Path | None = None) -> Path:
    if root is not None and str(root).strip():
        return Path(root).expanduser().resolve()
    env = os.environ.get("BOOKCOMPILER_CAPABILITY_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_ROOT.resolve()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _clean(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _bullets(items: Iterable[Any], empty: str = "（无）") -> str:
    rows = [f"- {_clean(item)}" for item in items if _clean(item)]
    return "\n".join(rows) if rows else empty


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left or "", right or "").ratio()


_KEYWORD_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)
_KEYWORD_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "big",
    "but", "by", "can", "could", "decision", "do", "does", "for", "frame",
    "from", "general", "has", "have", "how", "if", "in", "into", "is", "it",
    "its", "may", "might", "must", "new", "not", "of", "on", "or", "our",
    "should", "test", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "two", "use", "using",
    "value", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
})


def _keywords(parts: Iterable[Any], limit: int = 12) -> list[str]:
    """Extract short, meaningful surface phrases.

    The splitter is Unicode-aware, so Chinese punctuation is handled. English
    stopwords and generic routing words are removed to keep generated triggers
    precise.
    """
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = _clean(part)
        if not text:
            continue
        for segment in _KEYWORD_SPLIT_RE.split(text):
            segment = segment.strip("_")
            if not segment:
                continue
            if re.fullmatch(r"[A-Za-z0-9_]+", segment):
                if len(segment) < 3 and not (len(segment) == 2 and segment.isupper()):
                    continue
                value = segment.lower()
                if value in _KEYWORD_STOPWORDS:
                    continue
            elif re.fullmatch(r"[\u4e00-\u9fff]+", segment):
                if not (2 <= len(segment) <= 12):
                    continue
                value = segment
            else:
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
            if len(result) >= limit:
                return result
    return result


def _trigger_keywords(name: Any, limit: int = 4) -> list[str]:
    """Return precise routing triggers for a framework name.

    Chinese names are split into complete phrases; English names stay as one
    phrase so generic words such as ``with`` or ``test`` never become
    standalone routing triggers.
    """
    text = _clean(name)
    if not text:
        return []
    if re.search(r"[\u4e00-\u9fff]", text):
        candidates = _keywords([text], limit=limit * 2)
        return [
            item for item in candidates
            if not (
                re.fullmatch(r"[A-Za-z0-9_]+", item)
                and len(item) < 4
            )
        ][:limit]
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if 3 <= len(normalized) <= 80:
        return [normalized]
    return []

def _version_tuple(version: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version or "")
    if not match:
        return (1, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _bump_version(version: str, part: str = "patch") -> str:
    major, minor, patch = _version_tuple(version)
    if part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _content_signature(payload: dict[str, Any]) -> str:
    """Stable hash of every agent-visible field that can change behaviour."""
    content = {
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "domain": payload.get("domain", ""),
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "status": payload.get("status", ""),
        "lenses": sorted(str(item) for item in (payload.get("lenses") or [])),
        "direction": payload.get("direction", ""),
        "books": payload.get("books") or [],
        "book_cards": payload.get("book_cards") or {},
        "frameworks": payload.get("frameworks") or [],
        "claims": payload.get("claims") or [],
        "entities": payload.get("entities") or [],
        "debates": payload.get("debates") or [],
        "source_map": payload.get("source_map") or [],
        "coverage_gaps": payload.get("coverage_gaps") or [],
        "routing": payload.get("routing") or {},
    }
    encoded = json.dumps(
        _canonical(content), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _resolve_books(store: Store, identifiers: Iterable[str]) -> list[dict[str, Any]]:
    books = store.list_books()
    learned = store.learned_book_ids()
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in identifiers:
        needle = _clean(raw)
        if not needle:
            continue
        matches = [
            book for book in books
            if book["book_id"] == needle
            or book["title"].lower() == needle.lower()
            or needle.lower() in book["title"].lower()
        ]
        if not matches:
            raise ValueError(f"unknown book identifier: {needle}")
        exact = [book for book in matches if book["book_id"] == needle or book["title"].lower() == needle.lower()]
        if not exact and len(matches) > 1:
            options = ", ".join(f"{item['title']} ({item['book_id']})" for item in matches[:6])
            raise ValueError(f"ambiguous book identifier: {needle}; candidates: {options}")
        book = (exact or matches)[0]
        if book["book_id"] in seen:
            continue
        if book["book_id"] not in learned:
            raise ValueError(f"book is not learned/verified and cannot enter a capability pack: {book['title']} ({book['book_id']})")
        seen.add(book["book_id"])
        resolved.append(book)
    return resolved


def _auto_books(store: Store, preset: dict[str, Any], lenses: list[str], direction: str, max_books: int) -> list[dict[str, Any]]:
    if preset.get("book_titles"):
        titled: list[dict[str, Any]] = []
        seen: set[str] = set()
        for title in preset["book_titles"]:
            try:
                matches = _resolve_books(store, [title])
            except ValueError:
                continue
            for book in matches:
                if book["book_id"] not in seen:
                    seen.add(book["book_id"])
                    titled.append(book)
        if titled:
            return titled[: max(1, max_books)]
    learned = store.learned_book_ids()
    selected = select_books(store, direction, lenses, direction, limit=max(1, max_books))
    by_id = {book["book_id"]: book for book in store.list_books()}
    books = [
        by_id[item["book_id"]]
        for item in selected
        if item.get("book_id") in by_id and item.get("book_id") in learned
    ]
    if books:
        return books[: max(1, max_books)]
    learned = store.learned_book_ids()
    fallback = [
        book for book in store.list_books()
        if book["book_id"] in learned and set(lenses).intersection(set(book.get("disciplines", [])))
    ]
    return fallback[: max(1, max_books)]


def _framework_summary(framework: dict[str, Any], book_title: str) -> dict[str, Any]:
    return {
        "framework_id": framework.get("framework_id", ""),
        "book_id": framework.get("book_id", ""),
        "book_title": book_title,
        "name": framework.get("name", "Untitled framework"),
        "one_liner": framework.get("one_liner", ""),
        "lenses": list(framework.get("lenses") or []),
        "confidence": framework.get("confidence", "medium"),
        "status": framework.get("status", "draft"),
        "applicable_when": list(framework.get("applicable_when") or []),
        "failure_modes": list(framework.get("failure_modes") or []),
        "keywords": _trigger_keywords(framework.get("name", "")),
    }


def _claims_for_books(store: Store, books: list[dict[str, Any]], max_claims: int) -> list[dict[str, Any]]:
    per_book = max(3, max_claims // max(len(books), 1))
    rows: list[dict[str, Any]] = []
    for book in books:
        claims = store.list_claims(book_id=book["book_id"], status="active", limit=per_book)
        claims.sort(key=lambda item: (
            -float(item.get("confidence") or 0.0),
            str(item.get("claim_id", "")),
        ))
        for claim in claims:
            rows.append({
                "claim_id": claim.get("claim_id", ""),
                "book_id": book["book_id"],
                "book_title": book["title"],
                "subject": claim.get("subject", ""),
                "predicate": claim.get("predicate", ""),
                "object": claim.get("object", ""),
                "polarity": claim.get("polarity", 1),
                "quote": claim.get("quote", ""),
                "page": claim.get("page"),
                "confidence": claim.get("confidence", 0.0),
            })
    rows.sort(key=lambda item: (
        -float(item.get("confidence") or 0.0),
        str(item.get("book_id", "")),
        str(item.get("claim_id", "")),
    ))
    return rows[: max(1, max_claims)]


def _entities_for_books(store: Store, book_ids: list[str], limit: int = 40) -> list[dict[str, Any]]:
    if not book_ids:
        return []
    placeholders = ",".join("?" for _ in book_ids)
    rows = store.conn.execute(
        "SELECT e.entity_id, e.canonical_name, e.entity_type, e.aliases, e.summary, "
        "COUNT(DISTINCT m.book_id) AS book_count, COUNT(*) AS mentions "
        "FROM entities e JOIN entity_mentions m ON m.entity_id = e.entity_id "
        f"WHERE m.book_id IN ({placeholders}) "
        "GROUP BY e.entity_id ORDER BY book_count DESC, mentions DESC, e.canonical_name LIMIT ?",
        (*book_ids, max(1, limit)),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["aliases"] = json.loads(item.get("aliases") or "[]")
        except (TypeError, json.JSONDecodeError):
            item["aliases"] = []
        result.append(item)
    return result


def _reviewed_conflicts(store: Store, book_ids: list[str], limit: int = 12) -> list[dict[str, Any]]:
    result = []
    for row in store.get_claim_conflicts(book_ids=book_ids, limit=limit):
        result.append({
            "relation": row.get("relation", "contradicts"),
            "review_status": "reviewed",
            "confidence": row.get("confidence", 0.0),
            "note": row.get("note", ""),
            "subject": row.get("src_subject", ""),
            "left": {
                "claim_id": row.get("src_claim_id", ""), "book_id": row.get("src_book_id", ""),
                "book_title": row.get("src_book_title", ""), "quote": row.get("src_quote", ""),
                "page": row.get("src_page"), "polarity": row.get("src_polarity"),
            },
            "right": {
                "claim_id": row.get("dst_claim_id", ""), "book_id": row.get("dst_book_id", ""),
                "book_title": row.get("dst_book_title", ""), "quote": row.get("dst_quote", ""),
                "page": row.get("dst_page"), "polarity": row.get("dst_polarity"),
            },
        })
    return result


def _candidate_debates(claims: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        base_key = "|".join([_clean(claim.get("subject")).lower(), _clean(claim.get("predicate")).lower()])
        if base_key.strip("|"):
            grouped.setdefault(base_key, []).append(claim)
    debates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for items in grouped.values():
        for index, left in enumerate(items):
            for right in items[index + 1:]:
                if left.get("book_id") == right.get("book_id"):
                    continue
                if int(left.get("polarity") or 0) == int(right.get("polarity") or 0):
                    continue
                if _similarity(_clean(left.get("object")).lower(), _clean(right.get("object")).lower()) < 0.45:
                    continue
                pair_ids = sorted([
                    str(left.get("claim_id", "")),
                    str(right.get("claim_id", "")),
                ])
                if len(pair_ids) != 2 or not all(pair_ids):
                    continue
                pair = (pair_ids[0], pair_ids[1])
                if pair in seen:
                    continue
                seen.add(pair)
                debates.append({
                    "relation": "candidate_contradiction",
                    "review_status": "candidate",
                    "confidence": round(min(float(left.get("confidence") or 0.5), float(right.get("confidence") or 0.5)), 3),
                    "note": "same subject/predicate, opposite polarity, similar object; not yet reviewed",
                    "subject": left.get("subject", ""),
                    "left": left,
                    "right": right,
                })
                if len(debates) >= limit:
                    return debates
    return debates


def _source_map(
    books: list[dict[str, Any]],
    frameworks: list[dict[str, Any]],
    limit: int = 40,
    cards: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_book: dict[str, list[dict[str, Any]]] = {}
    for framework in frameworks:
        by_book.setdefault(str(framework.get("book_id", "")), []).append(framework)
    entries: list[dict[str, Any]] = []
    for book in books:
        card = (cards or {}).get(book["book_id"], {}) or {}
        framework_rows = by_book.get(book["book_id"], [])
        entries.append({
            "topic": book["title"],
            "lenses": list(book.get("disciplines") or []),
            "book_ids": [book["book_id"]],
            "framework_ids": [item.get("framework_id", "") for item in framework_rows],
            "keywords": _keywords([book.get("title", ""), " ".join(card.get("key_concepts") or []), " ".join(card.get("best_for") or []), " ".join(card.get("core_questions") or [])]),
        })
    for framework in frameworks:
        entries.append({
            "topic": framework.get("name", ""),
            "lenses": list(framework.get("lenses") or []),
            "book_ids": [framework.get("book_id", "")],
            "framework_ids": [framework.get("framework_id", "")],
            "keywords": list(framework.get("keywords") or []),
        })
    entries.sort(key=lambda item: (-len(item.get("framework_ids") or []), item.get("topic", "")))
    return entries[: max(1, limit)]


def _coverage_gaps(books: list[dict[str, Any]], frameworks: list[dict[str, Any]], claims: list[dict[str, Any]], debates: list[dict[str, Any]], lenses: list[str]) -> list[str]:
    gaps: list[str] = []
    if len(books) < 3:
        gaps.append(f"only {len(books)} books in the pack; cross-book synthesis will be weak")
    covered: set[str] = set()
    for book in books:
        covered.update(book.get("disciplines") or [])
    for framework in frameworks:
        covered.update(framework.get("lenses") or [])
    for lens in lenses:
        if lens not in covered:
            gaps.append(f"no book or framework covers lens: {lens}")
    if not frameworks:
        gaps.append("no frameworks; the pack has evidence but no procedure")
    if not claims:
        gaps.append("no extracted claims; source coverage is thin")
    if not debates:
        gaps.append("no cross-book conflicts detected; this may be extraction coverage, not agreement")
    return gaps

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_pack_md(pack: dict[str, Any]) -> str:
    books = pack.get("books") or []
    frameworks = pack.get("frameworks") or []
    debates = pack.get("debates") or []
    gaps = pack.get("coverage_gaps") or []
    lines = [
        f"# {pack.get('title') or pack.get('domain')}",
        "",
        f"> 领域能力包 `{pack.get('domain')}` · version `{pack.get('version')}` · status `{pack.get('status')}`",
        "",
        "> 这是生成文件。个人补充请写在同目录的 `LOCAL.md`；重新构建不会覆盖它。",
        "",
        "## 何时使用",
        "",
        "当问题涉及以下任一主题时加载本包：",
        "",
        _bullets((pack.get("routing") or {}).get("triggers") or []),
        "",
        "## 不用于",
        "",
        "- 单纯的书本摘要或作者角色扮演。",
        "- 没有书库证据、只靠常识就能回答的问题。",
        "- 需要实时行情、最新法规原文或未入库数据的问题；先提示用户补充来源。",
        "",
        "## 推理协议（必须按顺序走）",
        "",
        "1. `事件拆解`：拆成主体、约束、机制、时间尺度。",
        "2. `选择镜头`：说明本问题需要哪些 lens，以及为什么。",
        "3. `选择框架`：从 `frameworks.md` 选 1–3 个框架，写出适用条件。",
        "4. `执行步骤`：按框架的 inputs/steps/outputs 真走一遍，不得只引用结论。",
        "5. `跨书对照`：至少找一本支持、一本限制或反对的书；没有就说没有。",
        "6. `冲突处理`：读 `debates.md`；有冲突就并列呈现，不取平均。",
        "7. `边界与证伪`：写清结论在什么条件下失效，以及什么指标会改变判断。",
        "8. `引用`：每个事实句给出书名、章节/页码和原文引用；推断与建议单独标注。",
        "",
        "## 领域概览",
        "",
        f"- 镜头：{', '.join(pack.get('lenses') or [])}",
        f"- 书：{len(books)} 本",
        f"- 框架：{len(frameworks)} 个",
        f"- claims：{len(pack.get('claims') or [])} 条",
        f"- 跨书实体：{len(pack.get('entities') or [])} 个",
        f"- 争议：{len(debates)} 条",
        "",
        "## 书与框架的对应",
        "",
        "| 书 | 学科 | 框架数 |",
        "| --- | --- | ---: |",
    ]
    for book in books:
        count = sum(1 for framework in frameworks if framework.get("book_id") == book.get("book_id"))
        lines.append(f"| {book.get('title', '')} | {', '.join(book.get('disciplines') or [])} | {count} |")
    lines.extend([
        "",
        "详细来源见 `sources.md`，框架步骤见 `frameworks.md`，争议见 `debates.md`。",
        "",
        "## 加载顺序（渐进披露）",
        "",
        "1. 先读本文件，确认是否适用。",
        "2. 只加载与问题相关的 1–3 个框架（`frameworks.md`）。",
        "3. 需要出处时再读 `sources.md` / `debates.md`。",
        "4. 回答完成后按 `eval.md` 的 rubric 自评。",
        "",
        "## 当前覆盖缺口",
        "",
        _bullets(gaps, "未检测到明显缺口。"),
        "",
        "## 评估",
        "",
        f"- Golden set：`{pack.get('eval', {}).get('golden_set', 'eval/golden.jsonl')}`",
        f"- 最近一次覆盖率评估：`{pack.get('eval', {}).get('last_score', '未运行')}`",
        "- 覆盖率不等于答案深度；深度仍需要独立 judge 或人工盲评。",
        "",
    ])
    return "\n".join(lines)


def _render_sources_md(pack: dict[str, Any]) -> str:
    lines = [
        f"# {pack.get('title')} · 来源与证据",
        "",
        "> 本文件只列已入库、已验证的书与 claim。引用时必须回到原文核对。",
        "",
        "## 书目",
        "",
        "| 书名 | 作者 | 学科 | 状态 |",
        "| --- | --- | --- | --- |",
    ]
    for book in pack.get("books") or []:
        lines.append(f"| {book.get('title', '')} | {book.get('author', '')} | {', '.join(book.get('disciplines') or [])} | {book.get('status', '')} |")
    lines.extend(["", "## 关键 claims", ""])
    claims = pack.get("claims") or []
    if not claims:
        lines.append("（当前没有 claim 抽取结果；请先运行 `bookcompiler claims build`。）")
    for claim in claims:
        page = f" · p.{claim.get('page')}" if claim.get("page") else ""
        lines.extend([
            f"### {claim.get('subject', '')} · {claim.get('book_title', '')}{page}",
            "",
            f"> {claim.get('quote', '')}",
            "",
            f"- claim_id: `{claim.get('claim_id', '')}` · confidence: {claim.get('confidence', '')}",
            "",
        ])
    lines.extend(["## 跨书实体", ""])
    entities = pack.get("entities") or []
    if not entities:
        lines.append("（没有实体统计。）")
    for entity in entities:
        aliases = ", ".join(entity.get("aliases") or [])
        lines.append(f"- **{entity.get('canonical_name', '')}** · {entity.get('book_count', 0)} 本书 · {entity.get('mentions', 0)} 次提及" + (f" · aliases: {aliases}" if aliases else ""))
    lines.append("")
    return "\n".join(lines)


def _render_frameworks_md(pack: dict[str, Any], details: list[dict[str, Any]]) -> str:
    lines = [f"# {pack.get('title')} · 框架步骤", "", "> 只加载与当前问题相关的框架。不要一次读完。", ""]
    for framework in details:
        lines.extend([
            f"## {framework.get('name', 'Untitled framework')}",
            "",
            f"> {framework.get('one_liner', '')}",
            "",
            f"- book: {framework.get('book_title', '')}",
            f"- lenses: {', '.join(framework.get('lenses') or [])}",
            f"- confidence: {framework.get('confidence', '')} · status: {framework.get('status', '')}",
            "",
            "### Applicable when",
            "",
            _bullets(framework.get("applicable_when") or []),
            "",
            "### Inputs",
            "",
            _bullets(framework.get("inputs") or []),
            "",
            "### Steps",
            "",
            _bullets(framework.get("steps") or []),
            "",
            "### Outputs",
            "",
            _bullets(framework.get("outputs") or []),
            "",
            "### Failure modes",
            "",
            _bullets(framework.get("failure_modes") or []),
            "",
            "### Counterexamples",
            "",
            _bullets(framework.get("counterexamples") or []),
            "",
            "### Source citations",
            "",
        ])
        citations = framework.get("citations") or []
        if not citations:
            lines.append("（无引用；该框架不应被当作已证实结论。）")
        for citation in citations:
            page = f" · p.{citation.get('page')}" if citation.get("page") else ""
            lines.append(f"> {citation.get('quote', '')}")
            lines.append(f"  - {framework.get('book_title', '')}{page}")
        lines.append("")
    return "\n".join(lines)


def _render_debates_md(pack: dict[str, Any]) -> str:
    lines = [
        f"# {pack.get('title')} · 跨书争议",
        "",
        "> 争议不是错误。不要为了让答案顺滑而把两本书的冲突平均掉。",
        "",
    ]
    debates = pack.get("debates") or []
    if not debates:
        lines.extend([
            "当前没有检测到跨书矛盾。",
            "",
            "这**不等于**所有书结论一致；也可能只是 claim 抽取覆盖不足。回答时应明确说“未发现已抽取的冲突”，而不是“学界一致”。",
            "",
        ])
        return "\n".join(lines)
    for index, debate in enumerate(debates, start=1):
        left = debate.get("left") or {}
        right = debate.get("right") or {}
        lines.extend([
            f"## {index}. {debate.get('subject', '')}",
            "",
            f"- relation: {debate.get('relation', '')}",
            f"- review: {debate.get('review_status', '')} · confidence: {debate.get('confidence', '')}",
            f"- note: {debate.get('note', '')}",
            "",
            f"**{left.get('book_title', '')}**" + (f" · p.{left.get('page')}" if left.get("page") else ""),
            "",
            f"> {left.get('quote', '')}",
            "",
            f"**{right.get('book_title', '')}**" + (f" · p.{right.get('page')}" if right.get("page") else ""),
            "",
            f"> {right.get('quote', '')}",
            "",
            "处理要求：说明两者是否真的在同一条件下冲突；给出区分条件；不要只选一个。",
            "",
        ])
    return "\n".join(lines)


def _render_boundaries_md(pack: dict[str, Any], details: list[dict[str, Any]]) -> str:
    lines = [f"# {pack.get('title')} · 边界与失效条件", ""]
    lines.extend(["## 书的局限", ""])
    cards = pack.get("book_cards") or {}
    for book in pack.get("books") or []:
        card = cards.get(book.get("book_id", ""), {}) or {}
        lines.extend([
            f"### {book.get('title', '')}",
            "",
            "**Assumptions**",
            "",
            _bullets(card.get("assumptions") or []),
            "",
            "**Limitations**",
            "",
            _bullets(card.get("limitations") or []),
            "",
            "**Not for**",
            "",
            _bullets(card.get("not_for") or []),
            "",
        ])
    lines.extend(["## 框架失效模式", ""])
    for framework in details:
        lines.extend([
            f"### {framework.get('name', '')}",
            "",
            _bullets(framework.get("failure_modes") or []),
            "",
            "**Counterexamples**",
            "",
            _bullets(framework.get("counterexamples") or []),
            "",
        ])
    return "\n".join(lines)


def _render_eval_md(pack: dict[str, Any]) -> str:
    lines = [
        f"# {pack.get('title')} · 评测",
        "",
        "## 两种评测，不要混为一谈",
        "",
        "1. **覆盖率评测（结构）**：检查期望的书/框架/镜头/冲突是否在包内。零模型调用，适合每次更新后跑。",
        "2. **答案深度评测（judge）**：让独立模型按下面 rubric 打分。它不能替代人工盲评。",
        "",
        "## Rubric（0–10）",
        "",
    ]
    for name, description in RUBRIC:
        lines.append(f"- `{name}`：{description}")
    lines.extend([
        "",
        "## 通过线",
        "",
        "- 总分 ≥ 7.0。",
        "- 任一维度不得低于 5。",
        "- 引用必须可回到原文；发现编造引用直接判失败。",
        "- 只引用一本书时，`cross_book_synthesis` 不得高于 3。",
        "- 没有可证伪条件时，`calibration` 不得高于 5。",
        "",
        "## 运行",
        "",
        "```powershell",
        f"bookcompiler capability eval --domain {pack.get('domain')}",
        "```",
        "",
        "Golden set 使用 JSONL，每行一个事件，字段见 `eval/golden.jsonl`。",
        "",
    ])
    return "\n".join(lines)


def _render_local_md(pack: dict[str, Any]) -> str:
    return (
        f"# {pack.get('title')} · 本地补充\n\n"
        "这个文件不会被重新构建覆盖。可以写：\n\n"
        "- 你自己的判断规则\n"
        "- 某本书的阅读笔记\n"
        "- 希望 agent 下次注意的偏好\n"
        "- 真实案例与结果\n\n"
        "生成文件（`PACK.md`、`frameworks.md`、`sources.md`、`debates.md`、`boundaries.md`、`eval.md`）会被覆盖，请不要直接改它们。\n"
    )


def _render_changelog(pack: dict[str, Any]) -> str:
    """Render one clean changelog document from the pack's history."""
    lines = ["# Changelog", ""]
    history = list(pack.get("history") or [])
    if not history:
        history = [{
            "version": pack.get("version", ""),
            "at": pack.get("updated_at", utc_now()),
            "event": "build",
            "books": len(pack.get("books") or []),
            "frameworks": len(pack.get("frameworks") or []),
            "claims": len(pack.get("claims") or []),
            "diff": {},
        }]
    for entry in history:
        lines.extend([
            f"## {entry.get('version', '')} | {entry.get('at', '')}",
            "",
            f"- event: {entry.get('event', '')}",
            f"- books: {entry.get('books', 0)}",
            f"- frameworks: {entry.get('frameworks', 0)}",
            f"- claims: {entry.get('claims', 0)}",
        ])
        diff = entry.get("diff") or {}
        for key in ("added_books", "removed_books", "added_frameworks", "removed_frameworks"):
            items = diff.get(key) or []
            if items:
                lines.append(f"- {key}: {', '.join(str(item) for item in items)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

# ---------------------------------------------------------------------------
# Build / list / status
# ---------------------------------------------------------------------------

def _pack_dir(domain: str, root: str | Path | None = None) -> Path:
    return packs_root(root) / _safe_domain(domain)


def _load_pack(domain: str, root: str | Path | None = None) -> dict[str, Any] | None:
    path = _pack_dir(domain, root) / "pack.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_index(root: str | Path | None = None) -> dict[str, Any]:
    base = packs_root(root)
    base.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/pack.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(pack, dict):
            continue
        entries.append({
            "domain": pack.get("domain", path.parent.name),
            "title": pack.get("title", path.parent.name),
            "version": pack.get("version", "0.0.0"),
            "status": pack.get("status", "active"),
            "lenses": pack.get("lenses") or [],
            "triggers": (pack.get("routing") or {}).get("triggers") or [],
            "book_count": len(pack.get("books") or []),
            "book_titles": [item.get("title", "") for item in pack.get("books") or []],
            "framework_count": len(pack.get("frameworks") or []),
            "claim_count": len(pack.get("claims") or []),
            "updated_at": pack.get("updated_at", ""),
            "path": str(path.parent),
        })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "root": str(base),
        "total": len(entries),
        "packs": entries,
    }
    _atomic_write(base / "index.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def list_capabilities(root: str | Path | None = None) -> dict[str, Any]:
    """Rebuild the index from pack files so manual edits cannot leave it stale."""
    return {"ok": True, **_write_index(root)}

def capability_status(domain: str = "", root: str | Path | None = None) -> dict[str, Any]:
    if not _clean(domain):
        return list_capabilities(root)
    pack = _load_pack(domain, root)
    if not pack:
        return {"ok": False, "error": f"unknown capability pack: {domain}", "root": str(packs_root(root))}
    directory = _pack_dir(domain, root)
    files = {path.name: path.stat().st_size for path in directory.glob("*") if path.is_file()}
    return {
        "ok": True,
        "domain": pack.get("domain", domain),
        "title": pack.get("title", ""),
        "version": pack.get("version", ""),
        "status": pack.get("status", ""),
        "lenses": pack.get("lenses") or [],
        "books": len(pack.get("books") or []),
        "book_titles": [item.get("title", "") for item in pack.get("books") or []],
        "frameworks": len(pack.get("frameworks") or []),
        "claims": len(pack.get("claims") or []),
        "entities": len(pack.get("entities") or []),
        "debates": len(pack.get("debates") or []),
        "coverage_gaps": pack.get("coverage_gaps") or [],
        "triggers": (pack.get("routing") or {}).get("triggers") or [],
        "eval": pack.get("eval") or {},
        "files": files,
        "path": str(directory),
    }


def build_capability(
    store: Store,
    domain: str,
    *,
    title: str = "",
    description: str = "",
    lenses: list[str] | None = None,
    book_ids: list[str] | None = None,
    direction: str = "",
    max_books: int = 8,
    max_frameworks: int = 40,
    max_claims: int = 60,
    max_entities: int = 40,
    root: str | Path | None = None,
    version: str = "",
    force: bool = False,
) -> dict[str, Any]:
    domain = _safe_domain(domain)
    preset = DOMAIN_PRESETS.get(domain, {})
    lenses = list(dict.fromkeys(
        str(item).strip() for item in (lenses or preset.get("lenses") or []) if str(item).strip()
    ))
    if not lenses:
        raise ValueError("at least one lens is required")
    direction = _clean(direction or preset.get("direction") or "")
    title = _clean(title or preset.get("title") or domain)

    books = _resolve_books(store, book_ids or []) if book_ids else _auto_books(store, preset, lenses, direction, max_books)
    if not books:
        raise ValueError("no learned books selected for this capability pack")
    for book in books:
        book["_card"] = store.get_book_card(book["book_id"]) or {}
    book_ids_resolved = [book["book_id"] for book in books]
    book_titles = {book["book_id"]: book["title"] for book in books}
    book_rows = [
        {
            "book_id": book["book_id"],
            "title": book["title"],
            "author": book.get("author", ""),
            "status": book.get("status", ""),
            "disciplines": list(book.get("disciplines") or []),
            "card_status": (book.get("_card") or {}).get("status", ""),
            "one_line_thesis": (book.get("_card") or {}).get("one_line_thesis", ""),
        }
        for book in books
    ]
    book_cards = {
        book["book_id"]: {
            "assumptions": (book.get("_card") or {}).get("assumptions") or [],
            "limitations": (book.get("_card") or {}).get("limitations") or [],
            "not_for": (book.get("_card") or {}).get("not_for") or [],
        }
        for book in books
    }

    frameworks_all = store.list_frameworks(book_ids=book_ids_resolved)
    frameworks_all.sort(key=lambda item: (
        0 if str(item.get("status", "")).lower() in {"verified", "complete"} else 1,
        {"high": 0, "medium": 1, "low": 2}.get(str(item.get("confidence", "medium")).lower(), 1),
        str(item.get("name", "")),
        str(item.get("framework_id", "")),
    ))
    frameworks = [_framework_summary(item, book_titles.get(item.get("book_id", ""), "")) for item in frameworks_all]
    frameworks = frameworks[: max(1, max_frameworks)]
    framework_ids = {item["framework_id"] for item in frameworks}
    framework_details = [item for item in frameworks_all if item.get("framework_id") in framework_ids][: max(1, max_frameworks)]

    claims = _claims_for_books(store, books, max_claims)
    entities = _entities_for_books(store, book_ids_resolved, max_entities)
    reviewed = _reviewed_conflicts(store, book_ids_resolved, limit=12)
    candidates = _candidate_debates(claims, limit=max(0, 12 - len(reviewed)))
    debates = reviewed + candidates
    coverage_gaps = _coverage_gaps(books, frameworks, claims, debates, lenses)
    source_map = _source_map(
        books,
        frameworks,
        limit=max(20, max_frameworks),
        cards={book["book_id"]: book.get("_card") or {} for book in books},
    )

    triggers = list(dict.fromkeys([
        *(preset.get("triggers") or []),
        *[item for framework in frameworks for item in _trigger_keywords(framework.get("name", ""), limit=4)],
    ]))
    triggers = [item for item in triggers if _clean(item)][:80]

    old = _load_pack(domain, root)
    old_signature = _content_signature(old) if old else ""
    routing_policy = (
        "Auto-select only when one pack is clearly ahead. If two packs are close "
        "or the question is high-stakes, show the candidates and ask. Never load "
        "more than two packs."
    )
    signature_payload = {
        "schema_version": SCHEMA_VERSION,
        "domain": domain,
        "title": title,
        "description": _clean(description or preset.get("description") or ""),
        "status": "active",
        "lenses": lenses,
        "direction": direction,
        "books": book_rows,
        "book_cards": book_cards,
        "frameworks": frameworks,
        "claims": claims,
        "entities": entities,
        "debates": debates,
        "source_map": source_map,
        "coverage_gaps": coverage_gaps,
        "routing": {"triggers": triggers, "policy": routing_policy},
    }
    new_signature = _content_signature(signature_payload)
    old_books = {item.get("book_id", "") for item in (old or {}).get("books", [])}
    new_books = set(book_ids_resolved)
    diff = {
        "added_books": sorted(new_books - old_books),
        "removed_books": sorted(old_books - new_books),
        "added_frameworks": sorted({item["framework_id"] for item in frameworks} - {item.get("framework_id", "") for item in (old or {}).get("frameworks", [])}),
        "removed_frameworks": sorted({item.get("framework_id", "") for item in (old or {}).get("frameworks", [])} - {item["framework_id"] for item in frameworks}),
    }
    if version:
        next_version = version
    elif old and old_signature == new_signature and not force:
        next_version = str(old.get("version") or "1.0.0")
    elif old:
        next_version = _bump_version(str(old.get("version") or "1.0.0"), "minor" if new_books - old_books else "patch")
    else:
        next_version = "1.0.0"

    now = utc_now()
    history = list((old or {}).get("history") or [])
    if not old or old_signature != new_signature or force:
        history.append({
            "version": next_version,
            "at": now,
            "event": "build" if not old else "update",
            "books": len(books),
            "frameworks": len(frameworks),
            "claims": len(claims),
            "diff": diff,
        })
    pack: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "domain": domain,
        "title": title,
        "description": _clean(description or preset.get("description") or ""),
        "version": next_version,
        "status": "active",
        "lenses": lenses,
        "direction": direction,
        "created_at": (old or {}).get("created_at") or now,
        "updated_at": now,
        "books": book_rows,
        "book_cards": book_cards,
        "frameworks": frameworks,
        "claims": claims,
        "entities": entities,
        "debates": debates,
        "source_map": source_map,
        "coverage_gaps": coverage_gaps,
        "routing": {
            "triggers": triggers,
            "policy": routing_policy,
        },
        "eval": {
            "rubric": [name for name, _ in RUBRIC],
            "golden_set": "eval/golden.jsonl",
            "last_score": (old or {}).get("eval", {}).get("last_score"),
        },
        "history": history,
        "stats": {
            "books": len(books),
            "frameworks": len(frameworks),
            "claims": len(claims),
            "entities": len(entities),
            "debates": len(debates),
        },
    }

    directory = _pack_dir(domain, root)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(directory / "pack.json", json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(directory / "PACK.md", _render_pack_md(pack))
    _atomic_write(directory / "sources.md", _render_sources_md(pack))
    _atomic_write(directory / "frameworks.md", _render_frameworks_md(pack, framework_details))
    _atomic_write(directory / "debates.md", _render_debates_md(pack))
    _atomic_write(directory / "boundaries.md", _render_boundaries_md(pack, framework_details))
    _atomic_write(directory / "eval.md", _render_eval_md(pack))
    if not (directory / "LOCAL.md").is_file():
        _atomic_write(directory / "LOCAL.md", _render_local_md(pack))
    golden = directory / "eval" / "golden.jsonl"
    cases = GOLDEN_CASES.get(domain) or []
    default_text = "\n".join(json.dumps(case, ensure_ascii=False) for case in DEFAULT_GOLDEN_CASES) + "\n"
    stale_default = False
    if golden.is_file():
        try:
            stale_default = (
                domain != "political-economy"
                and golden.read_text(encoding="utf-8").strip() == default_text.strip()
            )
        except OSError:
            stale_default = False
    if cases and (not golden.is_file() or stale_default):
        _atomic_write(golden, "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n")
    changelog = directory / "CHANGELOG.md"
    # Rewrite the whole document from history. This is cheap and prevents
    # duplicated headers when appending versions over time.
    _atomic_write(changelog, _render_changelog(pack))
    index = _write_index(root)
    return {
        "ok": True,
        "domain": domain,
        "title": title,
        "version": next_version,
        "path": str(directory),
        "books": len(books),
        "frameworks": len(frameworks),
        "claims": len(claims),
        "entities": len(entities),
        "debates": len(debates),
        "coverage_gaps": coverage_gaps,
        "diff": diff,
        "index": index,
    }


# ---------------------------------------------------------------------------
# Routing / impact / update
# ---------------------------------------------------------------------------

def _all_packs(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = packs_root(root)
    packs: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/pack.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(pack, dict):
            packs.append(pack)
    return packs


def route_capability(store: Store, query: str, lenses: list[str] | None = None, limit: int = 3, root: str | Path | None = None) -> dict[str, Any]:
    query = _clean(query)
    if not query:
        raise ValueError("query is required for capability routing")
    packs = _all_packs(root)
    if not packs:
        return {
            "ok": True,
            "query": query,
            "requested_lenses": [],
            "candidates": [],
            "top": None,
            "selected": None,
            "secondary": None,
            "confidence": 0.0,
            "confidence_note": "heuristic score ratio, not a calibrated probability",
            "margin": 0.0,
            "requires_confirmation": True,
            "confirmation_reason": "no capability packs",
            "policy": "Clear winner: load it automatically. Close scores or high-stakes/ambiguous question: show the candidates and ask the user. Never load more than two packs.",
            "message": "No capability packs found. Build one with `bookcompiler capability build --domain ...`.",
        }
    requested_lenses = [str(item).strip() for item in (lenses or []) if str(item).strip()]
    lowered = query.lower()
    terms = set(query_terms(query))
    try:
        from .entities import detect_entities
        detected = {item.get("canonical_name", "").lower() for item in detect_entities(store, query)}
    except Exception:
        detected = set()

    candidates: list[dict[str, Any]] = []
    for pack in packs:
        score = 0.0
        reasons: list[str] = []
        pack_lenses = set(pack.get("lenses") or [])
        if requested_lenses:
            overlap = pack_lenses.intersection(requested_lenses)
            if overlap:
                score += 3.0 * len(overlap)
                reasons.append("lens match: " + ", ".join(sorted(overlap)))
        for trigger in ((pack.get("routing") or {}).get("triggers") or [])[:80]:
            trigger = str(trigger).strip()
            if trigger and trigger.lower() in lowered:
                score += 2.5
                reasons.append(f"trigger: {trigger}")
        for book in pack.get("books") or []:
            title = str(book.get("title", "")).strip()
            if title and title.lower() in lowered:
                score += 2.0
                reasons.append(f"book: {title}")
        for framework in pack.get("frameworks") or []:
            name = str(framework.get("name", "")).strip()
            if name and name.lower() in lowered:
                score += 1.5
                reasons.append(f"framework: {name}")
        for entity in pack.get("entities") or []:
            name = str(entity.get("canonical_name", "")).strip().lower()
            if name and name in detected:
                score += 2.0
                reasons.append(f"entity: {entity.get('canonical_name', '')}")
        description = (str(pack.get("title", "")) + " " + str(pack.get("description", ""))).lower()
        lexical = sum(0.25 for term in terms if len(term) >= 2 and term in description)
        if lexical:
            score += min(2.0, lexical)
            reasons.append("description match")
        candidates.append({
            "domain": pack.get("domain", ""), "title": pack.get("title", ""),
            "version": pack.get("version", ""), "lenses": pack.get("lenses") or [],
            "book_count": len(pack.get("books") or []), "framework_count": len(pack.get("frameworks") or []),
            "score": round(score, 2), "reasons": list(dict.fromkeys(reasons))[:8],
        })
    candidates.sort(key=lambda item: (-item["score"], item["domain"]))
    top = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    margin = (top["score"] if top else 0.0) - (second["score"] if second else 0.0)
    top_score = top["score"] if top else 0.0
    confirmation = bool(top is None or top_score < 5.0 or (second is not None and margin < 2.0))
    confirmation_reason = (
        "no capability packs"
        if top is None
        else "weak match"
        if top_score < 5.0
        else "close scores; ask the user"
        if second is not None and margin < 2.0
        else ""
    )
    confidence = round(top_score / (top_score + 4.0), 2) if top_score else 0.0
    secondary = None
    if not confirmation and second is not None and second["score"] >= 5.0:
        secondary = {
            "domain": second["domain"],
            "title": second["title"],
            "score": second["score"],
            "reasons": second["reasons"],
        }
    return {
        "ok": True, "query": query, "requested_lenses": requested_lenses,
        "candidates": candidates[: max(1, limit)], "top": top,
        "selected": top["domain"] if top and not confirmation else None,
        "secondary": secondary,
        "confidence": confidence,
        "confidence_note": "heuristic score ratio, not a calibrated probability",
        "margin": round(margin, 2),
        "requires_confirmation": confirmation,
        "confirmation_reason": confirmation_reason,
        "policy": "Clear winner: load it automatically. Close scores or high-stakes/ambiguous question: show the candidates and ask the user. Never load more than two packs.",
    }


def capability_impact(store: Store, book_id: str, root: str | Path | None = None) -> dict[str, Any]:
    book = store.get_book(book_id)
    if not book:
        raise ValueError(f"unknown book_id: {book_id}")
    packs = _all_packs(root)
    book_lenses = set(book.get("disciplines") or [])
    book_frameworks = store.list_frameworks(book_ids=[book_id])
    book_framework_ids = {item.get("framework_id", "") for item in book_frameworks}
    entity_rows = store.conn.execute("SELECT DISTINCT entity_id FROM entity_mentions WHERE book_id = ?", (book_id,)).fetchall()
    book_entity_ids = {row["entity_id"] for row in entity_rows}
    claims = store.list_claims(book_id=book_id, status="active", limit=200)
    claim_base_keys = {"|".join([_clean(item.get("subject")).lower(), _clean(item.get("predicate")).lower()]) for item in claims}
    affected: list[dict[str, Any]] = []
    for pack in packs:
        score = 0.0
        reasons: list[str] = []
        pack_book_ids = {item.get("book_id") for item in pack.get("books") or []}
        if book_id in pack_book_ids:
            score += 10.0
            reasons.append("book already in pack")
        overlap = book_lenses.intersection(set(pack.get("lenses") or []))
        if overlap:
            score += 2.0 * len(overlap)
            reasons.append("lens overlap: " + ", ".join(sorted(overlap)))
        pack_framework_ids = {item.get("framework_id", "") for item in pack.get("frameworks") or []}
        framework_overlap = book_framework_ids.intersection(pack_framework_ids)
        if framework_overlap:
            score += 1.0 * len(framework_overlap)
            reasons.append(f"{len(framework_overlap)} framework overlap")
        pack_entity_ids = {item.get("entity_id", "") for item in pack.get("entities") or []}
        entity_overlap = book_entity_ids.intersection(pack_entity_ids)
        if entity_overlap:
            score += min(4.0, 0.5 * len(entity_overlap))
            reasons.append(f"{len(entity_overlap)} entity overlap")
        pack_claim_keys = {"|".join([_clean(item.get("subject")).lower(), _clean(item.get("predicate")).lower()]) for item in pack.get("claims") or []}
        claim_overlap = claim_base_keys.intersection(pack_claim_keys)
        if claim_overlap:
            score += min(4.0, 0.5 * len(claim_overlap))
            reasons.append(f"{len(claim_overlap)} claim-topic overlap")
        if score <= 0:
            continue
        already = book_id in pack_book_ids
        affected.append({
            "domain": pack.get("domain", ""), "title": pack.get("title", ""),
            "version": pack.get("version", ""), "score": round(score, 2), "reasons": reasons,
            "already_includes_book": already, "new_frameworks": len(book_frameworks),
            "new_claims": len(claims), "new_entities": len(book_entity_ids),
            "claim_topic_overlap": len(claim_overlap),
            "requires_review": bool(claim_overlap) and not already,
        })
    affected.sort(key=lambda item: -item["score"])
    return {
        "ok": True,
        "book": {"book_id": book_id, "title": book.get("title", ""), "disciplines": book.get("disciplines") or []},
        "affected_packs": affected,
        "recommended_action": "update affected packs" if affected else "no pack currently needs this book",
        "policy": "Low-risk update (no removed items, no new topic-level conflicts) can be applied automatically. If the book introduces new conflicts or changes core frameworks, show the diff before applying.",
    }


def update_capability(store: Store, domain: str, *, book_ids: list[str] | None = None, apply: bool = False, root: str | Path | None = None) -> dict[str, Any]:
    domain = _safe_domain(domain)
    old = _load_pack(domain, root)
    if not old:
        return {"ok": False, "domain": domain, "applied": False, "error": "pack does not exist yet; use action=build first"}
    existing = [item.get("book_id", "") for item in old.get("books") or []]
    resolved_new = [book["book_id"] for book in _resolve_books(store, book_ids or [])] if book_ids else []
    merged = list(dict.fromkeys([*existing, *resolved_new]))
    proposal = {
        "ok": True, "domain": domain, "applied": False,
        "current_version": old.get("version", ""), "current_books": existing,
        "proposed_books": merged, "added_books": [item for item in merged if item not in existing],
        "removed_books": [item for item in existing if item not in merged],
    }
    if not apply:
        return proposal
    result = build_capability(
        store,
        domain,
        book_ids=merged,
        root=root,
        title=str(old.get("title") or ""),
        description=str(old.get("description") or ""),
        lenses=list(old.get("lenses") or []) or None,
        direction=str(old.get("direction") or ""),
    )
    pack = _load_pack(domain, root) or {}
    return {**proposal, "applied": True, "new_version": result.get("version", ""), "result": result,
            "debates": len(pack.get("debates") or []), "coverage_gaps": pack.get("coverage_gaps") or []}

# ---------------------------------------------------------------------------
# Coverage evaluation
# ---------------------------------------------------------------------------

def _read_cases(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    cases: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            cases.append(item)
    return cases


def evaluate_capability(store: Store, domain: str, *, cases_path: str | Path | None = None, limit: int = 0, root: str | Path | None = None) -> dict[str, Any]:
    domain = _safe_domain(domain)
    pack = _load_pack(domain, root)
    if not pack:
        return {"ok": False, "error": f"unknown capability pack: {domain}"}
    directory = _pack_dir(domain, root)
    path = Path(cases_path).expanduser().resolve() if cases_path else directory / "eval" / "golden.jsonl"
    cases = _read_cases(path)
    if limit and limit > 0:
        cases = cases[:limit]
    if not cases:
        return {"ok": False, "error": f"no evaluation cases found: {path}"}

    book_titles = [str(item.get("title", "")) for item in pack.get("books") or []]
    framework_names = [str(item.get("name", "")) for item in pack.get("frameworks") or []]
    pack_lenses = set(pack.get("lenses") or [])
    trigger_text = " ".join(str(item) for item in ((pack.get("routing") or {}).get("triggers") or []))
    topic_text = " ".join(" ".join(str(keyword) for keyword in (entry.get("keywords") or [])) for entry in pack.get("source_map") or [])
    has_debates = bool(pack.get("debates") or [])

    failures: list[dict[str, Any]] = []
    totals = {"book_coverage": 0.0, "framework_coverage": 0.0, "lens_coverage": 0.0, "topic_coverage": 0.0, "conflict_coverage": 0.0}
    routing_hits = 0
    for case in cases:
        expected_books = [str(item) for item in case.get("expected_books") or []]
        expected_frameworks = [str(item) for item in case.get("expected_frameworks") or []]
        expected_lenses = [str(item) for item in case.get("lenses") or []]
        expected_topics = [str(item) for item in case.get("expected_topics") or []]
        missing_books = [
            expected for expected in expected_books
            if not any(expected.lower() in title.lower() for title in book_titles)
        ]
        missing_frameworks = [
            expected for expected in expected_frameworks
            if not any(expected.lower() in name.lower() for name in framework_names)
        ]
        missing_topics = [
            expected for expected in expected_topics
            if expected.lower() not in (trigger_text + " " + topic_text).lower()
        ]
        book_hit = not missing_books
        framework_hit = not missing_frameworks
        lens_hit = set(expected_lenses).issubset(pack_lenses)
        topic_hit = not missing_topics
        conflict_hit = has_debates if case.get("expected_conflicts") else True
        totals["book_coverage"] += 1.0 if book_hit else 0.0
        totals["framework_coverage"] += 1.0 if framework_hit else 0.0
        totals["lens_coverage"] += 1.0 if lens_hit else 0.0
        totals["topic_coverage"] += 1.0 if topic_hit else 0.0
        totals["conflict_coverage"] += 1.0 if conflict_hit else 0.0
        route = route_capability(store, str(case.get("event", "")), lenses=expected_lenses, limit=2, root=root)
        top_domain = (route.get("candidates") or [{}])[0].get("domain", "")
        secondary_domain = (route.get("secondary") or {}).get("domain", "")
        route_hit = route.get("selected") == domain or top_domain == domain or secondary_domain == domain
        routing_hits += 1 if route_hit else 0
        if not all([book_hit, framework_hit, lens_hit, topic_hit, conflict_hit]):
            failures.append({
                "id": case.get("id", ""), "event": case.get("event", ""),
                "book_hit": book_hit, "framework_hit": framework_hit, "lens_hit": lens_hit,
                "topic_hit": topic_hit, "conflict_hit": conflict_hit,
                "missing_books": missing_books, "missing_frameworks": missing_frameworks,
                "missing_topics": missing_topics,
                "route_top": (route.get("candidates") or [{}])[0].get("domain", ""),
            })
    total = float(len(cases))
    result = {
        "ok": True, "domain": domain, "mode": "coverage",
        "note": "Coverage is structural: it checks whether the pack contains the expected books, frameworks, lenses, topics and conflicts. It is not a blind quality score.",
        "cases": len(cases),
        "scores": {key: round(value / total, 4) for key, value in totals.items()},
        "overall": round(sum(totals.values()) / (total * len(totals)), 4),
        "routing_accuracy": round(routing_hits / total, 4),
        "failures": failures[:50], "path": str(path),
    }
    _atomic_write(directory / "eval" / "last-run.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    pack.setdefault("eval", {})["last_score"] = result["scores"]
    _atomic_write(directory / "pack.json", json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
    _write_index(root)
    return result


def list_presets() -> dict[str, Any]:
    return {
        "ok": True,
        "presets": [
            {
                "domain": key, "title": value.get("title", key),
                "lenses": value.get("lenses", []), "book_titles": value.get("book_titles", []),
                "triggers": value.get("triggers", []),
            }
            for key, value in DOMAIN_PRESETS.items()
        ],
    }


# ---------------------------------------------------------------------------
# Starter golden set: real event archetypes, not synthetic trivia.
# ---------------------------------------------------------------------------

DEFAULT_GOLDEN_CASES: list[dict[str, Any]] = [    {"id": "pe-001", "event": "2013年6月银行间市场“钱荒”，隔夜利率飙升，央行未立即大规模投放流动性。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["基础货币—货币乘数控制链", "央行资产负债表投放渠道"], "expected_topics": ["流动性", "基础货币", "货币乘数"], "expected_conflicts": False},
    {"id": "pe-002", "event": "2014年地方政府债务审计与43号文推动城投平台与政府信用切割。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["土地—财政—金融三位一体", "财权—事权错配压力测试"], "expected_topics": ["地方债", "城投", "财政"], "expected_conflicts": False},
    {"id": "pe-003", "event": "2015年人民币汇率中间价改革后，资本流动与外汇储备出现剧烈变化。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["央行资产负债表投放渠道", "货币供给内生性检验"], "expected_topics": ["汇率", "外汇占款", "流动性"], "expected_conflicts": False},
    {"id": "pe-004", "event": "2015年棚改货币化安置推动房地产去库存，同时改变地方财政与银行信贷结构。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["土地—财政—金融三位一体"], "expected_topics": ["房地产", "土地财政", "信贷"], "expected_conflicts": False},
    {"id": "pe-005", "event": "2016年供给侧改革去产能，上游价格上升而中下游利润受挤压。", "lenses": ["economics", "politics"], "expected_books": ["中国的经济制度"], "expected_frameworks": ["县际竞争激励诊断", "政策归因波动分析"], "expected_topics": ["产业政策", "地方政府", "竞争"], "expected_conflicts": False},
    {"id": "pe-006", "event": "2017年金融去杠杆与资管新规压缩影子银行和同业业务。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["货币供给内生性检验", "基础货币—货币乘数控制链"], "expected_topics": ["去杠杆", "影子银行", "银行信贷"], "expected_conflicts": False},
    {"id": "pe-007", "event": "2018年中美贸易摩擦升级，出口、汇率与产业链政策同时承压。", "lenses": ["economics", "politics"], "expected_books": ["中国近代史"], "expected_frameworks": ["三角外交杠杆测算"], "expected_topics": ["贸易", "外交", "产业政策"], "expected_conflicts": False},
    {"id": "pe-008", "event": "2019年包商银行被接管，银行同业刚兑预期被打破。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["央行资产负债表投放渠道", "货币供给内生性检验"], "expected_topics": ["银行", "流动性", "金融稳定"], "expected_conflicts": False},
    {"id": "pe-009", "event": "2020年疫情冲击下，财政纾困、特别国债与央行流动性投放同时扩张。", "lenses": ["economics", "politics"], "expected_books": ["Principles for Navigating Big Debt Crises", "中央银行与货币供给"], "expected_frameworks": ["Debt Cycle Phase Classifier", "央行资产负债表投放渠道"], "expected_topics": ["财政", "特别国债", "流动性"], "expected_conflicts": False},
    {"id": "pe-010", "event": "2021年房地产“三条红线”实施后，房企融资、土地财政与地方债务联动收紧。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["土地—财政—金融三位一体", "地方政府公司化与软预算约束"], "expected_topics": ["房地产", "土地财政", "地方债"], "expected_conflicts": False},
    {"id": "pe-011", "event": "2021年教培行业整顿，政策目标从市场扩张转向公共服务与公平。", "lenses": ["economics", "politics"], "expected_books": ["当代中国政府与政治"], "expected_frameworks": ["试点—推广的适应性政策过程", "党政体制—条块矩阵"], "expected_topics": ["产业政策", "监管", "条块"], "expected_conflicts": False},
    {"id": "pe-012", "event": "2022年美联储快速加息，人民币汇率承压，资本流动与国内货币政策空间受影响。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["货币供给内生性检验", "央行资产负债表投放渠道"], "expected_topics": ["汇率", "利率", "资本流动"], "expected_conflicts": False},
    {"id": "pe-013", "event": "2022年土地出让收入下滑，地方财政收支矛盾与城投偿债压力上升。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["土地—财政—金融三位一体", "财权—事权错配压力测试"], "expected_topics": ["土地财政", "地方债", "城投"], "expected_conflicts": False},
    {"id": "pe-014", "event": "2022年河南村镇银行事件暴露地方金融监管与银行治理问题。", "lenses": ["economics", "politics"], "expected_books": ["当代中国政府与政治", "中央银行与货币供给"], "expected_frameworks": ["党政体制—条块矩阵", "货币供给内生性检验"], "expected_topics": ["银行", "监管", "金融稳定"], "expected_conflicts": False},
    {"id": "pe-015", "event": "2023年地方政府债务化解一揽子方案推进，特殊再融资债与债务置换扩张。", "lenses": ["economics", "politics"], "expected_books": ["Principles for Navigating Big Debt Crises", "以利为利：财政关系与地方政府行为"], "expected_frameworks": ["Restructuring Leverage Assessment", "财权—事权错配压力测试"], "expected_topics": ["化债", "地方债", "债务周期"], "expected_conflicts": False},
    {"id": "pe-016", "event": "2023年央行降准释放长期流动性，但信贷需求与信用扩张仍然偏弱。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["基础货币—货币乘数控制链", "货币供给内生性检验"], "expected_topics": ["降准", "流动性", "信用扩张"], "expected_conflicts": False},
    {"id": "pe-017", "event": "2024年超长期特别国债发行，财政扩张与地方项目资本金形成联动。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为", "当代中国政府与政治"], "expected_frameworks": ["财权—事权错配压力测试", "党政体制—条块矩阵"], "expected_topics": ["特别国债", "财政", "地方债"], "expected_conflicts": False},
    {"id": "pe-018", "event": "2024年新一轮隐性债务置换推进，城投平台退出与银行资产质量同时受影响。", "lenses": ["economics", "politics"], "expected_books": ["Principles for Navigating Big Debt Crises"], "expected_frameworks": ["Restructuring Leverage Assessment", "Crisis Political-Economy Risk Map"], "expected_topics": ["化债", "城投", "银行"], "expected_conflicts": False},
    {"id": "pe-019", "event": "2024年房地产收储政策推进，地方政府、银行与房企的资产负债表同时调整。", "lenses": ["economics", "politics"], "expected_books": ["Principles for Navigating Big Debt Crises", "以利为利：财政关系与地方政府行为"], "expected_frameworks": ["Beautiful Deleveraging Balance", "土地—财政—金融三位一体"], "expected_topics": ["房地产", "去杠杆", "地方财政"], "expected_conflicts": False},
    {"id": "pe-020", "event": "2024年存款利率下调，银行净息差收窄而居民储蓄行为发生变化。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["基础货币—货币乘数控制链", "货币供给内生性检验"], "expected_topics": ["利率", "银行", "货币供给"], "expected_conflicts": False},
    {"id": "pe-021", "event": "2025年提振消费专项行动，财政补贴、居民收入与地方执行能力共同决定效果。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为", "当代中国政府与政治"], "expected_frameworks": ["财权—事权错配压力测试", "试点—推广的适应性政策过程"], "expected_topics": ["财政", "消费", "地方政府"], "expected_conflicts": False},
    {"id": "pe-022", "event": "2025年民营经济促进法实施，产权保护、市场准入与地方执法一致性成为焦点。", "lenses": ["economics", "politics"], "expected_books": ["中国的经济制度", "当代中国政府与政治"], "expected_frameworks": ["合约约束竞争分析", "党规—国法双重约束"], "expected_topics": ["产权", "法律", "地方政府"], "expected_conflicts": False},
    {"id": "pe-023", "event": "2025年全国统一大市场建设，地方保护、要素流动与央地激励发生冲突。", "lenses": ["economics", "politics"], "expected_books": ["中国的经济制度", "当代中国政府与政治"], "expected_frameworks": ["县际竞争激励诊断", "党政体制—条块矩阵"], "expected_topics": ["统一大市场", "地方政府", "竞争"], "expected_conflicts": False},
    {"id": "pe-024", "event": "2025年人工智能产业政策加码，地方政府补贴、算力投资与重复建设风险并存。", "lenses": ["economics", "politics"], "expected_books": ["中国的经济制度"], "expected_frameworks": ["县际竞争激励诊断", "政策归因波动分析"], "expected_topics": ["产业政策", "地方政府", "投资"], "expected_conflicts": False},
    {"id": "pe-025", "event": "2025年地方政府专项债扩围，项目收益不足与隐性债务风险同时上升。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["财权—事权错配压力测试", "土地—财政—金融三位一体"], "expected_topics": ["专项债", "地方债", "财政"], "expected_conflicts": False},
    {"id": "pe-026", "event": "2025年美联储降息预期变化，全球资本流动与新兴市场汇率重新定价。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["货币供给内生性检验", "央行资产负债表投放渠道"], "expected_topics": ["汇率", "资本流动", "利率"], "expected_conflicts": False},
    {"id": "pe-027", "event": "人口老龄化加深，养老金、医疗支出与地方财政可持续性压力上升。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["财权—事权错配压力测试"], "expected_topics": ["财政", "人口", "地方政府"], "expected_conflicts": False},
    {"id": "pe-028", "event": "地方融资平台转型为市场化国企，政府信用与企业信用边界重新划定。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为", "当代中国政府与政治"], "expected_frameworks": ["地方政府公司化与软预算约束", "党政体制—条块矩阵"], "expected_topics": ["城投", "地方债", "国企"], "expected_conflicts": False},
    {"id": "pe-029", "event": "中央银行使用结构性货币政策工具，流动性投放与特定行业信贷支持相互交织。", "lenses": ["economics", "politics"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["央行资产负债表投放渠道", "基础货币—货币乘数控制链"], "expected_topics": ["货币政策", "流动性", "信贷"], "expected_conflicts": False},
    {"id": "pe-030", "event": "地方财政压力上升时，地方政府通过非税收入、罚没收入和拖欠账款缓解收支缺口。", "lenses": ["economics", "politics"], "expected_books": ["以利为利：财政关系与地方政府行为"], "expected_frameworks": ["地方政府公司化与软预算约束", "财权—事权错配压力测试"], "expected_topics": ["财政", "地方政府", "非税收入"], "expected_conflicts": False},
]

MACRO_GOLDEN_CASES: list[dict[str, Any]] = [
    {"id": "mf-001", "event": "2013年6月银行间市场“钱荒”，隔夜利率飙升，央行未立即大规模投放流动性。", "lenses": ["economics", "finance"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["基础货币—货币乘数控制链", "央行资产负债表投放渠道"], "expected_topics": ["流动性", "基础货币", "货币乘数"], "expected_conflicts": False},
    {"id": "mf-002", "event": "2015年人民币汇率中间价改革后，资本流动与外汇储备出现剧烈变化。", "lenses": ["economics", "finance"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["央行资产负债表投放渠道", "货币供给内生性检验"], "expected_topics": ["汇率", "流动性", "货币供给"], "expected_conflicts": False},
    {"id": "mf-003", "event": "2017年金融去杠杆压缩影子银行和同业业务。", "lenses": ["economics", "finance"], "expected_books": ["信用创造、货币供求与经济结构"], "expected_frameworks": ["货币供给内生性检验", "影子与离岸信用派生"], "expected_topics": ["信贷", "流动性", "金融稳定"], "expected_conflicts": False},
    {"id": "mf-004", "event": "2019年包商银行被接管，银行同业刚兑预期被打破。", "lenses": ["economics", "finance"], "expected_books": ["稳定不稳定的经济：一种金融不稳定视角"], "expected_frameworks": ["流动性—偿付能力判别", "明斯基融资结构脆弱性"], "expected_topics": ["流动性", "银行", "金融稳定"], "expected_conflicts": False},
    {"id": "mf-005", "event": "2020年疫情冲击下，财政纾困、特别国债与央行流动性投放同时扩张。", "lenses": ["economics", "finance"], "expected_books": ["稳定不稳定的经济：一种金融不稳定视角", "中央银行与货币供给"], "expected_frameworks": ["大政府—最后贷款人稳定器与副作用", "央行资产负债表投放渠道"], "expected_topics": ["流动性", "货币政策", "金融稳定"], "expected_conflicts": False},
    {"id": "mf-006", "event": "2021年房地产“三道红线”实施后，房企融资、土地财政与地方债务联动收紧。", "lenses": ["economics", "finance"], "expected_books": ["稳定不稳定的经济：一种金融不稳定视角"], "expected_frameworks": ["明斯基融资结构脆弱性", "投资—利润—债务周期"], "expected_topics": ["信贷", "债务", "金融稳定"], "expected_conflicts": False},
    {"id": "mf-007", "event": "2022年美联储快速加息，人民币汇率承压，资本流动与国内货币政策空间受影响。", "lenses": ["economics", "finance"], "expected_books": ["货币数量、利率调控与政策转型"], "expected_frameworks": ["开放经济政策有效性判别（三元/二元悖论）", "内外均衡的政策搭配（IB-EB）"], "expected_topics": ["汇率", "资本流动", "利率"], "expected_conflicts": False},
    {"id": "mf-008", "event": "2023年央行降准释放长期流动性，银行信贷与货币乘数随之变化。", "lenses": ["economics", "finance"], "expected_books": ["中央银行与货币供给"], "expected_frameworks": ["基础货币—货币乘数控制链", "央行资产负债表投放渠道"], "expected_topics": ["降准", "流动性", "货币供给"], "expected_conflicts": False},
    {"id": "mf-009", "event": "2024年存款利率下调，银行息差收窄，居民资产配置与金融脱媒加速。", "lenses": ["economics", "finance"], "expected_books": ["货币数量、利率调控与政策转型"], "expected_frameworks": ["价格型调控转型条件诊断", "金融脱媒传导诊断"], "expected_topics": ["利率", "银行", "货币政策"], "expected_conflicts": False},
    {"id": "mf-010", "event": "2025年美联储降息预期变化，全球资本流动与新兴市场汇率重新定价。", "lenses": ["economics", "finance"], "expected_books": ["这次不一样：八百年金融危机史", "货币数量、利率调控与政策转型"], "expected_frameworks": ["商品价格—资本流动先导观察", "开放经济政策有效性判别（三元/二元悖论）"], "expected_topics": ["汇率", "资本流动", "利率"], "expected_conflicts": False},
]

LEGAL_GOLDEN_CASES: list[dict[str, Any]] = [
    {"id": "lg-001", "event": "行政机关作出处罚前未告知听证权利，程序是否合法？", "lenses": ["law", "politics"], "expected_books": ["当代中国政府与政治", "Introduction to Logic"], "expected_frameworks": ["党规—国法双重约束", "Deductive Validity Test"], "expected_topics": ["法律", "程序", "合法性"], "expected_conflicts": False},
    {"id": "lg-002", "event": "地方政府规章与上位法冲突，监管机关应如何适用规则？", "lenses": ["law", "politics"], "expected_books": ["当代中国政府与政治", "Introduction to Logic"], "expected_frameworks": ["党规—国法双重约束", "Fallacy Audit with Contextual Exception"], "expected_topics": ["法律", "合法性", "监管"], "expected_conflicts": False},
    {"id": "lg-003", "event": "一项限制经营自由的监管措施是否符合比例原则？", "lenses": ["law", "politics"], "expected_books": ["Introduction to Logic", "通往奴役之路"], "expected_frameworks": ["Definition Stress Test", "Two-Dimensional Argument Diagram"], "expected_topics": ["比例原则", "权利", "法律"], "expected_conflicts": False},
    {"id": "lg-004", "event": "法院在司法审查中如何对待与本案事实不同的先例？", "lenses": ["law", "politics"], "expected_books": ["Introduction to Logic"], "expected_frameworks": ["Refutation by Logical Analogy", "Deductive Validity Test"], "expected_topics": ["司法", "先例", "法律"], "expected_conflicts": False},
    {"id": "lg-005", "event": "程序正义与行政效率发生冲突时，应如何论证取舍？", "lenses": ["law", "politics"], "expected_books": ["Introduction to Logic", "当代中国政府与政治"], "expected_frameworks": ["Expectation-Value Decision Frame", "Two-Dimensional Argument Diagram"], "expected_topics": ["程序", "权利", "法律"], "expected_conflicts": False},
    {"id": "lg-006", "event": "地方政策试点在推广前需要满足哪些合法性条件？", "lenses": ["law", "politics"], "expected_books": ["当代中国政府与政治"], "expected_frameworks": ["试点—推广的适应性政策过程", "党规—国法双重约束"], "expected_topics": ["合法性", "政策", "法律"], "expected_conflicts": False},
    {"id": "lg-007", "event": "紧急状态下限制权利的措施，其边界应如何界定？", "lenses": ["law", "politics"], "expected_books": ["通往奴役之路", "Introduction to Logic"], "expected_frameworks": ["自由主义适应性框架", "Definition Stress Test"], "expected_topics": ["权利", "法律", "监管"], "expected_conflicts": False},
    {"id": "lg-008", "event": "监管处罚决定被质疑说理不足，应如何审查其论证结构？", "lenses": ["law", "politics"], "expected_books": ["Introduction to Logic"], "expected_frameworks": ["Fallacy Audit with Contextual Exception", "Deductive Validity Test"], "expected_topics": ["监管", "处罚", "合规"], "expected_conflicts": False},
]

GOLDEN_CASES: dict[str, list[dict[str, Any]]] = {
    "political-economy": DEFAULT_GOLDEN_CASES,
    "macro-finance": MACRO_GOLDEN_CASES,
    "legal-reasoning": LEGAL_GOLDEN_CASES,
}
