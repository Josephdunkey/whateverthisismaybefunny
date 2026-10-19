from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Store


# A curated catalogue is intentional.  The goal is not to guess every possible
# book on the web; it is to recognise when a question depends on an authoritative
# primary source that the current library does not contain.
SOURCE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "source_id": "cn-law-pboc",
        "title": "中华人民共和国中国人民银行法",
        "aliases": ["中国人民银行法", "人民银行法", "PBOC Law"],
        "source_type": "law",
        "jurisdiction": "中国",
        "priority": "high",
        "author": "全国人民代表大会",
        "triggers": [
            "中国人民银行",
            "人民银行",
            "央行",
            "降准",
            "存款准备金",
            "准备金率",
            "货币政策",
            "公开市场操作",
            "再贷款",
            "利率走廊",
            "货币供给",
            "基础货币",
            "central bank",
            "pboc",
            "reserve requirement",
            "monetary policy",
            "open market operation",
        ],
        "matched_lenses": ["law", "economics", "finance"],
        "suggested_disciplines": ["law", "finance"],
        "why": (
            "规定中国人民银行职责、货币政策目标与工具边界；分析降准、流动性投放和央行权限时，"
            "二手教材不能替代法条原文。"
        ),
        "official_source": "全国人民代表大会（现行有效文本）；中国人民银行官网政策法规栏目",
        "next_check": "下载并入库《中华人民共和国中国人民银行法》，核对现行有效版本后复核央行权限与货币政策工具边界。",
    },
    {
        "source_id": "cn-law-commercial-bank",
        "title": "中华人民共和国商业银行法",
        "aliases": ["商业银行法", "Commercial Bank Law"],
        "source_type": "law",
        "jurisdiction": "中国",
        "priority": "high",
        "author": "全国人民代表大会",
        "triggers": [
            "商业银行",
            "银行信贷",
            "信贷扩张",
            "信贷",
            "贷款",
            "存款",
            "银行体系",
            "commercial bank",
            "bank lending",
            "bank credit",
            "credit expansion",
        ],
        "matched_lenses": ["law", "economics", "finance"],
        "suggested_disciplines": ["law", "finance"],
        "why": (
            "规定商业银行业务边界、贷款与存款关系以及审慎经营要求；判断银行信贷是否必然扩张，"
            "需要法律约束与监管要求的一手文本。"
        ),
        "official_source": "全国人民代表大会（现行有效文本）",
        "next_check": "下载并入库《中华人民共和国商业银行法》，再复核银行业务边界和信贷投放约束。",
    },
    {
        "source_id": "cn-law-banking-supervision",
        "title": "中华人民共和国银行业监督管理法",
        "aliases": ["银行业监督管理法", "银行监管法", "Banking Supervision Law"],
        "source_type": "law",
        "jurisdiction": "中国",
        "priority": "high",
        "author": "全国人民代表大会",
        "triggers": [
            "金融监管",
            "银行业监督管理",
            "银行监管",
            "监管约束",
            "监管权限",
            "宏观审慎",
            "banking supervision",
            "prudential regulation",
            "macroprudential",
        ],
        "matched_lenses": ["law", "politics", "finance"],
        "suggested_disciplines": ["law", "finance", "public_administration"],
        "why": (
            "规定银行业监管机关的职责、审慎监管措施和处罚边界；分析金融监管约束时，"
            "必须核对监管机关究竟有哪些法定权限。"
        ),
        "official_source": "全国人民代表大会（现行有效文本）；国家金融监督管理总局官网",
        "next_check": "下载并入库《中华人民共和国银行业监督管理法》，再复核监管机关权限与可执行工具。",
    },
    {
        "source_id": "cn-law-budget",
        "title": "中华人民共和国预算法",
        "aliases": ["预算法", "Budget Law"],
        "source_type": "law",
        "jurisdiction": "中国",
        "priority": "high",
        "author": "全国人民代表大会",
        "triggers": [
            "预算法",
            "财政预算",
            "预算执行",
            "预算调整",
            "地方政府债务",
            "地方债",
            "转移支付",
            "财政赤字",
            "预算赤字",
            "债务限额",
            "budget law",
            "fiscal budget",
            "local government debt",
            "transfer payment",
            "deficit",
        ],
        "matched_lenses": ["law", "politics", "economics", "public_finance"],
        "suggested_disciplines": ["law", "public_finance", "economics"],
        "why": (
            "规定预算编制、审批、执行、调整以及地方债务限额的基本规则；分析地方财政激励、"
            "债务扩张和预算约束时需要法条原文。"
        ),
        "official_source": "全国人民代表大会（现行有效文本）；财政部官网",
        "next_check": "下载并入库《中华人民共和国预算法》，再复核地方债务限额、预算调整和转移支付规则。",
    },
    {
        "source_id": "cn-regulation-budget-implementation",
        "title": "中华人民共和国预算法实施条例",
        "aliases": ["预算法实施条例", "Budget Law Implementation Regulations"],
        "source_type": "regulation",
        "jurisdiction": "中国",
        "priority": "medium",
        "author": "国务院",
        "triggers": [
            "预算法实施条例",
            "预算执行",
            "预算调整",
            "预算公开",
            "转移支付",
            "地方政府债务",
            "地方债",
            "债务限额",
            "budget implementation",
            "local government debt",
        ],
        "matched_lenses": ["law", "politics", "economics", "public_finance"],
        "suggested_disciplines": ["law", "public_finance"],
        "why": (
            "把预算法的原则落到预算执行、转移支付、债务管理和监督程序；只读预算法通常不足以判断具体操作权限。"
        ),
        "official_source": "国务院（现行有效文本）；财政部官网",
        "next_check": "下载并入库《中华人民共和国预算法实施条例》，再核对预算执行与地方债务管理的操作规则。",
    },
    {
        "source_id": "cn-law-legislation",
        "title": "中华人民共和国立法法",
        "aliases": ["立法法", "Legislation Law"],
        "source_type": "law",
        "jurisdiction": "中国",
        "priority": "medium",
        "author": "全国人民代表大会",
        "triggers": [
            "立法法",
            "法律依据",
            "立法权限",
            "授权立法",
            "法规制定",
            "合法性审查",
            "法定权限",
            "statutory authority",
            "legislative authority",
            "legal authority",
            "delegated legislation",
        ],
        "matched_lenses": ["law", "politics"],
        "suggested_disciplines": ["law", "politics"],
        "why": (
            "规定法律、行政法规、地方性法规和规章的权限与效力层级；跨学科判断“谁有权做什么”时，"
            "需要一手规则而不是泛泛的合法性讨论。"
        ),
        "official_source": "全国人民代表大会（现行有效文本）",
        "next_check": "下载并入库《中华人民共和国立法法》，再复核事项属于法律、行政法规还是地方性法规权限。",
    },
    {
        "source_id": "cn-policy-local-government-debt",
        "title": "国务院关于加强地方政府性债务管理的意见（国发〔2014〕43号）",
        "aliases": ["国发〔2014〕43号", "地方政府性债务管理的意见", "Local Government Debt Management Opinion"],
        "source_type": "policy",
        "jurisdiction": "中国",
        "priority": "high",
        "author": "国务院",
        "triggers": [
            "地方政府债务",
            "地方政府性债务",
            "地方债",
            "融资平台",
            "城投",
            "隐性债务",
            "土地财政",
            "债务置换",
            "local government debt",
            "financing vehicle",
            "hidden debt",
            "land finance",
        ],
        "matched_lenses": ["politics", "economics", "law", "public_finance"],
        "suggested_disciplines": ["public_finance", "politics", "law"],
        "why": (
            "确立地方政府债务管理、融资平台清理和存量债务处置的政策框架；分析地方融资行为时，"
            "需要正式文件而不是只依赖教材概括。"
        ),
        "official_source": "国务院；财政部官网（检索文号与现行有效状态）",
        "next_check": "下载并入库国发〔2014〕43号，再核对融资平台、存量债务和地方举债约束。",
    },
    {
        "source_id": "cn-regulation-bank-capital",
        "title": "商业银行资本管理办法",
        "aliases": ["资本管理办法", "Bank Capital Measures"],
        "source_type": "regulation",
        "jurisdiction": "中国",
        "priority": "medium",
        "author": "国家金融监督管理总局",
        "triggers": [
            "资本充足率",
            "商业银行资本",
            "风险加权资产",
            "资本监管",
            "资本管理办法",
            "capital adequacy",
            "risk-weighted assets",
            "bank capital",
        ],
        "matched_lenses": ["law", "finance", "economics"],
        "suggested_disciplines": ["finance", "law"],
        "why": (
            "资本充足率是银行扩张信贷的硬约束；分析降准后的信贷传导，需要现行资本监管规则而不是只看流动性。"
        ),
        "official_source": "国家金融监督管理总局（原银保监会）官网（现行有效版本）",
        "next_check": "下载并入库《商业银行资本管理办法》，再复核资本充足率对信贷扩张的约束。",
    },
    {
        "source_id": "cn-regulation-bank-liquidity",
        "title": "商业银行流动性风险管理办法",
        "aliases": ["流动性风险管理办法", "Bank Liquidity Risk Measures"],
        "source_type": "regulation",
        "jurisdiction": "中国",
        "priority": "medium",
        "author": "国家金融监督管理总局",
        "triggers": [
            "流动性覆盖率",
            "净稳定资金比例",
            "流动性风险",
            "流动性监管",
            "liquidity coverage ratio",
            "net stable funding ratio",
            "liquidity risk",
        ],
        "matched_lenses": ["law", "finance", "economics"],
        "suggested_disciplines": ["finance", "law"],
        "why": (
            "流动性覆盖率和净稳定资金比例约束银行资产负债结构；降准释放流动性不等于银行必然放贷。"
        ),
        "official_source": "国家金融监督管理总局（原银保监会）官网（现行有效版本）",
        "next_check": "下载并入库《商业银行流动性风险管理办法》，再复核流动性指标对信贷投放的约束。",
    },
)


