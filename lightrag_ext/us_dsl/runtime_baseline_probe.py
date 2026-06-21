from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse

from .ingestion_baseline_types import RuntimeModelBaseline, StorageBaseline


DEFAULTS = {
    "WORKING_DIR": "./rag_storage",
    "INPUT_DIR": "./inputs",
    "WORKSPACE": "",
    "LLM_BINDING": "ollama",
    "LLM_BINDING_HOST": None,
    "LLM_MODEL": "mistral-nemo:latest",
    "LLM_TIMEOUT": 180,
    "MAX_ASYNC": 4,
    "SUMMARY_MAX_TOKENS": 1200,
    "ENABLE_LLM_CACHE": True,
    "ENABLE_LLM_CACHE_FOR_EXTRACT": True,
    "EMBEDDING_BINDING": "ollama",
    "EMBEDDING_BINDING_HOST": None,
    "EMBEDDING_MODEL": None,
    "EMBEDDING_DIM": None,
    "EMBEDDING_SEND_DIM": False,
    "EMBEDDING_TOKEN_LIMIT": None,
    "EMBEDDING_FUNC_MAX_ASYNC": 8,
    "EMBEDDING_BATCH_NUM": 10,
    "EMBEDDING_TIMEOUT": 30,
    "LIGHTRAG_KV_STORAGE": "JsonKVStorage",
    "LIGHTRAG_VECTOR_STORAGE": "NanoVectorDBStorage",
    "LIGHTRAG_GRAPH_STORAGE": "NetworkXStorage",
    "LIGHTRAG_DOC_STATUS_STORAGE": "JsonDocStatusStorage",
    "LIGHTRAG_DSL_INGEST_NAMESPACE": "dsl_test_knowledge_ingestion",
    "LIGHTRAG_DSL_INGEST_WORKING_DIR": None,
    "LIGHTRAG_DSL_INGEST_MODE": "readiness",
    "LIGHTRAG_ENABLE_DSL_AWARE_KNOWLEDGE_INGESTION": "0",
}

DEFAULT_HOSTS = {
    "ollama": "http://localhost:11434",
    "lollms": "http://localhost:9600",
    "azure_openai": "https://api.openai.com/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}

PROVIDER_DEFAULT_EMBEDDINGS = {
    "openai": {"model": "text-embedding-3-small", "dimension": 1536, "max_token_size": 8192},
    "azure_openai": {"model": "my-text-embedding-3-large-deployment", "dimension": 1536, "max_token_size": 8192},
    "jina": {"model": "jina-embeddings-v4", "dimension": 2048, "max_token_size": 8192},
    "gemini": {"model": "gemini-embedding-001", "dimension": 1536, "max_token_size": None},
    "voyageai": {"model": "voyage-3-lite", "dimension": 1024, "max_token_size": 32000},
}

def probe_runtime_baseline(repo_path: str | Path) -> dict:
    repo = Path(repo_path)
    env_file = repo / ".env"
    env_values = _read_env_file(env_file)
    resolver = EnvResolver(env_values)

    embedding = _embedding_baseline(resolver)
    llm = _llm_baseline(resolver)
    storage = _storage_baseline(repo, resolver)
    working_dirs = _working_dir_baseline(repo, resolver, storage)

    return {
        "embedding": embedding,
        "llm": llm,
        "storage": storage,
        "working_dirs": working_dirs,
        "env_file_present": env_file.exists(),
        "network_calls_executed": False,
        "storage_writes_executed": False,
    }


class EnvResolver:
    def __init__(self, env_file_values: dict[str, str]):
        self.env_file_values = env_file_values

    def value(self, key: str):
        if key in os.environ:
            return os.environ[key]
        if key in self.env_file_values:
            return self.env_file_values[key]
        default = DEFAULTS.get(key)
        if key in {"LLM_BINDING_HOST", "EMBEDDING_BINDING_HOST"} and default is None:
            binding_key = "LLM_BINDING" if key == "LLM_BINDING_HOST" else "EMBEDDING_BINDING"
            return DEFAULT_HOSTS.get(str(self.value(binding_key)), "http://localhost:11434")
        return default

    def source(self, key: str) -> str:
        if key in os.environ:
            return "environment"
        if key in self.env_file_values:
            return ".env"
        return "default"

    def int_value(self, key: str) -> int | None:
        value = self.value(key)
        if value in (None, "", "None", "none", "null"):
            return None
        return int(value)

    def bool_value(self, key: str) -> bool:
        value = self.value(key)
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "y"}


