"""只读获取平台模型目录，不生成图片，不返回鉴权信息。"""

from typing import Any, Dict, List
from urllib.parse import urlsplit
import aiohttp
import asyncio

from .openai import OpenaiImage
from ..http import HttpProxySettings, read_response_json, read_response_text, sanitize_provider_text
from ...domain.models.discovery import is_image_candidate, is_supported_aliyun_image


DISCOVERY_KINDS = frozenset({"openai", "agnes", "google", "aliyun", "siliconflow", "volcengine"})
DISCOVERY_HINTS = {
    "zhipu": "当前未接入智谱的官方模型发现接口，请手动添加模型。",
    "novelai": "NovelAI 未公开绘图模型目录接口，可从预设添加或直接输入模型 ID。",
    "comfyui": "ComfyUI 使用本地 API 工作流，不将 checkpoint 列表作为绘图模型导入。",
}
MAX_MODELS = 2000
MAX_PAGES = 20


def _endpoint(kind: str, values: Dict[str, Any]) -> str:
    base = values.get("base_url", "").strip().rstrip("/")
    if kind == "siliconflow":
        base = "https://api.siliconflow.cn/v1"
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("请填写有效的 HTTP(S) API 基础地址，不要包含账号密码、查询参数或片段")
    if kind in {"openai", "agnes"}:
        base = OpenaiImage._normalize_base_url(base)
    elif kind == "google" and not base.endswith(("/v1beta", "/v1")):
        base += "/v1beta"
    elif kind == "volcengine" and base.endswith("/images/generations"):
        base = base.removesuffix("/images/generations")
    # 其他平台沿用各自配置的 API 版本与工作空间，绝不替换成固定域名。
    return base + "/models"


def _models(kind: str, data: Any, api_key: str) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("模型接口响应格式无效：缺少模型列表")
    result = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("模型接口返回了无效的模型记录")
        identifier = item.get("name" if kind == "google" else "model" if kind == "aliyun" else "id")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 300:
            raise ValueError("模型接口返回了无效或过长的模型 ID")
        identifier = identifier.strip().removeprefix("models/") if kind == "google" else identifier.strip()
        if api_key in identifier or any(ord(char) < 32 for char in identifier):
            raise ValueError("模型接口返回了无效的模型 ID")
        if kind == "aliyun" and not is_supported_aliyun_image(identifier):
            continue
        label = item.get("displayName", identifier) if kind == "google" else identifier
        label = label if isinstance(label, str) else identifier
        result.append(
            {
                "id": identifier,
                "label": sanitize_provider_text(label, api_key, max_chars=300),
                "image_candidate": kind in {"aliyun", "siliconflow"} or is_image_candidate(identifier),
            }
        )
    return result


async def fetch_models(kind: str, values: Dict[str, Any], proxy: HttpProxySettings) -> Dict[str, Any]:
    """带响应大小、页数与总时限约束地读取模型；失败直接报告，不伪造默认目录。"""
    if kind not in DISCOVERY_KINDS:
        raise ValueError(DISCOVERY_HINTS.get(kind, "此平台尚未接入模型发现"))
    api_key = values["api_key"].strip()
    if not api_key or api_key.startswith("your-"):
        raise ValueError("请先填写 API 密钥，或使用此平台已保存的密钥")
    url = _endpoint(kind, values)
    headers = {"x-goog-api-key": api_key} if kind == "google" else {"Authorization": f"Bearer {api_key}"}
    params: Dict[str, Any] = {}
    if kind == "google":
        params["pageSize"] = 1000
    elif kind == "aliyun":
        params.update(page_no=1, page_size=100, capabilities="IG")
    elif kind == "siliconflow":
        params["type"] = "image"
    found: Dict[str, Dict[str, Any]] = {}
    seen_tokens = set()
    received = 0
    try:
        async with (
            asyncio.timeout(20),
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12), **proxy.aiohttp_session_kwargs()) as session,
        ):
            for page in range(1, MAX_PAGES + 1):
                async with session.get(
                    url, params=params, headers=headers, allow_redirects=False, **proxy.aiohttp_request_kwargs()
                ) as response:
                    if response.status != 200:
                        detail = sanitize_provider_text(
                            await read_response_text(response, max_bytes=32 * 1024), api_key
                        )
                        raise ValueError(
                            f"获取模型失败：HTTP {response.status}。请检查服务地址、密钥和模型列表接口权限。{detail}"
                        )
                    payload = await read_response_json(response, max_bytes=2 * 1024 * 1024)
                if not isinstance(payload, dict):
                    raise ValueError("模型接口返回了非对象 JSON")
                if kind == "google":
                    rows = payload.get("models")
                elif kind == "aliyun":
                    output = payload.get("output")
                    if not isinstance(output, dict):
                        raise ValueError("百炼模型接口响应缺少 output")
                    rows = output.get("models")
                else:
                    rows = payload.get("data")
                for model in _models(kind, rows, api_key):
                    found[model["id"]] = model
                received += len(rows)
                if len(found) > MAX_MODELS:
                    raise ValueError("模型目录超过 2000 项，请精简服务返回的目录后重试")
                if kind == "google":
                    token = payload.get("nextPageToken", "")
                    if not token:
                        break
                    if not isinstance(token, str) or len(token) > 4096 or token in seen_tokens:
                        raise ValueError("Google 模型接口返回了无效或重复的分页标记")
                    seen_tokens.add(token)
                    params["pageToken"] = token
                elif kind == "aliyun":
                    total = output.get("total")
                    if type(total) is not int or total < 0:
                        raise ValueError("百炼模型接口返回了无效的分页总数")
                    if received >= total:
                        break
                    if not rows:
                        raise ValueError("百炼模型接口分页结果不完整，请稍后重试")
                    params["page_no"] = page + 1
                else:
                    break
            else:
                raise ValueError("模型目录超过分页上限，未导入不完整结果")
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ValueError("获取模型失败：" + sanitize_provider_text(exc, api_key)) from None
    except RuntimeError as exc:
        raise ValueError("模型接口响应无效：" + sanitize_provider_text(exc, api_key)) from None
    return {"models": list(found.values())}
