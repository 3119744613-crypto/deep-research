"""文档解析研发报告的独立输入、引用与证据约束。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ResearchError(ValueError):
    """可向用户展示的固定研发输入或报告校验错误；不包含外部原文。"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Comparison(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    approach: str = Field(min_length=1, max_length=3000)
    pros: list[str] = Field(min_length=1, max_length=10)
    cons: list[str] = Field(min_length=1, max_length=10)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class Experiment(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[str] = Field(min_length=1, max_length=20)
    metrics: list[str] = Field(min_length=1, max_length=20)
    acceptance: str = Field(min_length=1, max_length=3000)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class Recommendation(StrictModel):
    text: str = Field(min_length=1, max_length=5000)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class GraphEdge(StrictModel):
    subject: str = Field(min_length=1, max_length=300)
    relation: str = Field(min_length=1, max_length=300)
    object: str = Field(min_length=1, max_length=300)
    kind: Literal["fact", "inference"]
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(max_length=2000)


class ReportBody(StrictModel):
    summary: str = Field(min_length=1, max_length=5000)
    comparisons: list[Comparison] = Field(max_length=3)
    experiments: list[Experiment] = Field(min_length=1, max_length=12)
    recommendation: Recommendation
    assumptions: list[str] = Field(max_length=20)
    gaps: list[str] = Field(max_length=20)
    graph: list[GraphEdge] = Field(max_length=40)
    measurement_status: Literal["not_measured"]


REPORT_SCHEMA = ReportBody.model_json_schema()


def validate_report(value: object, sources: list[dict]) -> dict:
    """只接受已取回的来源；原文匹配不等价于独立事实核实。"""
    try:
        report = ReportBody.model_validate(value).model_dump()
    except ValidationError:
        raise ResearchError(
            "模型报告不符合结构约束，请重试或更换支持 JSON 的模型。"
        ) from None
    source_map = {source["id"]: source for source in sources}
    if not source_map:
        raise ResearchError("未获得可引用证据，不能生成有依据的推荐。")
    references = []
    for item in report["comparisons"] + report["experiments"]:
        references.extend(item["source_ids"])
    references.extend(report["recommendation"]["source_ids"])
    references.extend(edge["source_id"] for edge in report["graph"])
    if any(source_id not in source_map for source_id in references):
        raise ResearchError("模型报告引用了不存在的来源，已拒绝保存。")
    for edge in report["graph"]:
        if edge["quote"] and edge["quote"] not in source_map[edge["source_id"]]["text"]:
            raise ResearchError("图谱原文引句与引用来源不匹配，已拒绝保存。")
        if edge["kind"] == "fact":
            if not edge["quote"].strip():
                raise ResearchError("图谱事实缺少匹配的原文引句，已拒绝保存。")
            edge["verification_status"] = "source_statement_not_independently_verified"
        else:
            edge["verification_status"] = "pending_validation"
    # 限制模型返回的数组文本，避免结构合法但内容超限。
    for item in report["comparisons"]:
        _validate_text_items(item["pros"] + item["cons"])
    for item in report["experiments"]:
        _validate_text_items(item["steps"] + item["metrics"])
    _validate_text_items(report["assumptions"] + report["gaps"])
    return report


def _validate_text_items(items: list[str]) -> None:
    if any(not text.strip() or len(text) > 3000 for text in items):
        raise ResearchError("模型报告含空白或过长内容。")