def _normalize_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").lower())


def _title_variants(source: dict[str, Any]) -> list[str]:
    values = [source.get("title", "")]
    values.extend(source.get("aliases", []))
    variants: list[str] = []
    for value in values:
        normalized = _normalize_title(value)
        if len(normalized) >= 4 and normalized not in variants:
            variants.append(normalized)
    return variants


def _is_in_library(source: dict[str, Any], library_titles: list[str]) -> bool:
    variants = _title_variants(source)
    for title in library_titles:
        normalized = _normalize_title(title)
        if not normalized:
            continue
        for variant in variants:
            if variant in normalized or normalized in variant:
                return True
    return False


def _matched_terms(source: dict[str, Any], text: str) -> list[str]:
    lowered = (text or "").lower()
    matches: list[str] = []
    for term in source.get("triggers", []):
        if term and term.lower() in lowered:
            matches.append(term)
    return matches


def _ingest_hint(source: dict[str, Any]) -> str:
    disciplines = " ".join(
        f"--discipline {value}" for value in source.get("suggested_disciplines", [])
    )
    return (
        f'bookcompiler ingest "PATH_TO_DOWNLOADED_FILE" '
        f'--title "{source["title"]}" --author "{source.get("author", "Unknown")}" '
        f"{disciplines}".rstrip()
    )


