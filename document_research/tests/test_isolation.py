"""验证专用文档研发服务没有接入平台领域工具与数据平面。"""

import ast
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parent
FORBIDDEN_MODULES = {
    "backend",
    "platform_core",
    "equipment_deep_research",
    "knowledgegraph",
    "server",
}


def test_service_has_no_platform_imports():
    """独立服务不得导入现有平台工具、知识库或领域运行时。"""
    violations = []
    for path in SERVICE_ROOT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            violations.extend(
                f"{path.name}:{node.lineno}:{name}"
                for name in names
                if name.split(".")[0] in FORBIDDEN_MODULES
            )
    assert not violations, violations


def test_platform_does_not_register_document_research_as_a_tool():
    """新增能力不能通过原平台自动发现、注册或知识桥接获得调用入口。"""
    roots = [
        REPO_ROOT / "backend/package/platform_core/agents",
        REPO_ROOT / "backend/package/platform_core/knowledge",
        REPO_ROOT / "backend/package/platform_core/services",
        REPO_ROOT / "backend/package/equipment_deep_research",
        REPO_ROOT / "backend/package/knowledgegraph",
    ]
    violations = []
    for root in roots:
        assert root.exists(), f"缺少源码，无法审查：{root}"
        for path in root.rglob("*.py"):
            content = path.read_text()
            if "document-research-api" in content or "document_research" in content:
                violations.append(str(path.relative_to(REPO_ROOT)))
    assert not violations, violations


def test_default_deployment_does_not_share_new_service_secrets_or_volumes():
    """默认平台部署未自动挂载专用服务或注入访问凭据。"""
    for path in REPO_ROOT.glob("*compose*.y*ml"):
        content = path.read_text()
        assert "document-research-api" not in content, path.name
        assert "DOCUMENT_RESEARCH" not in content, path.name
        assert "DOC_RESEARCH" not in content, path.name