def _embedding_baseline(resolver: EnvResolver) -> RuntimeModelBaseline:
    binding = str(resolver.value("EMBEDDING_BINDING") or "")
    configured_model = resolver.value("EMBEDDING_MODEL")
    provider_defaults = PROVIDER_DEFAULT_EMBEDDINGS.get(binding, {})
    model = str(configured_model or provider_defaults.get("model") or "")
    host_value = str(resolver.value("EMBEDDING_BINDING_HOST") or "")
    configured_dim = resolver.int_value("EMBEDDING_DIM")
    provider_dim = provider_defaults.get("dimension")
    final_dim = configured_dim or provider_dim
    dimension_source = resolver.source("EMBEDDING_DIM") if configured_dim else "provider_default_or_unresolved"
    context_limit = resolver.int_value("EMBEDDING_TOKEN_LIMIT") or provider_defaults.get("max_token_size")
    sends_dimensions = _sends_embedding_dimension(binding, resolver.bool_value("EMBEDDING_SEND_DIM"))
    endpoint_host = _host_only(host_value)
    api_key = resolver.value("EMBEDDING_BINDING_API_KEY") or resolver.value("OPENAI_API_KEY")
    fake = _looks_fake(binding, model)
    risks = []
    if configured_model and not configured_dim:
        risks.append("Custom EMBEDDING_MODEL is configured without EMBEDDING_DIM.")
    if binding == "openai" and configured_dim and not sends_dimensions:
        risks.append(
            "EMBEDDING_DIM is used for local vector validation, but EMBEDDING_SEND_DIM=false means the OpenAI API dimensions parameter is not sent."
        )
    if fake:
        risks.append("Embedding model/binding name looks fake or test-scoped.")
    return RuntimeModelBaseline(
        binding=binding,
        model=model or None,
        endpoint_host=endpoint_host,
        config_sources={
            "EMBEDDING_BINDING": resolver.source("EMBEDDING_BINDING"),
            "EMBEDDING_MODEL": resolver.source("EMBEDDING_MODEL"),
            "EMBEDDING_BINDING_HOST": resolver.source("EMBEDDING_BINDING_HOST"),
            "EMBEDDING_DIM": resolver.source("EMBEDDING_DIM"),
            "EMBEDDING_SEND_DIM": resolver.source("EMBEDDING_SEND_DIM"),
            "embedding_context_limit": resolver.source("EMBEDDING_TOKEN_LIMIT"),
            "EMBEDDING_BATCH_NUM": resolver.source("EMBEDDING_BATCH_NUM"),
            "EMBEDDING_FUNC_MAX_ASYNC": resolver.source("EMBEDDING_FUNC_MAX_ASYNC"),
            "EMBEDDING_TIMEOUT": resolver.source("EMBEDDING_TIMEOUT"),
        },
        configured_dimension=final_dim,
        dimension_source=dimension_source,
        sends_dimensions_parameter=sends_dimensions,
        context_limit=context_limit,
        batch_size=resolver.int_value("EMBEDDING_BATCH_NUM"),
        concurrency=resolver.int_value("EMBEDDING_FUNC_MAX_ASYNC"),
        proxy_detected=_proxy_detected(),
        no_proxy_covers_endpoint=_no_proxy_covers(endpoint_host),
        fake_model_detected=fake,
        credential_configured=bool(api_key),
        credential_fingerprint=_credential_fingerprint(api_key),
        credential_source=_credential_source(
            resolver,
            (
                ("EMBEDDING_BINDING_API_KEY", "embedding_binding_credential"),
                ("OPENAI_API_KEY", "openai_credential"),
            ),
        ),
        cache_enabled=None,
        timeout=resolver.int_value("EMBEDDING_TIMEOUT"),
        summary_context_limit=context_limit,
        extract_model_same_as_query_model=None,
        risks=risks,
    )


