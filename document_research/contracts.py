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


class AnswerClaim(StrictModel):
    text: str = Field(min_length=1, max_length=5000)
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=2000)


class AnswerBody(StrictModel):
    answer: list[AnswerClaim] = Field(max_length=8)
    gaps: list[str] = Field(max_length=20)
    graph: list[GraphEdge] = Field(max_length=40)


REPORT_SCHEMA = ReportBody.model_json_schema()
ANSWER_SCHEMA = AnswerBody.model_json_schema()


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
    _validate_graph(report, source_map)
    # 限制模型返回的数组文本，避免结构合法但内容超限。
    for item in report["comparisons"]:
        _validate_text_items(item["pros"] + item["cons"])
    for item in report["experiments"]:
        _validate_text_items(item["steps"] + item["metrics"])
    _validate_text_items(report["assumptions"] + report["gaps"])
    return report


def validate_answer(value: object, sources: list[dict]) -> dict:
    """逐条答案必须附已有来源中的连续引句；不宣称自动完成语义核实。"""
    try:
        answer = AnswerBody.model_validate(value).model_dump()
    except ValidationError:
        raise ResearchError(
            "模型回答不符合结构约束，请重试或更换支持 JSON 的模型。"
        ) from None
    source_map = {source["id"]: source for source in sources}
    references = [item["source_id"] for item in answer["answer"]]
    references.extend(edge["source_id"] for edge in answer["graph"])
    if any(source_id not in source_map for source_id in references):
        raise ResearchError("模型回答引用了不存在的来源，已拒绝保存。")
    for claim in answer["answer"]:
        if not claim["text"].strip() or not claim["quote"].strip():
            raise ResearchError("模型回答缺少正文或原文引句，已拒绝保存。")
        if claim["quote"] not in source_map[claim["source_id"]]["text"]:
            raise ResearchError("回答原文引句与引用来源不匹配，已拒绝保存。")
    _validate_text_items(answer["gaps"])
    if not answer["answer"] and not answer["gaps"]:
        raise ResearchError("没有可引用回答时，必须说明证据缺口。")
    _validate_graph(answer, source_map)
    answer["mode"] = "answer"
    return answer


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_graph(result: dict, source_map: dict[str, dict]) -> None:
    """过滤缺少可定位端点的边；关系本身仍需用户核对，不做语义蕴含判断。"""
    edges = result["graph"]
    # 先检查所有非空引句，避免不受支持的端点掩盖伪造来源文本。
    for edge in edges:
        if (
            edge["quote"].strip()
            and edge["quote"] not in source_map[edge["source_id"]]["text"]
        ):
            raise ResearchError("图谱原文引句与引用来源不匹配，已拒绝保存。")
    supported = []
    seen = set()
    unsupported_count = 0
    duplicate_count = 0
    for edge in edges:
        quote = _normalized_text(edge["quote"])
        subject = _normalized_text(edge["subject"])
        relation = _normalized_text(edge["relation"])
        object_ = _normalized_text(edge["object"])
        if (
            not quote
            or not subject
            or not relation
            or not object_
            or subject not in quote
            or object_ not in quote
        ):
            unsupported_count += 1
            continue
        # 不同来源或不同引句保留各自的证据；相同边的事实/推断也不合并。
        signature = (subject, relation, object_, edge["kind"], edge["source_id"], quote)
        if signature in seen:
            duplicate_count += 1
            continue
        seen.add(signature)
        edge["verification_status"] = (
            "source_statement_not_independently_verified"
            if edge["kind"] == "fact"
            else "pending_validation"
        )
        edge["grounding_status"] = "endpoints_in_quote"
        supported.append(edge)
    result["graph"] = supported
    result["graph_removed_count"] = unsupported_count + duplicate_count
    result["graph_warnings"] = []
    if unsupported_count:
        result["graph_warnings"].append(
            f"已移除 {unsupported_count} 条缺少原文引句、有效关系或可定位主体/客体的图谱关系。"
        )
    if duplicate_count:
        result["graph_warnings"].append(f"已合并 {duplicate_count} 条重复的图谱关系。")


def _validate_text_items(items: list[str]) -> None:
    if any(not text.strip() or len(text) > 3000 for text in items):
        raise ResearchError("模型报告含空白或过长内容。")
