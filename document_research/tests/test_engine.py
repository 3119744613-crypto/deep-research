"""合成普通软件文档用例；验证边界，不声称真实模型或实验通过。"""

import asyncio
import copy
import json

import pytest

from document_research.contracts import ResearchError
from document_research.engine import Engine, EngineNotConfiguredError, prepare_sources
from document_research.providers import ProviderError

CONFIG = {
    "model": {
        "base_url": "https://model.example/v1",
        "api_key": "synthetic",
        "model": "synthetic",
    },
    "zhipu": {
        "api_key": "synthetic-zhipu",
        "libraries": {"alice": [{"id": "kb-a", "name": "Fixture"}]},
    },
}
TASK = {
    "id": "task-a",
    "owner": "alice",
    "problem": "复杂表格解析准确率不足",
    "library_ids": ["local-a"],
    "parser_version": "synthetic-1",
    "expected_result": "合并单元格结构一致",
    "constraints": "本地 CPU",
    "allow_external_model": True,
    "allow_public": False,
    "public_query": "",
}
LOCAL = {
    "id": "chunk-a",
    "document_id": "doc-a",
    "library_id": "local-a",
    "origin": "local",
    "title": "合成需求",
    "text": "合成需求：表格包含跨行合并单元格。",
    "source_url": None,
    "page": 2,
}


def report():
    return {
        "summary": "合成报告；未实测。",
        "comparisons": [
            {
                "name": "Docling",
                "approach": "待验证的表格结构提取",
                "pros": ["可进行针对性验证"],
                "cons": ["本样本尚未实测"],
                "source_ids": ["S1"],
            }
        ],
        "experiments": [
            {
                "name": "合并单元格实验",
                "steps": ["冻结版本、标注样本后运行"],
                "metrics": ["结构正确率 = 正确样本数 / 样本总数"],
                "acceptance": "阈值待用户确认",
                "source_ids": ["S1"],
            }
        ],
        "recommendation": {
            "text": "待验证建议：先完成基线对照。",
            "source_ids": ["S1"],
        },
        "assumptions": [],
        "gaps": ["缺少实测数据"],
        "graph": [
            {
                "subject": "合成样本",
                "relation": "包含",
                "object": "跨行合并单元格",
                "kind": "fact",
                "source_id": "S1",
                "quote": "表格包含跨行合并单元格",
            },
            {
                "subject": "合并单元格",
                "relation": "可能增加",
                "object": "结构提取难度",
                "kind": "inference",
                "source_id": "S1",
                "quote": "",
            },
        ],
        "measurement_status": "not_measured",
    }


class SyntheticProviders:
    def __init__(self):
        self.calls = []
        self.output = report()
        self.remote = []
        self.public = []
        self.warnings = []

    async def retrieve_zhipu(self, key, ids, query, authorize):
        authorize()
        self.calls.append(("zhipu", ids, query))
        authorize()
        return self.remote

    async def public_sources(self, query, authorize):
        authorize()
        self.calls.append(("public", query))
        authorize()
        return self.public, self.warnings

    async def model_report(self, config, messages, authorize):
        authorize()
        self.calls.append(("model", messages))
        authorize()
        return self.output


def run(engine, task=None, local=None, authorize=lambda: None):
    return asyncio.run(
        engine.run(
            copy.deepcopy(task or TASK),
            copy.deepcopy([LOCAL] if local is None else local),
            authorize,
        )
    )


def test_sourced_report_and_graph_verification_are_honest():
    providers = SyntheticProviders()
    result = run(Engine(lambda: CONFIG, providers))
    assert result["measurement_status"] == "not_measured"
    assert (
        result["graph"][0]["verification_status"]
        == "source_statement_not_independently_verified"
    )
    assert result["graph"][1]["verification_status"] == "pending_validation"
    assert result["sources"][0]["original_id"] == "chunk-a"
    assert result["sources"][0]["page"] == 2
    assert [call[0] for call in providers.calls] == ["model"]
    assert "未运行解析实验" in result["warnings"][-1]


def test_no_model_or_no_consent_never_falls_back_to_fake_report():
    providers = SyntheticProviders()
    with pytest.raises(EngineNotConfiguredError):
        run(Engine(dict, providers))
    with pytest.raises(PermissionError):
        run(Engine(lambda: CONFIG, providers), {**TASK, "allow_external_model": False})
    assert providers.calls == []


def test_selected_library_is_enforced_even_for_injected_local_sources():
    providers = SyntheticProviders()
    with pytest.raises(PermissionError):
        run(Engine(lambda: CONFIG, providers), {**TASK, "library_ids": []})
    assert providers.calls == []


def test_no_evidence_cannot_produce_affirmative_recommendation():
    providers = SyntheticProviders()
    with pytest.raises(ResearchError, match="未获得可引用证据"):
        run(Engine(lambda: CONFIG, providers), {**TASK, "library_ids": []}, [])
    assert providers.calls == []


@pytest.mark.parametrize(
    "section", ["comparisons", "experiments", "recommendation", "graph"]
)
def test_unknown_source_ids_rejected_in_every_section(section):
    providers = SyntheticProviders()
    if section == "recommendation":
        providers.output[section]["source_ids"] = ["S-fabricated"]
    elif section == "graph":
        providers.output[section][0]["source_id"] = "S-fabricated"
    else:
        providers.output[section][0]["source_ids"] = ["S-fabricated"]
    with pytest.raises(ResearchError, match="不存在的来源"):
        run(Engine(lambda: CONFIG, providers))


