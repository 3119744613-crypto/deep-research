"""全部为合成 HTTP 响应；不发送真实密钥或调用线上模型。"""

import asyncio
import json

import httpx
import pytest

from document_research.contracts import ResearchError
from document_research.providers import (
    PUBLIC_DOCUMENTS,
    ZHIPU_RETRIEVE_URL,
    HttpProviders,
    ProviderConfigurationError,
    ProviderError,
    model_configured,
    public_excerpt,
    strict_json,
)


def run(value):
    return asyncio.run(value)


def hit(kb="kb-a", text="Synthetic table extraction evidence."):
    return {
        "text": text,
        "score": 0.9,
        "metadata": {
            "_id": "chunk-1",
            "knowledge_id": kb,
            "doc_id": "doc-1",
            "doc_name": "Synthetic fixture",
            "doc_url": "https://example.org/source",
        },
    }


def make_provider(response):
    return HttpProviders(
        httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    )


def test_zhipu_wire_contract_and_no_fabricated_page():
    requests, checks = [], []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 200, "data": [hit()]})

    provider = HttpProviders(httpx.MockTransport(handle))
    sources = run(
        provider.retrieve_zhipu(
            "synthetic-key", ["kb-a"], "complex tables", lambda: checks.append(1)
        )
    )
    assert str(requests[0].url) == ZHIPU_RETRIEVE_URL
    assert requests[0].headers["authorization"] == "Bearer synthetic-key"
    assert json.loads(requests[0].content) == {
        "query": "complex tables",
        "knowledge_ids": ["kb-a"],
        "top_k": 6,
    }
    assert len(checks) == 2
    assert sources[0]["page"] is None
    assert sources[0]["origin"] == "zhipu"
    assert sources[0]["library_id"] == "zhipu:kb-a"


@pytest.mark.parametrize(
    "response",
    [
        {"code": 500, "data": []},
        {"code": "200", "data": []},
        {"data": []},
        {"code": 200, "data": {"list": [hit()]}},
        {"code": 200, "data": [{"text": "x", "score": 0.9}]},
        {"code": 200, "data": [{**hit(), "score": True}]},
        {"code": 200, "data": [{**hit(), "text": ""}]},
    ],
)
def test_provider_errors_are_not_empty_results(response):
    with pytest.raises(ProviderError):
        run(
            make_provider(response).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", lambda: None
            )
        )


def test_successful_empty_retrieval_is_distinct_from_failure():
    assert (
        run(
            make_provider({"code": 200, "data": []}).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", lambda: None
            )
        )
        == []
    )


def test_cross_library_result_rejected():
    with pytest.raises(PermissionError):
        run(
            make_provider({"code": 200, "data": [hit("not-selected")]}).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", lambda: None
            )
        )


@pytest.mark.parametrize(
    "query,top_k", [("", 6), ("x" * 1001, 6), ("x", 0), ("x", 21), ("x", True)]
)
def test_retrieval_input_limits(query, top_k):
    provider = make_provider({"code": 200, "data": []})
    with pytest.raises(ResearchError):
        run(
            provider.retrieve_zhipu(
                "synthetic-key", ["kb-a"], query, lambda: None, top_k
            )
        )


def test_revocation_after_network_discards_response():
    checks = 0

    def authorize():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        run(
            make_provider({"code": 200, "data": [hit()]}).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", authorize
            )
        )


def test_public_fetch_uses_fixed_urls_and_lists_only_actual_sources():
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="# Synthetic official fixture\nTable parsing.")

    sources, warnings = run(
        HttpProviders(httpx.MockTransport(handle)).public_sources(
            "public table keywords", lambda: None
        )
    )
    assert [str(request.url) for request in requests] == [
        url for _, url in PUBLIC_DOCUMENTS
    ]
    assert all(
        not request.url.query
        and not request.content
        and "authorization" not in request.headers
        for request in requests
    )
    assert len(sources) == 2
    assert len(warnings) == 1 and "PaddleOCR" in warnings[0]
    assert all(
        source["fetched_at"] and source["text"].startswith("# Synthetic")
        for source in sources
    )


def test_public_keywords_choose_late_relevant_contiguous_excerpt():
    document = (
        "# Synthetic project\n\n"
        + ("General installation notes.\n\n" * 400)
        + "## Complex tables\n\nSupports table structure and merged cells.\n\n"
        + ("Other notes.\n\n" * 400)
    )
    excerpt, start, end = public_excerpt(document, "table structure merged cells")
    assert start > 6000
    assert "Supports table structure and merged cells." in excerpt
    assert excerpt == document[start:end]
    assert len(excerpt) <= 6000


