"""检索预览、问答、公开查询隔离和实时撤权的合成验收。"""

import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from document_research.config import init_config, load_config
from document_research.contracts import ResearchError
from document_research.engine import Engine
from document_research.providers import ProviderError
from document_research.service import PREFIX, create_app

TOKEN = "synthetic-retrieval-test-token-20261011"
CONFIG = {
    "model": {
        "base_url": "https://model.example/v1",
        "model": "fake",
        "api_key": "fake",
    },
    "zhipu": {"api_key": "fake", "libraries": {"local": [{"id": "fixture"}]}},
}
SOURCE = {
    "id": "part1",
    "origin": "local",
    "library_id": "local:test",
    "document_id": "test",
    "title": "合成需求",
    "text": "复杂表格包含合并单元格。",
    "page": 1,
    "source_url": None,
}
TASK = {
    "owner": "local",
    "library_ids": ["local:test"],
    "problem": "复杂表格有什么问题？",
}


class Providers:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.failure = None

    async def search_public(self, key, query, authorize):
        authorize()
        self.calls.append(("public_search", query))
        return [{**SOURCE, "origin": "public", "library_id": "public:web_search"}], []

    async def retrieve_zhipu(self, key, ids, query, authorize):
        self.calls.append(("zhipu", query))
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        authorize()
        if self.failure:
            raise self.failure
        return [{**SOURCE, "origin": "zhipu", "library_id": "zhipu:fixture"}]

    async def model_report(self, config, messages, authorize):
        authorize()
        self.calls.append(("model", messages))
        source = json.loads(messages[-1]["content"])["sources"][0]
        return {
            "answer": [
                {
                    "text": "资料提到合并单元格。",
                    "source_id": source["id"],
                    "quote": "复杂表格包含合并单元格。",
                }
            ],
            "gaps": ["未提供实际表格样本"],
            "graph": [],
        }


def retrieve(engine, task=TASK, sources=None):
    return asyncio.run(
        engine.retrieve(
            copy.deepcopy(task), [SOURCE] if sources is None else sources, lambda: None
        )
    )


def test_preview_needs_no_model_and_only_returns_matching_local_evidence():
    providers = Providers()
    result = retrieve(
        Engine(dict, providers),
        sources=[SOURCE, {**SOURCE, "id": "other", "text": "unrelated banana"}],
    )
    assert [item["original_id"] for item in result["sources"]] == ["part1"]
    assert result["retrieval_status"] == [
        {"provider": "local", "status": "ok", "count": 1}
    ]
    assert providers.calls == []
    empty = retrieve(Engine(dict, providers), {**TASK, "problem": "astronomy planets"})
    assert empty["sources"] == []
    assert empty["retrieval_status"][0]["status"] == "empty"


def test_public_search_is_opt_in_and_receives_only_explicit_public_query():
    providers = Providers()
    engine = Engine(lambda: CONFIG, providers)
    retrieve(engine, {**TASK, "public_query": "Docling tables"})
    assert providers.calls == []
    retrieve(
        engine,
        {
            **TASK,
            "problem": "PRIVATE complex tables",
            "allow_web_search": True,
            "public_query": "Docling tables",
        },
    )
    assert providers.calls == [("public_search", "Docling tables")]
    with pytest.raises(ResearchError, match="单独填写"):
        retrieve(engine, {**TASK, "allow_web_search": True})
    assert len(providers.calls) == 1


def test_answer_uses_fresh_sources_and_preserves_exact_quotes():
    providers = Providers()
    task = {**TASK, "mode": "answer", "allow_external_model": True}
    result = asyncio.run(
        Engine(lambda: CONFIG, providers).run(task, [SOURCE], lambda: None)
    )
    assert result["mode"] == "answer"
    assert result["answer"][0]["quote"] in result["sources"][0]["text"]
    assert result["assumptions"] == []
    assert [call[0] for call in providers.calls] == ["model"]
    assert "不可信数据" in providers.calls[0][1][0]["content"]


def test_answer_without_hits_does_not_invent_a_model_answer():
    providers = Providers()
    task = {
        **TASK,
        "mode": "answer",
        "allow_external_model": True,
        "problem": "astronomy",
    }
    result = asyncio.run(
        Engine(lambda: CONFIG, providers).run(task, [SOURCE], lambda: None)
    )
    assert result["answer"] == [] and result["gaps"]
    assert result["sources"] == [] and providers.calls == []


@pytest.fixture
def live_service(tmp_path):
    init_config(tmp_path)
    config = load_config(tmp_path)
    config.update(copy.deepcopy(CONFIG), tokens={"local": TOKEN})
    (tmp_path / "config.json").write_text(json.dumps(config))
    providers = Providers()
    engine = Engine(lambda: load_config(tmp_path), providers)
    with TestClient(
        create_app(tmp_path, engine), headers={"Authorization": "Bearer " + TOKEN}
    ) as client:
        yield client, providers, tmp_path


def test_preview_http_has_same_scope_and_no_model_requirement(live_service):
    client, providers, path = live_service
    config = load_config(path)
    config["model"] = {}
    (path / "config.json").write_text(json.dumps(config))
    library = client.post(PREFIX + "/libraries", json={"name": "测试"}).json()
    client.post(
        PREFIX + "/libraries/" + library["id"] + "/documents",
        files={"file": ("sample.txt", SOURCE["text"].encode())},
    )
    body = {"problem": "复杂表格", "library_ids": [library["id"]]}
    response = client.post(PREFIX + "/retrieve", json=body)
    assert response.status_code == 200, response.text
    assert len(response.json()["sources"]) == 1 and providers.calls == []
    assert (
        client.post(
            PREFIX + "/retrieve", json=body, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        client.post(
            PREFIX + "/retrieve", json={**body, "library_ids": ["zhipu:other"]}
        ).status_code
        == 403
    )
    assert (
        client.post(
            PREFIX + "/retrieve", json={**body, "allow_web_search": True}
        ).status_code
        == 422
    )


def test_preview_remote_failure_is_not_an_empty_success(live_service):
    client, providers, _ = live_service
    providers.failure = ProviderError("合成检索故障")
    response = client.post(
        PREFIX + "/retrieve",
        json={"problem": "复杂表格", "library_ids": ["zhipu:fixture"]},
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "合成检索故障"}


def test_preview_discards_result_after_token_revocation(live_service):
    client, providers, path = live_service
    providers.release.clear()
    with ThreadPoolExecutor() as executor:
        response = executor.submit(
            client.post,
            PREFIX + "/retrieve",
            json={"problem": "复杂表格", "library_ids": ["zhipu:fixture"]},
        )
        assert providers.started.wait(2)
        config = load_config(path)
        config["tokens"] = {"local": TOKEN + "changed"}
        (path / "config.json").write_text(json.dumps(config))
        providers.release.set()
        assert response.result(timeout=5).status_code == 403


def test_answer_task_is_ready_without_research_clarifications(live_service):
    client, _, _ = live_service
    response = client.post(
        PREFIX + "/tasks",
        json={
            "mode": "answer",
            "problem": "复杂表格",
            "library_ids": ["zhipu:fixture"],
            "allow_external_model": True,
        },
    )
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "ready" and task["questions"] == []
    assert task["assumptions"] == []
    assert (
        client.post(
            PREFIX + "/tasks", json={"mode": "unknown", "problem": "复杂表格"}
        ).status_code
        == 422
    )