def _llm_baseline(resolver: EnvResolver) -> RuntimeModelBaseline:
    binding = str(resolver.value("LLM_BINDING") or "")
    model = str(resolver.value("LLM_MODEL") or "")
    host_value = str(resolver.value("LLM_BINDING_HOST") or "")
    endpoint_host = _host_only(host_value)
    api_key = resolver.value("LLM_BINDING_API_KEY") or resolver.value("OPENAI_API_KEY")
    fake = _looks_fake(binding, model)
    risks = []
    if fake:
        risks.append("LLM model/binding name looks fake or test-scoped.")
    if binding == "openai" and model.startswith("gpt-5"):
        risks.append("Model access depends on the configured OpenAI account credential.")
    summary_context_limit = resolver.int_value("SUMMARY_MAX_TOKENS")
    return RuntimeModelBaseline(
        binding=binding,
        model=model or None,
        endpoint_host=endpoint_host,
        config_sources={
            "LLM_BINDING": resolver.source("LLM_BINDING"),
            "LLM_MODEL": resolver.source("LLM_MODEL"),
            "LLM_BINDING_HOST": resolver.source("LLM_BINDING_HOST"),
            "MAX_ASYNC": resolver.source("MAX_ASYNC"),
            "LLM_TIMEOUT": resolver.source("LLM_TIMEOUT"),
            "ENABLE_LLM_CACHE": resolver.source("ENABLE_LLM_CACHE"),
            "ENABLE_LLM_CACHE_FOR_EXTRACT": resolver.source(
                "ENABLE_LLM_CACHE_FOR_EXTRACT"
            ),
            "summary_context_limit": resolver.source("SUMMARY_MAX_TOKENS"),
        },
        configured_dimension=None,
        dimension_source=None,
        sends_dimensions_parameter=None,
        context_limit=None,
        batch_size=None,
        concurrency=resolver.int_value("MAX_ASYNC"),
        proxy_detected=_proxy_detected(),
        no_proxy_covers_endpoint=_no_proxy_covers(endpoint_host),
        fake_model_detected=fake,
        credential_configured=bool(api_key),
        credential_fingerprint=_credential_fingerprint(api_key),
        credential_source=_credential_source(
            resolver,
            (
                ("LLM_BINDING_API_KEY", "llm_binding_credential"),
                ("OPENAI_API_KEY", "openai_credential"),
            ),
        ),
        cache_enabled=resolver.bool_value("ENABLE_LLM_CACHE"),
        timeout=resolver.int_value("LLM_TIMEOUT"),
        summary_context_limit=summary_context_limit,
        extract_model_same_as_query_model=True,
        risks=risks,
    )


def _storage_baseline(repo: Path, resolver: EnvResolver) -> StorageBaseline:
    working_dir = _absolute_path(repo, str(resolver.value("WORKING_DIR") or DEFAULTS["WORKING_DIR"]))
    workspace = str(resolver.value("WORKSPACE") or "")
    kv_storage = str(resolver.value("LIGHTRAG_KV_STORAGE"))
    vector_storage = str(resolver.value("LIGHTRAG_VECTOR_STORAGE"))
    graph_storage = str(resolver.value("LIGHTRAG_GRAPH_STORAGE"))
    doc_status_storage = str(resolver.value("LIGHTRAG_DOC_STATUS_STORAGE"))
    storage_files = _storage_files(working_dir)
    risks = []
    embedding_metadata_found = _embedding_metadata_found(storage_files)
    if not Path(working_dir).exists():
        risks.append("Configured working_dir does not exist in this checkout.")
    if vector_storage == "NanoVectorDBStorage" and storage_files:
        risks.append("Local NanoVectorDB files exist; dimension compatibility must be confirmed before model changes.")
    return StorageBaseline(
        kv_storage=kv_storage,
        vector_storage=vector_storage,
        graph_storage=graph_storage,
        doc_status_storage=doc_status_storage,
        workspace=workspace,
        namespace="workspace-scoped LightRAG namespaces",
        working_dir=working_dir,
        config_sources={
            "WORKING_DIR": resolver.source("WORKING_DIR"),
            "WORKSPACE": resolver.source("WORKSPACE"),
            "LIGHTRAG_KV_STORAGE": resolver.source("LIGHTRAG_KV_STORAGE"),
            "LIGHTRAG_VECTOR_STORAGE": resolver.source("LIGHTRAG_VECTOR_STORAGE"),
            "LIGHTRAG_GRAPH_STORAGE": resolver.source("LIGHTRAG_GRAPH_STORAGE"),
            "LIGHTRAG_DOC_STATUS_STORAGE": resolver.source("LIGHTRAG_DOC_STATUS_STORAGE"),
        },
        is_networkx=graph_storage == "NetworkXStorage",
        is_neo4j=graph_storage == "Neo4JStorage",
        is_postgresql="PostgreSQL" in {kv_storage, vector_storage, graph_storage, doc_status_storage},
        is_nano_vectordb=vector_storage == "NanoVectorDBStorage",
        uses_redis="Redis" in {kv_storage, vector_storage, graph_storage, doc_status_storage},
        uses_mongo="Mongo" in {kv_storage, vector_storage, graph_storage, doc_status_storage},
        uses_opensearch="OpenSearch" in {kv_storage, vector_storage, graph_storage, doc_status_storage},
        storage_files_found=storage_files,
        embedding_metadata_found=embedding_metadata_found,
        risks=risks,
    )


