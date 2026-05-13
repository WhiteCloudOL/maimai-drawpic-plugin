from __future__ import annotations

import base64
import time
from typing import Any

import aiohttp


class ZhipuImage:
    """智谱图像生成接口封装。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用智谱文生图接口。"""

        if n != 1:
            raise RuntimeError("智谱图像生成接口当前仅按单张图片流程接入")

        response = await self._post_json(
            url=f"{self.base_url}/api/paas/v4/images/generations",
            payload={
                "model": model,
                "prompt": prompt,
                "size": "1280x1280",
            },
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """智谱当前未接入图生图编辑接口。"""

        del prompt, model, image_bytes, n
        raise RuntimeError("智谱图片模型当前仅支持文生图，不支持图生图编辑")

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._build_headers(), json=payload) as response:
                duration = time.time() - start_time
                if response.status != 200:
                    error_text = await response.text()
                    self._log_error(
                        "智谱图片生成接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise RuntimeError(
                        f"智谱图片生成接口错误 ({response.status}, 耗时: {duration:.2f}s): {error_text}"
                    )
                response_json = await response.json()
                data_count = len(response_json.get("data", [])) if isinstance(response_json.get("data"), list) else 0
                self._log_info("智谱接口成功: status=%s duration=%.2fs data_count=%s", response.status, duration, data_count)
                return response_json

    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从接口响应中提取图片。"""

        data = response.get("data")
        if not isinstance(data, list):
            response_preview = str(response)[:1200]
            self._log_error("智谱响应解析失败: 未找到 data 列表，response_preview=%s", response_preview)
            raise RuntimeError(f"智谱响应中未找到 data 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            image_base64 = item.get("b64_json")
            if isinstance(image_base64, str) and image_base64:
                image_bytes_list.append(base64.b64decode(image_base64))
                continue

            image_url = item.get("url")
            if isinstance(image_url, str) and image_url:
                image_bytes_list.append(await self._download_image(image_url))

        if not image_bytes_list:
            self._log_error("智谱响应解析失败: data 存在但没有可用图片数据")
            raise RuntimeError("智谱响应中没有可用图片数据")
        return image_bytes_list

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    self._log_error("下载智谱生成图片失败: status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载智谱生成图片失败: status={response.status}")
                image_bytes = await response.read()
                return image_bytes

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""

        if self.logger is not None:
            self.logger.info(message, *args)

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
