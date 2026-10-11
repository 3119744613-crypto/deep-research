"""合成证据的词面校验；不把词面匹配当作模型关系语义正确的证明。"""

from copy import deepcopy

import pytest

from document_research.contracts import (
    ANSWER_SCHEMA,
    ResearchError,
    validate_answer,
    validate_report,
)

TEXT = "合成需求：表格包含跨行合并单元格。Docling  supports\nTables."
SOURCES = [{"id": "S1", "text": TEXT}, {"id": "S2", "text": TEXT}]


def edge(**changes):
    return {
        "subject": "表格",
        "relation": "包含",
        "object": "跨行合并单元格",
        "kind": "fact",
        "source_id": "S1",
        "quote": "表格包含跨行合并单元格",
        **changes,
    }


def report(graph):
    return {
        "summary": "合成报告，未实测。",
        "comparisons": [],
        "experiments": [
            {
                "name": "核对样本",
                "steps": ["由人工核对样本"],
                "metrics": ["人工核对数量"],
                "acceptance": "待确认",
                "source_ids": ["S1"],
            }
        ],
        "recommendation": {"text": "待核对样本。", "source_ids": ["S1"]},
        "assumptions": [],
        "gaps": ["未执行解析实验"],
        "graph": graph,
        "measurement_status": "not_measured",
    }


def answer(**changes):
    return {
        "answer": [
            {
                "text": "合成需求包含跨行合并单元格。",
                "source_id": "S1",
                "quote": "表格包含跨行合并单元格",
            }
        ],
        "gaps": [],
        "graph": [],
        **changes,
    }


@pytest.mark.parametrize("kind", ["fact", "inference"])
@pytest.mark.parametrize(
    "changes",
    [
        {"quote": ""},
        {"quote": " \t"},
        {"subject": "Unstructured"},
        {"object": "Docling、PaddleOCR、Unstructured"},
        {"relation": " \t"},
        {"subject": " \t"},
        {"object": " \t"},
    ],
)
def test_unsupported_graph_edges_are_removed_not_report_content(kind, changes):
    result = validate_report(report([edge(kind=kind, **changes)]), SOURCES)
    assert result["graph"] == []
    assert result["graph_removed_count"] == 1
    assert len(result["graph_warnings"]) == 1
    assert "已移除 1 条" in result["graph_warnings"][0]
    assert result["experiments"] and result["recommendation"]


def test_known_tool_names_inference_cannot_use_unrelated_real_quote():
    # 回归真实联调暴露的模式：合法原文引句并不能支持其中未出现的工具名。
    sources = [{"id": "S1", "text": "测试主题：文档解析中的复杂表格识别。"}]
    output = answer(
        answer=[],
        gaps=["缺少候选工具资料"],
        graph=[
            edge(
                subject="文档解析中的复杂表格识别",
                relation="需在独立数据集上对照验证",
                object="Docling、PaddleOCR、Unstructured",
                kind="inference",
                quote="测试主题：文档解析中的复杂表格识别。",
            )
        ],
    )
    result = validate_answer(output, sources)
    assert result["graph"] == []
    assert result["graph_removed_count"] == 1
    assert result["gaps"] == ["缺少候选工具资料"]


def test_graph_normalizes_endpoint_case_and_whitespace_but_not_source_quote():
    result = validate_report(
        report(
            [
                edge(
                    subject="docling supports",
                    object="TABLES",
                    relation="mentions",
                    quote="Docling  supports\nTables",
                )
            ]
        ),
        SOURCES,
    )
    assert result["graph"][0]["grounding_status"] == "endpoints_in_quote"
    assert result["graph"][0]["quote"] == "Docling  supports\nTables"
    assert result["graph_removed_count"] == 0
    assert result["graph_warnings"] == []