def _working_dir_baseline(repo: Path, resolver: EnvResolver, storage: StorageBaseline) -> dict:
    raw_working_dir = storage.working_dir
    raw_workspace = storage.workspace
    dsl_namespace = str(resolver.value("LIGHTRAG_DSL_INGEST_NAMESPACE") or "")
    dsl_configured = resolver.value("LIGHTRAG_DSL_INGEST_WORKING_DIR")
    dsl_default = None
    if dsl_configured:
        dsl_default = _absolute_path(repo, str(dsl_configured))
    e2e_default = str((repo / "artifacts").resolve())
    share = bool(dsl_default and Path(dsl_default).resolve() == Path(raw_working_dir).resolve())
    share_graph_namespace = bool(raw_workspace and dsl_namespace and raw_workspace == dsl_namespace)
    return {
        "raw_upload_working_dir": raw_working_dir,
        "raw_workspace": raw_workspace,
        "dsl_readiness_working_dir": dsl_default,
        "dsl_canary_module_working_dir": dsl_default or "tempfile.mkdtemp(prefix='lightrag_dsl_ingestion_dsl_test_')",
        "dsl_namespace": dsl_namespace,
        "e2e_test_working_dir": e2e_default,
        "raw_and_dsl_share_working_dir": share,
        "raw_and_dsl_share_graph_namespace": share_graph_namespace,
        "runtime_confirmation_required": dsl_configured is None,
        "fake_and_real_embedding_mix_detected": False,
        "risk_notes": [
            "DSL canary/module creates temp working_dir when LIGHTRAG_DSL_INGEST_WORKING_DIR is unset.",
            "If both raw and DSL are deliberately pointed at the same safe test path, fake 8-dim and real embedding vectors can collide.",
        ],
    }


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _host_only(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"//{value}")
    return parsed.hostname or parsed.netloc or value


def _sends_embedding_dimension(binding: str, embedding_send_dim: bool) -> bool:
    if binding in {"jina", "gemini"}:
        return True
    return bool(embedding_send_dim)


def _proxy_detected() -> bool:
    return any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))


def _no_proxy_covers(endpoint_host: str | None) -> bool | None:
    if not endpoint_host:
        return None
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    if not no_proxy:
        return False
    endpoint = endpoint_host.lower()
    for part in no_proxy.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if item == "*" or endpoint == item or endpoint.endswith(item.lstrip(".")):
            return True
    return False


def _looks_fake(binding: str | None, model: str | None) -> bool:
    text = f"{binding or ''} {model or ''}".lower()
    return any(token in text for token in ("fake", "test", "mock", "stub"))


def _credential_fingerprint(value) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


def _credential_source(resolver: EnvResolver, keys: tuple[tuple[str, str], ...]) -> str | None:
    for key, safe_name in keys:
        if resolver.value(key):
            source = resolver.source(key)
            return safe_name if source == ".env" else f"{source}:{safe_name}"
    return None


def _absolute_path(repo: Path, value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo / path
    return str(path.resolve())


def _storage_files(working_dir: str) -> list[str]:
    root = Path(working_dir)
    if not root.exists():
        return []
    patterns = ("vdb_*.json", "kv_store_*.json", "graph_*.graphml")
    files: list[str] = []
    for pattern in patterns:
        files.extend(str(path) for path in root.rglob(pattern) if path.is_file())
    return sorted(files)


def _embedding_metadata_found(files: list[str]) -> bool | None:
    vdb_files = [Path(path) for path in files if Path(path).name.startswith("vdb_")]
    if not vdb_files:
        return None
    for path in vdb_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "embedding" in text.lower() or "dim" in text.lower():
            return True
    return False
