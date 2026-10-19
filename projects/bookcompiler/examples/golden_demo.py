from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bookcompiler.analysis import apply_analysis_patch, create_analysis
from bookcompiler.compiler import compile_book
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.render import render_dashboard, render_memo
from bookcompiler.store import Store

DB = ROOT / ".bookcompiler" / "golden-demo.db"
OUT = ROOT / ".bookcompiler" / "golden-analysis.md"
DASH = ROOT / ".bookcompiler" / "golden-dashboard.md"
DB.parent.mkdir(parents=True, exist_ok=True)
if DB.exists():
    DB.unlink()

store = Store(DB)
parsed = parse_book(
    ROOT / "examples" / "sample_book.md",
    title="Policy Shocks: A Minimal Cross-Disciplinary Primer",
    author="BookCompiler demo",
    disciplines=["economics", "politics", "law"],
)
store.add_book(parsed)
book_id = parsed.book_id
chunks = {chunk.chapter_title: chunk for chunk in store.get_chunks(book_id)}


def cite(chapter: str, quote: str) -> dict:
    chunk = chunks[chapter]
    assert quote in chunk.text, f"quote not in source: {quote}"
    return {
        "book_id": book_id,
        "quote": quote,
        "chunk_id": chunk.chunk_id,
        "chapter": chunk.chapter_title,
        "page": chunk.page_start,
    }


CH1 = "Chapter 1: Incentives and Prices"
CH2 = "Chapter 2: Coalitions and Implementation"
CH3 = "Chapter 3: Legal Authority and Risk"

q11 = "A policy shock changes relative prices."
q12 = "When the cost of capital rises, firms delay investment."
q13 = "If the central bank tightens liquidity, banks reprice credit and households reduce spending."
q14 = "A useful analysis asks who bears the cost, which constraints bind, and what second-order effects follow."
q21 = "A regulation can be economically efficient but politically fragile."
q22 = "When veto players oppose the rule, implementation stalls."
q23 = "The government must build a coalition, compensate losers, and sequence the reform."
q24 = "Political feasibility is not the same as economic desirability."
q31 = "A regulator must act within statutory authority."
q32 = "If the rule exceeds jurisdiction, courts may stay it."
q33 = "Unless the law clearly delegates authority, legal risk is high."
q34 = "Legal analysis should separate authority, procedure, rights, liability, and enforceability."