def recommend_sources(
    store: "Store",
    query: str,
    lenses: list[str] | None = None,
    direction: str = "",
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return authoritative sources that match the question but are absent.

    This function never downloads anything.  It only turns a detected gap into
    an actionable download/ingest instruction for the user or calling agent.
    Exact-title matching deliberately checks every ingested book, including
    books that have not been deeply compiled yet: asking the user to download a
    statute they already imported would be confusing.
    """

    lenses = lenses or []
    haystack = " ".join(part for part in [query, direction] if part)
    if not haystack.strip():
        return []
    library_titles = [str(book.get("title", "")) for book in store.list_books()]
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    for order, source in enumerate(SOURCE_CATALOG):
        matched = _matched_terms(source, haystack)
        if not matched:
            continue
        if _is_in_library(source, library_titles):
            continue
        overlap = sorted(set(lenses).intersection(source.get("matched_lenses", [])))
        priority_rank = 0 if source.get("priority") == "high" else 1
        ranked.append(
            (
                priority_rank,
                -len(matched),
                order,
                {
                    "source_id": source["source_id"],
                    "title": source["title"],
                    "source_type": source["source_type"],
                    "jurisdiction": source["jurisdiction"],
                    "priority": source["priority"],
                    "action": "download_and_ingest",
                    "why": source["why"],
                    "reason": source["why"],
                    "matched_terms": matched,
                    "matched_lenses": overlap or list(source.get("matched_lenses", [])),
                    "suggested_disciplines": list(source.get("suggested_disciplines", [])),
                    "official_source": source["official_source"],
                    "version_note": "请使用官方现行有效版本，并记录公布或修订日期。",
                    "ingest_hint": _ingest_hint(source),
                    "next_check": source["next_check"],
                    "in_library": False,
                },
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in ranked[: max(0, limit)]]