def test_graph_deduplicates_same_evidence_but_preserves_distinct_provenance_and_kind():
    result = validate_report(
        report([edge(), edge(), edge(source_id="S2"), edge(kind="inference")]),
        SOURCES,
    )
    assert len(result["graph"]) == 3
    assert result["graph_removed_count"] == 1
    assert result["graph_warnings"] == ["已合并 1 条重复的图谱关系。"]
    assert [item["source_id"] for item in result["graph"]] == ["S1", "S2", "S1"]
    assert result["graph"][2]["verification_status"] == "pending_validation"


@pytest.mark.parametrize(
    "validator,factory",
    [(validate_report, report), (validate_answer, lambda graph: answer(graph=graph))],
)
def test_unknown_graph_source_fails_even_when_edge_would_be_removed(validator, factory):
    with pytest.raises(ResearchError, match="不存在的来源"):
        validator(factory([edge(source_id="invented", subject="unknown")]), SOURCES)


@pytest.mark.parametrize("quote", ["invented", "Docling supports Tables"])
def test_fabricated_or_reformatted_graph_quote_fails_before_endpoint_filtering(quote):
    with pytest.raises(ResearchError, match="原文引句"):
        validate_report(report([edge(subject="unknown", quote=quote)]), SOURCES)


def test_answer_claims_have_retrieved_quotes_and_shared_graph_grounding():
    original = answer(graph=[edge(), edge(object="unsupported")])
    before = deepcopy(original)
    result = validate_answer(original, SOURCES)
    assert result["mode"] == "answer"
    assert result["answer"] == before["answer"]
    assert len(result["graph"]) == 1
    assert result["graph_removed_count"] == 1
    assert result["graph_warnings"]
    assert original == before


def test_answer_abstains_with_explicit_gaps_without_sources():
    result = validate_answer(answer(answer=[], gaps=["没有返回可引用资料"]), [])
    assert result["answer"] == []
    assert result["gaps"] == ["没有返回可引用资料"]
    assert result["mode"] == "answer"


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"source_id": "invented"}, "不存在的来源"),
        ({"quote": "文档里没有的话"}, "原文引句"),
        ({"quote": "Docling supports Tables"}, "原文引句"),
        ({"quote": " "}, "原文引句"),
        ({"text": " "}, "正文"),
        ({"quote": ""}, "结构约束"),
    ],
)
def test_answer_claims_fail_closed_on_missing_or_fabricated_provenance(changes, match):
    output = answer()
    output["answer"][0].update(changes)
    with pytest.raises(ResearchError, match=match):
        validate_answer(output, SOURCES)


@pytest.mark.parametrize(
    "output",
    [
        answer(answer=[], gaps=[]),
        answer(answer=[], gaps=[" "]),
        answer(answer=[]),
    ],
)
def test_empty_answer_cannot_hide_evidence_gaps(output):
    with pytest.raises(ResearchError):
        validate_answer(output, SOURCES)


@pytest.mark.parametrize("graph", [[], [edge()]])
def test_claims_or_graph_without_retrieved_sources_are_rejected(graph):
    output = answer(graph=graph)
    if graph:
        output["answer"] = []
        output["gaps"] = ["资料不足"]
    with pytest.raises(ResearchError, match="不存在的来源"):
        validate_answer(output, [])


def test_answer_schema_restricts_claim_count_and_forbids_model_added_sources():
    assert ANSWER_SCHEMA["properties"]["answer"]["maxItems"] == 8
    claim = answer()["answer"][0]
    for output in (answer(answer=[claim] * 9), answer(sources=SOURCES)):
        with pytest.raises(ResearchError, match="结构约束"):
            validate_answer(output, SOURCES)


def test_matching_endpoints_do_not_change_semantic_verification_status():
    # 端点有词面依据仍不证明关系成立；保留明确的未独立核实/待验证状态。
    result = validate_answer(answer(graph=[edge(relation="contradicts")]), SOURCES)
    assert result["graph"][0]["verification_status"] == (
        "source_statement_not_independently_verified"
    )