compilation = {
    "book_card": {
        "book_id": book_id,
        "title": "Policy Shocks: A Minimal Cross-Disciplinary Primer",
        "author": "BookCompiler demo",
        "one_line_thesis": "Policy analysis must trace price transmission, coalition feasibility, and legal authority as three separate constraints on the same intervention.",
        "core_questions": [
            "Who bears the cost of a policy shock?",
            "Which constraints bind after the first round of repricing?",
            "Can the government build a coalition and implement the rule?",
            "Does the regulator have clear statutory authority?",
        ],
        "key_concepts": [
            "relative prices",
            "cost of capital",
            "credit repricing",
            "veto players",
            "political feasibility",
            "statutory authority",
            "legal risk",
            "second-order effects",
        ],
        "assumptions": [
            "Policy shocks work through changes in relative prices and binding constraints.",
            "Implementation depends on coalitions and veto players, not only on economic efficiency.",
            "Legal authority is a separate constraint from political support.",
        ],
        "limitations": [
            "The sample book is a minimal teaching text, not an empirical or jurisdiction-specific treatise.",
            "It states conditional transmission paths but gives no quantitative elasticities.",
            "It does not identify concrete institutions, statutes, or court doctrines.",
        ],
        "best_for": [
            "first-pass triage of a policy or regulatory shock",
            "cross-disciplinary hypothesis generation",
            "separating economic desirability from political and legal feasibility",
        ],
        "not_for": [
            "jurisdiction-specific legal advice",
            "quantitative forecasting",
            "replacing primary-source research on current law",
        ],
        "chapter_coverage": [
            {
                "chapter": CH1,
                "summary": "Policy shocks change relative prices; analysts should trace incidence, binding constraints, and second-order effects.",
                "citation": cite(CH1, q11),
            },
            {
                "chapter": CH2,
                "summary": "Economic efficiency does not guarantee implementation; coalitions, veto players, compensation, and sequencing matter.",
                "citation": cite(CH2, q21),
            },
            {
                "chapter": CH3,
                "summary": "Regulators need statutory authority; jurisdiction, procedure, rights, liability, and enforceability must be separated.",
                "citation": cite(CH3, q31),
            },
        ],
        "lenses": ["economics", "politics", "law"],
        "confidence": "medium",
        "status": "verified",
    },
    "frameworks": [
        {
            "framework_id": "golden-price-transmission",
            "book_id": book_id,
            "name": "Price transmission and incidence",
            "one_liner": "A policy shock changes relative prices, so trace who bears the cost and which constraints bind.",
            "lenses": ["economics"],
            "applicable_when": [
                "The policy changes an administered price, funding cost, or credit condition.",
                "The first-round effect may be offset by bank, firm, or household behavior.",
            ],
            "inputs": [
                "The policy instrument and its intended target",
                "Affected prices, quantities, and balance sheets",
                "The constraints that may bind after the first round",
            ],
            "steps": [
                "Identify the relative price or funding cost that changes.",
                "Trace first-round repricing by banks, firms, and households.",
                "Identify who bears the cost and which constraints bind.",
                "Check second-order effects and feedback loops.",
            ],
            "outputs": [
                "A transmission map",
                "A list of winners, losers, and binding constraints",
            ],
            "failure_modes": [
                "The framework is weak when the policy does not change relative prices or when quantitative elasticities are required.",
            ],
            "counterexamples": [
                "A liquidity injection may sit in bank reserves if banks choose not to lend.",
            ],
            "citations": [cite(CH1, q11), cite(CH1, q13), cite(CH1, q14)],
            "related_frameworks": ["golden-coalition-test", "golden-legal-authority"],
            "confidence": "medium",
            "status": "verified",
        },
        {
            "framework_id": "golden-coalition-test",
            "book_id": book_id,
            "name": "Coalition and implementation test",
            "one_liner": "Separate economic desirability from political feasibility by mapping coalitions, veto players, and sequencing.",
            "lenses": ["politics"],
            "applicable_when": [
                "A rule is economically attractive but faces organized opposition.",
                "Implementation requires bargaining, compensation, or sequencing.",
            ],
            "inputs": [
                "The proposed rule and its distributional effects",
                "Supporters, opponents, and veto players",
                "Compensation and sequencing options",
            ],
            "steps": [
                "Map who gains and who loses.",
                "Identify veto players and the points where they can block implementation.",
                "Ask whether losers can be compensated or the reform can be sequenced.",
                "Separate economic desirability from political feasibility.",
            ],
            "outputs": [
                "A coalition map",
                "An implementation-risk judgment",
            ],
            "failure_modes": [
                "The framework is weak when the issue is a technical rule with no organized distributional conflict.",
            ],
            "counterexamples": [
                "A technically efficient rule may fail because a small veto player blocks it.",
            ],
            "citations": [cite(CH2, q21), cite(CH2, q22), cite(CH2, q23), cite(CH2, q24)],
            "related_frameworks": ["golden-price-transmission", "golden-legal-authority"],
            "confidence": "medium",
            "status": "verified",
        },
        {
            "framework_id": "golden-legal-authority",
            "book_id": book_id,
            "name": "Statutory authority and legal risk",
            "one_liner": "Check authority, jurisdiction, procedure, rights, liability, and enforceability before judging a rule.",
            "lenses": ["law"],
            "applicable_when": [
                "A regulator acts through a rule, order, or informal guidance.",
                "The action may exceed jurisdiction or lack clear delegation.",
            ],
            "inputs": [
                "The regulator and the legal instrument",
                "The claimed statutory basis",
                "The procedure followed and the rights affected",
            ],
            "steps": [
                "Identify the statutory source of authority.",
                "Check jurisdiction and procedure.",
                "Separate rights, liability, and enforceability.",
                "Ask whether a court could stay or invalidate the action.",
            ],
            "outputs": [
                "A legal-risk register",
                "A list of missing authority or procedural facts",
            ],
            "failure_modes": [
                "The framework cannot substitute for jurisdiction-specific legal research or advice.",
            ],
            "counterexamples": [
                "A politically popular rule may still be stayed for lack of statutory authority.",
            ],
            "citations": [cite(CH3, q31), cite(CH3, q32), cite(CH3, q33), cite(CH3, q34)],
            "related_frameworks": ["golden-price-transmission", "golden-coalition-test"],
            "confidence": "medium",
            "status": "verified",
        },
    ],
}

result = compile_book(store, book_id, compilation)
errors = [issue for issue in result.issues if issue.severity == "error"]
assert not errors, errors

query = "Central bank cuts reserve requirements while tightening bank lending standards"
lenses = ["economics", "politics", "law"]
proposal = build_proposal(store, "auto", query, lenses)
packet = create_analysis(store, query, lenses, proposal, "auto")

