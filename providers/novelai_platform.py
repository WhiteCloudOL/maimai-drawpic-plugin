from __future__ import annotations

from io import BytesIO
from typing import Any

import aiohttp
import base64
import json
import random
import time
import zipfile

from ..core.image_utils import detect_image_dimensions


class NovelAIImage:
    """NovelAI 官方图片接口与兼容 NovelAPI 网关封装。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://image.novelai.net",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        width: int = 832,
        height: int = 1216,
        model_size_overrides: dict[str, str] | None = None,
        sampler: str = "k_euler_ancestral",
        steps: int = 28,
        scale: float = 5.0,
        seed: int = -1,
        negative_prompt: str = "",
        uc_preset: int = 0,
        quality_toggle: bool = True,
        sm: bool = False,
        sm_dyn: bool = False,
        noise_schedule: str = "native",
        img2img_strength: float = 0.6,
        img2img_noise: float = 0.1,
        max_images: int = 1,
        extra_parameters: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.width = int(width)
        self.height = int(height)
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.sampler = sampler.strip()
        self.steps = int(steps)
        self.scale = float(scale)
        self.seed = int(seed)
        self.negative_prompt = negative_prompt.strip()
        self.uc_preset = int(uc_preset)
        self.quality_toggle = quality_toggle
        self.sm = sm
        self.sm_dyn = sm_dyn
        self.noise_schedule = noise_schedule.strip()
        self.img2img_strength = float(img2img_strength)
        self.img2img_noise = float(img2img_noise)
        self.max_images = max(int(max_images), 1)
        self.extra_parameters = dict(extra_parameters or {})

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用 NovelAI / NovelAPI 文生图接口。"""

        content, content_type = await self._post_generation(
            url=f"{self.base_url}/ai/generate-image",
            payload=self._build_payload(prompt=prompt, model=model, action="generate", n=n),
        )
        return await self._extract_images(content, content_type)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """调用 NovelAI / NovelAPI 图生图接口。

        NovelAI img2img 接口仅接受单张源图片，传入多张时只使用第一张。
        """

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")
        if len(image_bytes_list) > 1:
            self._log_warning(
                "NovelAI 图生图仅支持单张源图片，已忽略多余的 %s 张", len(image_bytes_list) - 1
            )

        image_bytes = image_bytes_list[0]
        content, content_type = await self._post_img2img_with_source_size_fallback(
            prompt=prompt,
            model=model,
            image_bytes=image_bytes,
            n=n,
        )
        return await self._extract_images(content, content_type)

    def _build_payload(
        self,
        prompt: str,
        model: str,
        action: str,
        n: int,
        size_override: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """构建 NovelAI 图片请求体。"""

        width, height = size_override if size_override is not None else self._resolve_size(model)
        parameters: dict[str, Any] = {
            "width": width,
            "height": height,
            "scale": self.scale,
            "sampler": self.sampler,
            "steps": self.steps,
            "n_samples": min(max(int(n), 1), self.max_images),
            "seed": self._resolve_seed(),
            "ucPreset": self.uc_preset,
            "qualityToggle": self.quality_toggle,
            "sm": self.sm,
            "sm_dyn": self.sm_dyn,
        }
        if self.negative_prompt:
            parameters["uc"] = self.negative_prompt
        if self.noise_schedule:
            parameters["noise_schedule"] = self.noise_schedule
        parameters.update(self.extra_parameters)
        return {
            "input": prompt,
            "model": model,
            "action": action,
            "parameters": parameters,
        }

    def _resolve_size(self, model: str) -> tuple[int, int]:
        """按模型名解析图片尺寸。"""

        size = self.model_size_overrides.get(model.strip(), "")
        if not size:
            return max(self.width, 1), max(self.height, 1)

        normalized_size = size.replace("*", "x").lower()
        if "x" not in normalized_size:
            return max(self.width, 1), max(self.height, 1)
        width_text, height_text = normalized_size.split("x", maxsplit=1)
        try:
            return max(int(width_text.strip()), 1), max(int(height_text.strip()), 1)
        except ValueError:
            return max(self.width, 1), max(self.height, 1)

    @staticmethod
    def _detect_image_size(image_bytes: bytes) -> tuple[int, int] | None:
        """读取源图尺寸。"""

        return detect_image_dimensions(image_bytes)

    async def _post_img2img_with_source_size_fallback(
        self,
        *,
        prompt: str,
        model: str,
        image_bytes: bytes,
        n: int,
    ) -> tuple[bytes, str]:
        """图生图优先使用源图尺寸，接口不支持时回退默认尺寸。"""

        default_size = self._resolve_size(model)
        source_size = self._detect_image_size(image_bytes)
        size_candidates: list[tuple[int, int]] = []
        if source_size is not None and source_size != default_size:
            size_candidates.append(source_size)
        size_candidates.append(default_size)
        attempt_errors: list[str] = []

        for size_index, (width, height) in enumerate(size_candidates):
            if size_index == 0:
                self._log_info(
                    "NovelAI 图生图尺寸尝试: model=%s source_size=%s request_size=%sx%s default_size=%sx%s image_count=1",
                    model,
                    f"{source_size[0]}x{source_size[1]}" if source_size is not None else "",
                    width,
                    height,
                    default_size[0],
                    default_size[1],
                )
            if size_index > 0 and source_size is not None:
                self._log_warning(
                    "NovelAI 图生图源图尺寸不可用，回退默认尺寸: model=%s source_size=%sx%s fallback_size=%sx%s",
                    model,
                    source_size[0],
                    source_size[1],
                    width,
                    height,
                )
            payload = self._build_payload(
                prompt=prompt,
                model=model,
                action="img2img",
                n=n,
                size_override=(width, height),
            )
            payload["parameters"].update(
                {
                    "image": base64.b64encode(image_bytes).decode("utf-8"),
                    "strength": self.img2img_strength,
                    "noise": self.img2img_noise,
                }
            )
            try:
                return await self._post_generation(
                    url=f"{self.base_url}/ai/generate-image",
                    payload=payload,
                )
            except Exception as exc:
                attempt_errors.append(f"size={width}x{height}: {exc}")
        raise RuntimeError("NovelAI 图生图请求失败: " + " | ".join(attempt_errors))

    def _resolve_seed(self) -> int:
        """解析 NovelAI seed；负数表示每次随机。"""

        if self.seed >= 0:
            return self.seed
        return random.randint(0, 2**32 - 1)

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/zip",
        }

    async def _post_generation(self, url: str, payload: dict[str, Any]) -> tuple[bytes, str]:
        """发送 NovelAI 图片请求并保留二进制响应。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._build_headers(), json=payload) as response:
                duration = time.time() - start_time
                content = await response.read()
                content_type = response.headers.get("Content-Type", "")
                if response.status != 201:
                    error_preview = content[:1200].decode("utf-8", errors="replace")
                    self._log_error(
                        "NovelAI 图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_preview,
                    )
                    raise RuntimeError(
                        f"NovelAI 图片接口错误 ({response.status}, 耗时: {duration:.2f}s): {error_preview}"
                    )
                self._log_info("NovelAI 接口成功: status=%s duration=%.2fs", response.status, duration)
                return content, content_type

    async def _extract_images(self, content: bytes, content_type: str) -> list[bytes]:
        """从 NovelAI 官方 zip、兼容 JSON 或直接图片响应中提取图片。"""

        normalized_content_type = content_type.lower()
        if "application/json" in normalized_content_type:
            try:
                response = json.loads(content.decode("utf-8"))
            except Exception as exc:
                raise RuntimeError(f"NovelAI JSON 响应解析失败：{exc}") from exc
            return await self._extract_images_from_json(response)

        if zipfile.is_zipfile(BytesIO(content)):
            return self._extract_images_from_zip(content)

        if normalized_content_type.startswith("image/"):
            return [content]

        response_preview = content[:1200].decode("utf-8", errors="replace")
        raise RuntimeError(f"NovelAI 响应不是可解析的图片、zip 或 JSON，response_preview={response_preview}")

    def _extract_images_from_zip(self, content: bytes) -> list[bytes]:
        """从 NovelAI 官方 zip 响应中提取图片文件。"""

        image_bytes_list: list[bytes] = []
        with zipfile.ZipFile(BytesIO(content)) as image_zip:
            for file_info in image_zip.infolist():
                if file_info.is_dir():
                    continue
                filename = file_info.filename.lower()
                if not filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                image_bytes_list.append(image_zip.read(file_info))

        if not image_bytes_list:
            raise RuntimeError("NovelAI zip 响应中没有可用图片文件")
        return image_bytes_list

    async def _extract_images_from_json(self, response: dict[str, Any]) -> list[bytes]:
        """从 NovelAPI 兼容 JSON 响应中提取图片。"""

        image_bytes_list: list[bytes] = []
        for item in self._iter_json_image_items(response):
            if isinstance(item, str):
                extracted = await self._extract_image_from_string(item)
                if extracted is not None:
                    image_bytes_list.append(extracted)
            elif isinstance(item, dict):
                image_base64 = item.get("b64_json") or item.get("image_base64") or item.get("data")
                if isinstance(image_base64, str) and image_base64:
                    extracted = await self._extract_image_from_string(image_base64)
                    if extracted is not None:
                        image_bytes_list.append(extracted)
                        continue
                image_url = item.get("url") or item.get("image") or item.get("image_url")
                if isinstance(image_url, str) and image_url:
                    extracted = await self._extract_image_from_string(image_url)
                    if extracted is not None:
                        image_bytes_list.append(extracted)

        if not image_bytes_list:
            response_preview = str(response)[:1200]
            raise RuntimeError(f"NovelAPI JSON 响应中没有可用图片数据，response_preview={response_preview}")
        return image_bytes_list

    @staticmethod
    def _iter_json_image_items(response: dict[str, Any]) -> list[Any]:
        """兼容常见图片 JSON 响应字段。"""

        for key in ("data", "images", "output"):
            value = response.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested_items = NovelAIImage._iter_json_image_items(value)
                if nested_items:
                    return nested_items
        image = response.get("image") or response.get("url") or response.get("b64_json")
        if image:
            return [image]
        return []

    async def _extract_image_from_string(self, value: str) -> bytes | None:
        """从字符串中提取图片字节。"""

        if value.startswith("data:image/") and ";base64," in value:
            _prefix, image_base64 = value.split(";base64,", maxsplit=1)
            return base64.b64decode(image_base64)
        if value.startswith("http://") or value.startswith("https://"):
            return await self._download_image(value)
        try:
            return base64.b64decode(value)
        except Exception:
            return None

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    self._log_error("下载 NovelAI 生成图片失败: status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载 NovelAI 生成图片失败: status={response.status}")
                return await response.read()

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""

        if self.logger is not None:
            self.logger.info(message, *args)

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""

        if self.logger is not None:
            self.logger.warning(message, *args)

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