def test_public_keywords_change_local_excerpt_without_changing_request():
    document = (
        "Installation procedure.\n\n"
        + ("Filler notes.\n\n" * 600)
        + "Complex table cell extraction."
    )
    installation, _, _ = public_excerpt(document, "installation")
    table, _, _ = public_excerpt(document, "table cell extraction")
    assert "Installation procedure." in installation
    assert "Complex table cell extraction." in table
    assert installation != table


def test_redirect_never_follows_or_leaks_authorization():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            302, headers={"location": "https://attacker.invalid/steal"}
        )

    with pytest.raises(ProviderError, match="302"):
        run(
            HttpProviders(httpx.MockTransport(handle)).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", lambda: None
            )
        )
    assert len(requests) == 1


def test_network_exception_does_not_expose_secret():
    def handle(request):
        raise httpx.ReadTimeout("synthetic-key and private document content")

    with pytest.raises(ProviderError) as error:
        run(
            HttpProviders(httpx.MockTransport(handle)).retrieve_zhipu(
                "synthetic-key", ["kb-a"], "table", lambda: None
            )
        )
    assert "synthetic-key" not in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', "```json {} ```"])
def test_ambiguous_or_invalid_json_rejected(raw):
    with pytest.raises(ProviderError):
        strict_json(raw)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://model.example/v1", True),
        ("http://127.0.0.1:8765/v1", True),
        ("http://remote.example/v1", False),
        ("https://user:pass@remote.example/v1", False),
        ("https://remote.example/v1?key=secret", False),
    ],
)
def test_model_address_boundary(url, expected):
    assert (
        model_configured(
            {"model": {"base_url": url, "api_key": "synthetic", "model": "test"}}
        )
        is expected
    )


def test_incomplete_model_output_is_error():
    provider = make_provider(
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
    )
    with pytest.raises(ProviderError):
        run(
            provider.model_report(
                {
                    "base_url": "https://model.example/v1",
                    "api_key": "synthetic",
                    "model": "test",
                },
                [],
                lambda: None,
            )
        )


@pytest.mark.parametrize("reasoning_effort", [None, "low", "high", "max"])
def test_model_request_is_explicit_json_and_has_no_tools(reasoning_effort):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"synthetic":true}'},
                    }
                ]
            },
        )

    config = {
        "base_url": "https://model.example/v1",
        "api_key": "synthetic",
        "model": "test",
    }
    if reasoning_effort is not None:
        config["reasoning_effort"] = reasoning_effort
    value = run(
        HttpProviders(httpx.MockTransport(handle)).model_report(
            config,
            [{"role": "user", "content": "synthetic document"}],
            lambda: None,
        )
    )
    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://model.example/v1/chat/completions"
    expected_payload = {
        "model": "test",
        "messages": [{"role": "user", "content": "synthetic document"}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 10000,
        "stream": False,
    }
    if reasoning_effort is not None:
        expected_payload["reasoning_effort"] = reasoning_effort
    assert payload == expected_payload
    assert value == {"synthetic": True}


@pytest.mark.parametrize(
    "reasoning_effort",
    [
        None,
        True,
        1,
        [],
        {},
        "",
        " low",
        "LOW",
        "medium",
        "minimal",
        "xhigh",
        "private-secret",
    ],
)
def test_invalid_model_reasoning_effort_is_safe_and_sends_no_request(reasoning_effort):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={})

    provider = HttpProviders(httpx.MockTransport(handle))
    with pytest.raises(ProviderConfigurationError) as error:
        run(
            provider.model_report(
                {
                    "base_url": "https://model.example/v1",
                    "api_key": "synthetic-secret",
                    "model": "test",
                    "reasoning_effort": reasoning_effort,
                },
                [{"role": "user", "content": "synthetic private document"}],
                lambda: None,
            )
        )
    assert str(error.value) == (
        "独立模型思考强度配置无效，reasoning_effort 仅支持 low、high 或 max。"
    )
    assert requests == []


def test_public_revocation_is_not_downgraded_to_warning():
    checks = 0

    def authorize():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise PermissionError("revoked")

    provider = HttpProviders(
        httpx.MockTransport(lambda request: httpx.Response(200, text="Synthetic docs"))
    )
    with pytest.raises(PermissionError):
        run(provider.public_sources("table", authorize))


def test_response_size_limit():
    provider = HttpProviders(
        httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        )
    )
    with pytest.raises(ProviderError, match="大小上限"):
        run(provider.retrieve_zhipu("synthetic", ["kb-a"], "table", lambda: None))