@pytest.mark.parametrize("quote", ["", "文档中不存在的证据"])
def test_fact_requires_exact_source_quote(quote):
    providers = SyntheticProviders()
    providers.output["graph"][0]["quote"] = quote
    with pytest.raises(ResearchError, match="原文引句"):
        run(Engine(lambda: CONFIG, providers))


def test_inference_cannot_attach_fabricated_source_quote():
    providers = SyntheticProviders()
    providers.output["graph"][1]["quote"] = "原文没有出现的推断证据"
    with pytest.raises(ResearchError, match="原文引句"):
        run(Engine(lambda: CONFIG, providers))


@pytest.mark.parametrize("quote", ["", "表格包含跨行合并单元格"])
def test_inference_allows_empty_or_exact_source_quote(quote):
    providers = SyntheticProviders()
    providers.output["graph"][1]["quote"] = quote
    result = run(Engine(lambda: CONFIG, providers))
    assert result["graph"][1]["quote"] == quote
    assert result["graph"][1]["verification_status"] == "pending_validation"


@pytest.mark.parametrize(
    "change",
    [
        {"sources": [{"id": "S1", "text": "fabricated"}]},
        {"measurement_status": "measured"},
        {"experiments": []},
        {"summary": None},
    ],
)
def test_model_cannot_supply_sources_scores_or_invalid_schema(change):
    providers = SyntheticProviders()
    providers.output.update(change)
    with pytest.raises(ResearchError):
        run(Engine(lambda: CONFIG, providers))


def test_missing_inputs_are_reported_as_assumptions():
    result = run(
        Engine(lambda: CONFIG, SyntheticProviders()),
        {**TASK, "parser_version": "", "expected_result": "", "constraints": ""},
    )
    assert len(result["assumptions"]) == 3
    assert all("未提供" in text for text in result["assumptions"])


def test_remote_authorization_and_empty_result_warning():
    providers = SyntheticProviders()
    result = run(
        Engine(lambda: CONFIG, providers),
        {**TASK, "library_ids": ["local-a", "zhipu:kb-a"]},
    )
    assert providers.calls[0][:2] == ("zhipu", ["kb-a"])
    assert any("没有返回片段" in item for item in result["warnings"])
    providers.calls.clear()
    with pytest.raises(PermissionError):
        run(
            Engine(lambda: CONFIG, providers),
            {**TASK, "library_ids": ["local-a", "zhipu:kb-b"]},
        )
    assert providers.calls == []


def test_public_call_receives_only_explicit_public_keywords():
    providers = SyntheticProviders()
    providers.warnings = ["Synthetic public fetch failure"]
    result = run(
        Engine(lambda: CONFIG, providers),
        {
            **TASK,
            "problem": "PRIVATE: 合并单元格",
            "allow_public": True,
            "public_query": "table extraction",
        },
    )
    assert providers.calls[0] == ("public", "table extraction")
    assert len(result["sources"]) == 1
    assert "Synthetic public fetch failure" in result["warnings"]


def test_revoke_after_model_response_prevents_report():
    providers = SyntheticProviders()

    def authorize():
        if providers.calls and providers.calls[-1][0] == "model":
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        run(Engine(lambda: CONFIG, providers), authorize=authorize)


def test_provider_failure_is_not_reported_as_successful_empty_retrieval():
    class Failing(SyntheticProviders):
        async def retrieve_zhipu(self, *args):
            raise ProviderError("Synthetic provider failure")

    providers = Failing()
    with pytest.raises(ProviderError):
        run(
            Engine(lambda: CONFIG, providers),
            {**TASK, "library_ids": ["local-a", "zhipu:kb-a"]},
        )
    assert providers.calls == []


def test_engine_rechecks_remote_scope_at_provider_boundary():
    providers = SyntheticProviders()
    providers.remote = [{**LOCAL, "origin": "zhipu", "library_id": "zhipu:kb-b"}]
    with pytest.raises(PermissionError):
        run(
            Engine(lambda: CONFIG, providers),
            {**TASK, "library_ids": ["local-a", "zhipu:kb-a"]},
        )
    assert [call[0] for call in providers.calls] == ["zhipu"]


def test_model_disabled_during_retrieval_is_not_called():
    config = copy.deepcopy(CONFIG)

    class DisableModel(SyntheticProviders):
        async def retrieve_zhipu(self, *args):
            config["model"] = {}
            return []

    providers = DisableModel()
    with pytest.raises(EngineNotConfiguredError):
        run(
            Engine(lambda: config, providers),
            {**TASK, "library_ids": ["local-a", "zhipu:kb-a"]},
        )
    assert providers.calls == []


def test_source_context_is_bounded_and_warned():
    sources, warnings = prepare_sources([{**LOCAL, "text": "x" * 10000}], "x")
    assert len(sources[0]["text"]) == 6000
    assert warnings


def test_prompt_treats_document_instructions_as_untrusted_data():
    providers = SyntheticProviders()
    run(Engine(lambda: CONFIG, providers))
    messages = providers.calls[-1][1]
    assert messages[0]["role"] == "system"
    assert "不可信数据" in messages[0]["content"]
    prompt_data = json.loads(messages[1]["content"])
    assert "api_key" not in prompt_data
    assert prompt_data["sources"][0]["text"] == LOCAL["text"]


def test_default_engine_provider_reads_explicit_network_config():
    config = {**CONFIG, "network": {"proxy_url": "http://proxy.example:8080"}}
    engine = Engine(lambda: config)
    assert (
        engine.providers._proxy_for_request("https://model.example/v1")
        == "http://proxy.example:8080"
    )
    config["network"]["proxy_url"] = ""
    assert engine.providers._proxy_for_request("https://model.example/v1") is None
