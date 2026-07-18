from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import asyncio
import copy
import json
import secrets
import time
import uuid

import aiohttp

from ..core.http_proxy import HttpProxySettings


PromptMode = Literal["single_prompt", "positive_negative"]


class ComfyUIImage:
    """ComfyUI 本地服务图片生成接口封装。"""

    def __init__(
        self,
        *,
        base_url: str,
        plugin_dir: Path,
        logger: Any | None = None,
        request_timeout_seconds: int = 150,
        poll_interval_seconds: float = 1.0,
        t2i_workflow_path: str,
        i2i_workflow_path: str,
        t2i_prompt_mode: PromptMode,
        i2i_prompt_mode: PromptMode,
        t2i_prompt_node_id: str,
        i2i_prompt_node_id: str,
        t2i_positive_prompt_node_id: str,
        t2i_negative_prompt_node_id: str,
        i2i_positive_prompt_node_id: str,
        i2i_negative_prompt_node_id: str,
        t2i_negative_prompt: str,
        i2i_negative_prompt: str,
        i2i_image_node_id: str,
        prompt_input_name: str,
        image_input_name: str,
        seed: int,
        seed_input_name: str,
        t2i_seed_node_id: str,
        i2i_seed_node_id: str,
        proxy_settings: HttpProxySettings | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("ComfyUI 地址为空，请在 comfyui.base_url 中填写")
        if not normalized_base_url.startswith(("http://", "https://")):
            normalized_base_url = f"http://{normalized_base_url}"
        self.base_url = normalized_base_url
        self.plugin_dir = plugin_dir
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.poll_interval_seconds = max(float(poll_interval_seconds), 0.1)
        self.t2i_workflow_path = t2i_workflow_path
        self.i2i_workflow_path = i2i_workflow_path
        self.t2i_prompt_mode = t2i_prompt_mode
        self.i2i_prompt_mode = i2i_prompt_mode
        self.t2i_prompt_node_id = t2i_prompt_node_id
        self.i2i_prompt_node_id = i2i_prompt_node_id
        self.t2i_positive_prompt_node_id = t2i_positive_prompt_node_id
        self.t2i_negative_prompt_node_id = t2i_negative_prompt_node_id
        self.i2i_positive_prompt_node_id = i2i_positive_prompt_node_id
        self.i2i_negative_prompt_node_id = i2i_negative_prompt_node_id
        self.t2i_negative_prompt = t2i_negative_prompt
        self.i2i_negative_prompt = i2i_negative_prompt
        self.i2i_image_node_id = i2i_image_node_id
        self.prompt_input_name = prompt_input_name
        self.image_input_name = image_input_name
        self.seed = int(seed)
        self.seed_input_name = seed_input_name
        self.t2i_seed_node_id = t2i_seed_node_id
        self.i2i_seed_node_id = i2i_seed_node_id
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """使用配置的文生图工作流生成图片。"""

        del model, n
        workflow = self._load_workflow(self.t2i_workflow_path, "文生图")
        self._inject_prompt(
            workflow=workflow,
            prompt=prompt,
            mode=self.t2i_prompt_mode,
            prompt_node_id=self.t2i_prompt_node_id,
            positive_prompt_node_id=self.t2i_positive_prompt_node_id,
            negative_prompt_node_id=self.t2i_negative_prompt_node_id,
            negative_prompt=self.t2i_negative_prompt,
            task_name="文生图",
        )
        self._inject_seed(workflow, self.t2i_seed_node_id, "文生图")
        return await self._execute_workflow(workflow, "文生图")

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """使用配置的图生图工作流编辑图片。"""

        del model, n
        if not image_bytes_list:
            raise RuntimeError("没有可用于 ComfyUI 图生图的源图片")
        if len(image_bytes_list) > 1:
            self._log_warning("ComfyUI 图生图工作流当前仅注入第一张源图片，已忽略其余 %s 张", len(image_bytes_list) - 1)

        workflow = self._load_workflow(self.i2i_workflow_path, "图生图")
        self._inject_prompt(
            workflow=workflow,
            prompt=prompt,
            mode=self.i2i_prompt_mode,
            prompt_node_id=self.i2i_prompt_node_id,
            positive_prompt_node_id=self.i2i_positive_prompt_node_id,
            negative_prompt_node_id=self.i2i_negative_prompt_node_id,
            negative_prompt=self.i2i_negative_prompt,
            task_name="图生图",
        )
        self._inject_seed(workflow, self.i2i_seed_node_id, "图生图")
        uploaded_filename = await self._upload_image(image_bytes_list[0])
        self._set_node_input(
            workflow,
            self.i2i_image_node_id,
            self.image_input_name,
            uploaded_filename,
            "图生图源图片",
        )
        return await self._execute_workflow(workflow, "图生图")

    def validate_task_configuration(self, task_type: str) -> None:
        """验证强制绘图命令所需的 ComfyUI 工作流与节点配置。"""

        if task_type == "draw":
            workflow = self._load_workflow(self.t2i_workflow_path, "文生图")
            self._inject_prompt(
                workflow=workflow,
                prompt="",
                mode=self.t2i_prompt_mode,
                prompt_node_id=self.t2i_prompt_node_id,
                positive_prompt_node_id=self.t2i_positive_prompt_node_id,
                negative_prompt_node_id=self.t2i_negative_prompt_node_id,
                negative_prompt=self.t2i_negative_prompt,
                task_name="文生图",
            )
            self._validate_seed_target(workflow, self.t2i_seed_node_id, "文生图")
            return

        if task_type == "edit_image":
            workflow = self._load_workflow(self.i2i_workflow_path, "图生图")
            self._inject_prompt(
                workflow=workflow,
                prompt="",
                mode=self.i2i_prompt_mode,
                prompt_node_id=self.i2i_prompt_node_id,
                positive_prompt_node_id=self.i2i_positive_prompt_node_id,
                negative_prompt_node_id=self.i2i_negative_prompt_node_id,
                negative_prompt=self.i2i_negative_prompt,
                task_name="图生图",
            )
            self._validate_seed_target(workflow, self.i2i_seed_node_id, "图生图")
            self._get_node_inputs(workflow, self.i2i_image_node_id, self.image_input_name, "图生图源图片")
            return

        raise ValueError(f"不支持的 ComfyUI 任务类型：{task_type}")

    def _load_workflow(self, configured_path: str, task_name: str) -> dict[str, Any]:
        """加载并验证 ComfyUI API 格式工作流。"""

        if not configured_path.strip():
            raise ValueError(f"ComfyUI {task_name}工作流路径为空，请在 comfyui 配置中填写")
        workflow_path = Path(configured_path).expanduser()
        if not workflow_path.is_absolute():
            workflow_path = self.plugin_dir / workflow_path
        workflow_path = workflow_path.resolve()
        if not workflow_path.is_file():
            raise FileNotFoundError(f"ComfyUI {task_name}工作流不存在：{workflow_path}")

        try:
            with workflow_path.open("r", encoding="utf-8") as file:
                workflow = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ComfyUI {task_name}工作流 JSON 格式错误：{workflow_path} ({exc})") from exc

        if not isinstance(workflow, dict) or not workflow:
            raise ValueError(f"ComfyUI {task_name}工作流必须是非空 JSON 对象：{workflow_path}")
        if "nodes" in workflow or "links" in workflow:
            raise ValueError(
                f"ComfyUI {task_name}工作流不是 API 格式：{workflow_path}。"
                "请在 ComfyUI 菜单中选择“导出（API 格式）”后保存，不可使用普通保存的画布工作流。"
            )
        if not all(isinstance(node_id, str) and isinstance(node, dict) for node_id, node in workflow.items()):
            raise ValueError(f"ComfyUI {task_name}工作流节点必须使用字符串 ID 和对象定义：{workflow_path}")

        self._log_info("已加载 ComfyUI %s工作流: path=%s node_count=%s", task_name, workflow_path, len(workflow))
        return copy.deepcopy(workflow)

    def _inject_prompt(
        self,
        *,
        workflow: dict[str, Any],
        prompt: str,
        mode: PromptMode,
        prompt_node_id: str,
        positive_prompt_node_id: str,
        negative_prompt_node_id: str,
        negative_prompt: str,
        task_name: str,
    ) -> None:
        """将用户提示词写入单提示词或正反提示词工作流节点。"""

        if mode == "single_prompt":
            self._set_node_input(workflow, prompt_node_id, self.prompt_input_name, prompt, f"{task_name}提示词")
            return
        if mode == "positive_negative":
            self._set_node_input(
                workflow,
                positive_prompt_node_id,
                self.prompt_input_name,
                prompt,
                f"{task_name}正向提示词",
            )
            self._set_node_input(
                workflow,
                negative_prompt_node_id,
                self.prompt_input_name,
                negative_prompt,
                f"{task_name}反向提示词",
            )
            return
        raise ValueError(f"ComfyUI {task_name}提示词模式无效：{mode}")

    def _inject_seed(self, workflow: dict[str, Any], configured_node_id: str, task_name: str) -> None:
        """将固定或随机种子写入工作流的采样节点。"""

        node_id = self._validate_seed_target(workflow, configured_node_id, task_name)
        seed = self.seed if self.seed >= 0 else secrets.randbits(64)
        self._set_node_input(workflow, node_id, self.seed_input_name, seed, f"{task_name}随机种子")
        seed_mode = "固定" if self.seed >= 0 else "随机"
        self._log_info("ComfyUI %s种子已写入: mode=%s seed=%s node_id=%s", task_name, seed_mode, seed, node_id)

    def _validate_seed_target(self, workflow: dict[str, Any], configured_node_id: str, task_name: str) -> str:
        """解析并验证种子节点；未配置时自动识别唯一的 seed 输入节点。"""

        node_id = configured_node_id.strip()
        if not node_id:
            candidates = [
                candidate_id
                for candidate_id, node in workflow.items()
                if isinstance(node, dict)
                and isinstance(node.get("inputs"), dict)
                and self.seed_input_name.strip() in node["inputs"]
            ]
            if len(candidates) == 1:
                node_id = candidates[0]
            elif not candidates:
                raise ValueError(
                    f"ComfyUI {task_name}工作流未找到 {self.seed_input_name.strip() or 'seed'} 输入；"
                    "请填写种子输入字段名和种子节点 ID"
                )
            else:
                raise ValueError(
                    f"ComfyUI {task_name}工作流存在多个 {self.seed_input_name.strip() or 'seed'} 输入；"
                    "请填写对应的种子节点 ID"
                )
        self._get_node_inputs(workflow, node_id, self.seed_input_name, f"{task_name}随机种子")
        return node_id

    @classmethod
    def _set_node_input(
        cls,
        workflow: dict[str, Any],
        node_id: str,
        input_name: str,
        value: Any,
        field_name: str,
    ) -> None:
        """写入指定节点输入，并在配置错误时提供准确错误。"""

        inputs = cls._get_node_inputs(workflow, node_id, input_name, field_name)
        inputs[input_name.strip()] = value

    @staticmethod
    def _get_node_inputs(
        workflow: dict[str, Any],
        node_id: str,
        input_name: str,
        field_name: str,
    ) -> dict[str, Any]:
        """获取并校验指定节点输入。"""

        normalized_node_id = node_id.strip()
        normalized_input_name = input_name.strip()
        if not normalized_node_id:
            raise ValueError(f"ComfyUI {field_name}节点 ID 为空，请在 comfyui 配置中填写")
        if not normalized_input_name:
            raise ValueError(f"ComfyUI {field_name}输入字段为空，请在 comfyui 配置中填写")
        node = workflow.get(normalized_node_id)
        if not isinstance(node, dict):
            raise ValueError(f"ComfyUI 工作流中不存在 {field_name}节点：{normalized_node_id}")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(f"ComfyUI 工作流节点 {normalized_node_id} 缺少 inputs 对象，无法写入{field_name}")
        if normalized_input_name not in inputs:
            raise ValueError(f"ComfyUI 工作流节点 {normalized_node_id} 不包含 {field_name}输入：{normalized_input_name}")
        return inputs

    async def _execute_workflow(self, workflow: dict[str, Any], task_name: str) -> list[bytes]:
        """提交工作流、轮询执行结果并下载输出图片。"""

        client_id = str(uuid.uuid4())
        start_time = time.monotonic()
        prompt_id = await self._queue_prompt(workflow, client_id, task_name)
        history = await self._wait_for_history(prompt_id, start_time, task_name)
        image_descriptors = self._extract_image_descriptors(history, prompt_id)
        images = [await self._download_image(descriptor) for descriptor in image_descriptors]
        self._log_info(
            "ComfyUI %s完成: prompt_id=%s image_count=%s duration=%.2fs",
            task_name,
            prompt_id,
            len(images),
            time.monotonic() - start_time,
        )
        return images

    async def _queue_prompt(self, workflow: dict[str, Any], client_id: str, task_name: str) -> str:
        """向 ComfyUI 队列提交 API 格式工作流。"""

        response = await self._post_json("/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = response.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            error = response.get("error") or response.get("node_errors") or response
            self._log_error("ComfyUI %s提交失败: response=%s", task_name, str(error)[:2000])
            raise RuntimeError(f"ComfyUI {task_name}工作流提交失败：{error}")
        self._log_info("ComfyUI %s工作流已提交: prompt_id=%s", task_name, prompt_id)
        return prompt_id

    async def _wait_for_history(self, prompt_id: str, start_time: float, task_name: str) -> dict[str, Any]:
        """轮询指定任务历史，直到生成完成或超时。"""

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= self.request_timeout_seconds:
                raise TimeoutError(f"ComfyUI {task_name}执行超时：prompt_id={prompt_id}，耗时已超过 {self.request_timeout_seconds} 秒")
            history = await self._get_json(f"/history/{prompt_id}")
            task_history = history.get(prompt_id)
            if isinstance(task_history, dict):
                status = task_history.get("status")
                if isinstance(status, dict) and status.get("status_str") == "error":
                    messages = status.get("messages")
                    self._log_error("ComfyUI %s执行失败: prompt_id=%s messages=%s", task_name, prompt_id, messages)
                    raise RuntimeError(f"ComfyUI {task_name}执行失败：{messages}")
                outputs = task_history.get("outputs")
                if isinstance(outputs, dict):
                    return task_history
            await self._sleep_until_next_poll(start_time)

    async def _sleep_until_next_poll(self, start_time: float) -> None:
        """在不超过总超时的前提下等待下一次轮询。"""

        remaining = self.request_timeout_seconds - (time.monotonic() - start_time)
        if remaining > 0:
            await asyncio.sleep(min(self.poll_interval_seconds, remaining))

    @staticmethod
    def _extract_image_descriptors(history: dict[str, Any], prompt_id: str) -> list[dict[str, str]]:
        """从 ComfyUI 历史输出中提取可下载图片描述。"""

        outputs = history.get("outputs")
        if not isinstance(outputs, dict):
            raise RuntimeError(f"ComfyUI 任务未返回 outputs：prompt_id={prompt_id}")

        output_image_descriptors: list[dict[str, str]] = []
        other_image_descriptors: list[dict[str, str]] = []
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            images = output.get("images")
            if not isinstance(images, list):
                continue
            for image in images:
                if not isinstance(image, dict):
                    continue
                filename = image.get("filename")
                if not isinstance(filename, str) or not filename:
                    continue
                descriptor = {
                    "filename": filename,
                    "subfolder": str(image.get("subfolder") or ""),
                    "type": str(image.get("type") or "output"),
                }
                if descriptor["type"] == "output":
                    output_image_descriptors.append(descriptor)
                else:
                    other_image_descriptors.append(descriptor)
        image_descriptors = output_image_descriptors or other_image_descriptors
        if not image_descriptors:
            raise RuntimeError(f"ComfyUI 任务未返回可下载图片：prompt_id={prompt_id}")
        return image_descriptors

    async def _upload_image(self, image_bytes: bytes) -> str:
        """上传图生图源图片，并返回 ComfyUI 可被 LoadImage 节点读取的文件名。"""

        form = aiohttp.FormData()
        filename = f"maibot_{uuid.uuid4().hex}.png"
        form.add_field("image", image_bytes, filename=filename, content_type="image/png")
        response = await self._post_form("/upload/image", form)
        uploaded_name = response.get("name")
        if not isinstance(uploaded_name, str) or not uploaded_name:
            raise RuntimeError(f"ComfyUI 上传图生图源图片失败：{response}")
        subfolder = response.get("subfolder")
        if isinstance(subfolder, str) and subfolder:
            uploaded_name = f"{subfolder.rstrip('/')}/{uploaded_name}"
        self._log_info("ComfyUI 图生图源图片上传成功: filename=%s size=%s", uploaded_name, len(image_bytes))
        return uploaded_name

    async def _download_image(self, descriptor: dict[str, str]) -> bytes:
        """下载 ComfyUI 输出图片。"""

        query = urlencode(descriptor)
        url = f"{self.base_url}/view?{query}"
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()) as session:
            async with session.get(url, **self.proxy_settings.aiohttp_request_kwargs()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"下载 ComfyUI 图片失败 ({response.status})：{error_text[:1000]}")
                return await response.read()

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """向 ComfyUI 发送 JSON 请求。"""

        return await self._request_json("POST", path, json=payload)

    async def _post_form(self, path: str, form: aiohttp.FormData) -> dict[str, Any]:
        """向 ComfyUI 发送 multipart 表单请求。"""

        return await self._request_json("POST", path, data=form)

    async def _get_json(self, path: str) -> dict[str, Any]:
        """从 ComfyUI 获取 JSON 响应。"""

        return await self._request_json("GET", path)

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """执行 ComfyUI JSON HTTP 请求并记录精确错误。"""

        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()) as session:
            async with session.request(method, url, **kwargs, **self.proxy_settings.aiohttp_request_kwargs()) as response:
                response_text = await response.text()
                try:
                    response_json = json.loads(response_text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"ComfyUI 接口返回非 JSON 数据 ({response.status})：{response_text[:1000]}"
                    ) from exc
                if response.status not in {200, 201}:
                    self._log_error(
                        "ComfyUI 接口请求失败: method=%s status=%s url=%s response=%s",
                        method,
                        response.status,
                        url,
                        response_text[:2000],
                    )
                    raise RuntimeError(f"ComfyUI 接口错误 ({response.status})：{response_json}")
                if not isinstance(response_json, dict):
                    raise RuntimeError(f"ComfyUI 接口响应格式错误：{response_json}")
                return response_json

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