def test_cancellation_propagates():
    async def scenario():
        entered = asyncio.Event()

        async def handle(request):
            entered.set()
            await asyncio.Event().wait()

        provider = HttpProviders(httpx.MockTransport(handle))
        task = asyncio.create_task(
            provider.retrieve_zhipu("synthetic", ["kb-a"], "table", lambda: None)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())


@pytest.mark.parametrize(
    "proxy",
    ["http://proxy.example:8080", "https://user:synthetic-secret@proxy.example:8443"],
)
def test_explicit_proxy_configuration(proxy):
    provider = HttpProviders(config_loader=lambda: {"network": {"proxy_url": proxy}})
    assert provider._proxy_for_request(ZHIPU_RETRIEVE_URL) == proxy


@pytest.mark.parametrize(
    "proxy",
    [
        None,
        123,
        "socks5://proxy.example:1080",
        "http:///missing",
        "https://secret@proxy.example:bad",
        "https://proxy.example/private",
        "https://proxy.example?secret=value",
        "https://proxy.example#secret",
        "http://proxy.example:0",
        "http://proxy.example:99999",
    ],
)
def test_invalid_proxy_has_fixed_safe_error(proxy):
    provider = HttpProviders(config_loader=lambda: {"network": {"proxy_url": proxy}})
    with pytest.raises(ProviderError) as error:
        provider._proxy_for_request(ZHIPU_RETRIEVE_URL)
    assert str(error.value) == "独立网络代理配置无效，请检查 network.proxy_url。"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/v1/chat/completions",
        "http://localhost:8765/v1/chat/completions",
        "http://[::1]:8765/v1/chat/completions",
    ],
)
def test_loopback_models_explicitly_bypass_proxy(url):
    provider = HttpProviders(
        config_loader=lambda: {"network": {"proxy_url": "http://proxy.example:8080"}}
    )
    assert provider._proxy_for_request(url) is None


def test_proxy_config_is_reloaded_each_request():
    config = {"network": {"proxy_url": "http://proxy.example:8080"}}
    provider = HttpProviders(config_loader=lambda: config)
    assert (
        provider._proxy_for_request(ZHIPU_RETRIEVE_URL) == "http://proxy.example:8080"
    )
    config["network"]["proxy_url"] = ""
    assert provider._proxy_for_request(ZHIPU_RETRIEVE_URL) is None


def test_default_client_ignores_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://env-user:env-secret@proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://env-user:env-secret@proxy.invalid:8080")
    original_client = httpx.AsyncClient
    observed = []

    def capture_client(**kwargs):
        observed.append(kwargs)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", capture_client)
    provider = make_provider({"code": 200, "data": []})
    assert (
        run(provider.retrieve_zhipu("synthetic", ["kb-a"], "table", lambda: None)) == []
    )
    assert observed[0]["trust_env"] is False
    assert observed[0]["proxy"] is None


def test_explicit_proxy_is_passed_to_client_without_environment_fallback(monkeypatch):
    original_client = httpx.AsyncClient
    observed = []
    checks = []

    def capture_client(**kwargs):
        observed.append(
            {"proxy": kwargs.pop("proxy"), "trust_env": kwargs["trust_env"]}
        )
        # 合成 transport 接管请求；不会尝试连接这个示例代理。
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", capture_client)
    provider = HttpProviders(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 200, "data": []})
        ),
        config_loader=lambda: {"network": {"proxy_url": "http://proxy.example:8080"}},
    )
    run(
        provider.retrieve_zhipu(
            "synthetic", ["kb-a"], "table", lambda: checks.append(1)
        )
    )
    assert observed == [{"proxy": "http://proxy.example:8080", "trust_env": False}]
    assert checks == [1, 1]


def test_bad_proxy_configuration_not_disguised_as_empty_public_sources():
    provider = HttpProviders(
        config_loader=lambda: {"network": {"proxy_url": "invalid-private-secret"}}
    )
    with pytest.raises(ProviderError) as error:
        run(provider.public_sources("table", lambda: None))
    assert "invalid-private-secret" not in str(error.value)


def test_proxy_connect_failure_does_not_expose_proxy_credentials(monkeypatch):
    def fail_client(**kwargs):
        raise httpx.ProxyError("http://private-user:private-secret@proxy.example:8080")

    monkeypatch.setattr(httpx, "AsyncClient", fail_client)
    provider = HttpProviders(
        config_loader=lambda: {
            "network": {
                "proxy_url": "http://private-user:private-secret@proxy.example:8080"
            }
        }
    )
    with pytest.raises(ProviderError) as error:
        run(provider.retrieve_zhipu("synthetic", ["kb-a"], "table", lambda: None))
    assert "private" not in str(error.value)
    assert "proxy.example" not in str(error.value)