analysis_patch = {
    "hypotheses": [
        {
            "lens": "economics",
            "framework_id": "golden-price-transmission",
            "framework": "Price transmission and incidence",
            "claim": "下调准备金率首先改变银行的资金成本和可贷资金，但若同时收紧放贷标准，政策的第一轮效果是‘流动性改善’而不是‘信贷必然扩张’；只有银行风险偏好和实体信贷需求没有同步恶化时，流动性才会传导到投资和消费。",
            "supporting_evidence": [cite(CH1, q11), cite(CH1, q12), cite(CH1, q13)],
            "status": "supported",
            "confidence": "medium",
        },
        {
            "lens": "politics",
            "framework_id": "golden-coalition-test",
            "framework": "Coalition and implementation test",
            "claim": "政策能否落地取决于银行、借款人、监管机构和地方政府的联盟结构；即使经济上有效率，若受损方是否决玩家，政策也可能被延迟、补偿或缩水。",
            "supporting_evidence": [cite(CH2, q21), cite(CH2, q22), cite(CH2, q24)],
            "status": "supported",
            "confidence": "medium",
        },
        {
            "lens": "law",
            "framework_id": "golden-legal-authority",
            "framework": "Statutory authority and legal risk",
            "claim": "监管机构必须证明准备金工具和放贷标准都在法定授权范围内；若由不同机构实施，授权基础、程序、权利救济和可执行性要分别检查，否则规则可能被法院中止。",
            "supporting_evidence": [cite(CH3, q31), cite(CH3, q32), cite(CH3, q34)],
            "status": "supported",
            "confidence": "medium",
        },
    ],
    "counterevidence": [
        {
            "description": "本书只给出条件性传导路径，没有给出准备金释放与信贷扩张之间的弹性估计，因此不能把‘流动性增加’直接等同于‘信贷增加’。",
            "citation": cite(CH1, q14),
        },
        {
            "description": "经济效率不是政治可行性的替代品；只看经济收益会低估联盟阻力。",
            "citation": cite(CH2, q24),
        },
        {
            "description": "法定授权不清晰时，法院可能中止规则，从而改变政策的有效实施时点。",
            "citation": cite(CH3, q32),
        },
    ],
    "cross_lens_conflicts": [
        {
            "lenses": ["economics", "politics"],
            "description": "经济上可能提高信贷供给，但政治上可能因银行和借款人反对而延迟或缩水。",
            "resolution": "把‘是否值得做’和‘能否做成’分开：先给出经济条件判断，再给出政治可行性条件，不把两者平均成一个分数。",
        },
        {
            "lenses": ["politics", "law"],
            "description": "政治联盟可能支持快速执行，但法定授权不足会使规则被法院中止。",
            "resolution": "把合法性当作独立约束；政治多数不能替代法律授权。",
        },
    ],
    "conclusion": "在给定文本下，最稳妥的判断是条件性的：如果银行资本与风险偏好没有同步恶化，且监管授权清晰、联盟阻力可控，准备金下调更可能改善流动性并部分传导到信贷；如果放贷标准收紧导致银行惜贷，或授权与程序存在瑕疵，则政策可能只改变银行资产负债表，不改变实体信贷。",
    "uncertainty": "需要看到准备金释放规模、银行超额准备金、贷款标准的具体条款、监管机构授权依据，以及银行与借款人的政治反应；这些事实变化会改变结论。",
    "next_checks": [
        "核对准备金工具与放贷标准分别由哪个机构、依据哪条授权实施。",
        "观察银行超额准备金、贷款利差和信贷投放是否同向变化。",
        "识别银行、借款人、地方政府中的否决玩家及其补偿能力。",
        "检查程序、权利救济和可执行性是否足以承受司法审查。",
    ],
    "citations": [
        cite(CH1, q11), cite(CH1, q12), cite(CH1, q13), cite(CH1, q14),
        cite(CH2, q21), cite(CH2, q22), cite(CH2, q23), cite(CH2, q24),
        cite(CH3, q31), cite(CH3, q32), cite(CH3, q33), cite(CH3, q34),
    ],
    "jurisdiction": "Illustrative analysis; no specific jurisdiction or statute is identified in the sample book.",
    "not_legal_advice": True,
    "status": "complete",
}

final = apply_analysis_patch(store, packet.analysis_id, analysis_patch)
OUT.write_text(render_memo(final.to_dict()), encoding="utf-8")
DASH.write_text(render_dashboard(store), encoding="utf-8")
store.close()
print(f"db={DB}")
print(f"book_id={book_id}")
print(f"analysis_id={final.analysis_id}")
print(f"memo={OUT}")
print(f"dashboard={DASH}")
