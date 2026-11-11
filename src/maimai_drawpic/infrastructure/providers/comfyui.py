from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote, urlencode, urlsplit
import aiohttp
import asyncio
import copy
import json
import secrets
import time
import uuid

from ...domain.errors import ProviderOutcomeUnknown, ProviderRequestError, ProviderResultError
from ..http import HttpProxySettings, read_response_text, sanitize_provider_text, sanitized_log_args
from ..media.collection import bounded_results
from ..media.downloads import download_image
from ..media.images import detect_mime_type
from ..storage.migration import resolve_workflow_path
from .requests import generation_submission, query_submitted_task, submitted_task


PromptMode = Literal["single_prompt", "positive_negative"]


class ComfyUIImage:
    """ComfyUI 本地服务图片生成接口封装。"""

    def __init__(
        self,
        *,
        base_url: str,
        plugin_dir: Path,
        data_dir: Path,
        logger: Optional[Any] = None,
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
        proxy_settings: Optional[HttpProxySettings] = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("ComfyUI 地址为空，请在 comfyui.base_url 中填写")
        if "://" not in normalized_base_url:
            normalized_base_url = f"http://{normalized_base_url}"
        parsed_url = urlsplit(normalized_base_url)
        if (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or
                parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment):
            raise ValueError("ComfyUI 地址必须是无账号、查询参数和片段的 HTTP(S) 基础地址")
        self.base_url = normalized_base_url
        self.plugin_dir = plugin_dir
        self.data_dir = data_dir
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
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        """使用配置的文生图工作流生成图片。"""

        del model, n
        workflow = await asyncio.to_thread(self._load_workflow, self.t2i_workflow_path, "文生图")
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

    async def edit_images(self, prompt: str, model: str, image_bytes_list: List[bytes], n: int = 1) -> List[bytes]:
        """使用配置的图生图工作流编辑图片。"""

        del model, n
        if not image_bytes_list:
            raise RuntimeError("没有可用于 ComfyUI 图生图的源图片")
        if len(image_bytes_list) > 1:
            raise ValueError("ComfyUI 当前图生图工作流只配置了一个源图节点，请仅提供一张图片")

        workflow = await asyncio.to_thread(self._load_workflow, self.i2i_workflow_path, "图生图")
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
        self._get_node_inputs(workflow, self.i2i_image_node_id, self.image_input_name, "图生图源图片")
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

    def _load_workflow(self, configured_path: str, task_name: str) -> Dict[str, Any]:
        """加载并验证 ComfyUI API 格式工作流。"""

        if not configured_path.strip():
            raise ValueError(f"ComfyUI {task_name}工作流路径为空，请在 comfyui 配置中填写")
        workflow_path = resolve_workflow_path(configured_path, self.plugin_dir, self.data_dir).resolve()
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
        for node_id, node in workflow.items():
            if not isinstance(node.get("class_type"), str) or not node["class_type"].strip() or not isinstance(node.get("inputs"), dict):
                raise ValueError(f"ComfyUI {task_name}工作流节点 {node_id} 缺少有效的 class_type 或 inputs，请使用 API 格式导出")

        self._log_info("已加载 ComfyUI %s工作流: path=%s node_count=%s", task_name, workflow_path, len(workflow))
        return copy.deepcopy(workflow)

    def _inject_prompt(
        self,
        *,
        workflow: Dict[str, Any],
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
            if positive_prompt_node_id.strip() == negative_prompt_node_id.strip():
                raise ValueError(f"ComfyUI {task_name}正向和反向提示词必须使用不同节点")
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

    def _inject_seed(self, workflow: Dict[str, Any], configured_node_id: str, task_name: str) -> None:
        """将固定或随机种子写入工作流的采样节点。"""

        node_id = self._validate_seed_target(workflow, configured_node_id, task_name)
        seed = self.seed if self.seed >= 0 else secrets.randbits(64)
        self._set_node_input(workflow, node_id, self.seed_input_name, seed, f"{task_name}随机种子")
        seed_mode = "固定" if self.seed >= 0 else "随机"
        self._log_info("ComfyUI %s种子已写入: mode=%s seed=%s node_id=%s", task_name, seed_mode, seed, node_id)

    def _validate_seed_target(self, workflow: Dict[str, Any], configured_node_id: str, task_name: str) -> str:
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
        workflow: Dict[str, Any],
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
        workflow: Dict[str, Any],
        node_id: str,
        input_name: str,
        field_name: str,
    ) -> Dict[str, Any]:
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
            raise ValueError(
                f"ComfyUI 工作流节点 {normalized_node_id} 不包含 {field_name}输入：{normalized_input_name}"
            )
        if isinstance(inputs[normalized_input_name], list):
            raise ValueError(f"ComfyUI 节点 {normalized_node_id} 的 {normalized_input_name} 是节点连线；请配置实际接收{field_name}值的节点，不能覆盖连线")
        return inputs

    @bounded_results
    async def _execute_workflow(self, workflow: Dict[str, Any], task_name: str) -> List[bytes]:
        """提交工作流、轮询执行结果并下载输出图片。"""

        client_id = str(uuid.uuid4())
        start_time = time.monotonic()
        prompt_id = await self._queue_prompt(workflow, client_id, task_name)
        async with submitted_task("ComfyUI", prompt_id):
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

    async def _queue_prompt(self, workflow: Dict[str, Any], client_id: str, task_name: str) -> str:
        """向 ComfyUI 队列提交 API 格式工作流。"""

        response = await self._post_json("/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = response.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            detail = self._error_details(response)
            self._log_error("ComfyUI %s提交未确认: response=%s", task_name, detail)
            raise ProviderOutcomeUnknown(f"ComfyUI {task_name}响应缺少 prompt_id，远端受理状态未确认，未重新提交：{detail}")
        if response.get("node_errors"):
            self._log_warning("ComfyUI %s部分输出未通过校验: prompt_id=%s detail=%s", task_name, prompt_id, self._error_details(response))
        self._log_info("ComfyUI %s工作流已提交: prompt_id=%s", task_name, prompt_id)
        return prompt_id

    async def _wait_for_history(self, prompt_id: str, start_time: float, task_name: str) -> Dict[str, Any]:
        """轮询指定任务历史，直到生成完成或超时。"""

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= self.request_timeout_seconds:
                raise TimeoutError(
                    f"ComfyUI {task_name}执行超时：prompt_id={prompt_id}，耗时已超过 {self.request_timeout_seconds} 秒"
                )
            history = await asyncio.wait_for(
                query_submitted_task(
                    lambda: self._get_json(f"/history/{quote(prompt_id, safe='')}"),
                    poll_interval=self.poll_interval_seconds,
                ),
                timeout=self.request_timeout_seconds - elapsed,
            )
            task_history = history.get(prompt_id)
            if isinstance(task_history, dict):
                status = task_history.get("status")
                if isinstance(status, dict) and status.get("status_str") == "error":
                    detail = self._execution_error(status)
                    self._log_error("ComfyUI %s执行失败: prompt_id=%s detail=%s", task_name, prompt_id, detail)
                    raise ProviderResultError(f"ComfyUI {task_name}执行失败：{detail}")
                if isinstance(status, dict) and status.get("completed") is False:
                    raise ProviderResultError(f"ComfyUI {task_name}未完成：prompt_id={prompt_id}，不会读取未完成输出")
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
    def _extract_image_descriptors(history: Dict[str, Any], prompt_id: str) -> List[Dict[str, str]]:
        """从 ComfyUI 历史输出中提取可下载图片描述。"""

        outputs = history.get("outputs")
        if not isinstance(outputs, dict):
            raise RuntimeError(f"ComfyUI 任务未返回 outputs：prompt_id={prompt_id}")

        output_image_descriptors: List[Dict[str, str]] = []
        other_image_descriptors: List[Dict[str, str]] = []
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
        mime_type = detect_mime_type(image_bytes)
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime_type)
        if extension is None:
            raise ValueError(f"ComfyUI 源图片格式不支持：{mime_type}")
        filename = f"maibot_{uuid.uuid4().hex}.{extension}"
        form.add_field("image", image_bytes, filename=filename, content_type=mime_type)
        form.add_field("type", "input")
        response = await self._post_form("/upload/image", form)
        uploaded_name = response.get("name")
        if not isinstance(uploaded_name, str) or not uploaded_name:
            raise RuntimeError(f"ComfyUI 上传图生图源图片失败：{sanitize_provider_text(response)}")
        if response.get("type") != "input":
            raise ProviderResultError("ComfyUI 上传响应的 type 不是 input，无法交给 LoadImage 节点")
        subfolder = response.get("subfolder")
        if isinstance(subfolder, str) and subfolder:
            uploaded_name = f"{subfolder.rstrip('/')}/{uploaded_name}"
        self._log_info("ComfyUI 图生图源图片上传成功: filename=%s size=%s", uploaded_name, len(image_bytes))
        return uploaded_name

    async def _download_image(self, descriptor: Dict[str, str]) -> bytes:
        """下载 ComfyUI 输出图片。"""

        url = f"{self.base_url}/view?{urlencode(descriptor)}"
        return await download_image(
            url,
            base_url=self.base_url,
            proxy_settings=self.proxy_settings,
            skip_ip_check=self.skip_image_url_ip_check,
            timeout_seconds=self.request_timeout_seconds,
        )

    @generation_submission
    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """向 ComfyUI 发送 JSON 请求。"""

        encoded = await asyncio.to_thread(lambda: json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return await self._request_json("POST", path, data=encoded, headers={"Content-Type": "application/json"})

    @generation_submission
    async def _post_form(self, path: str, form: aiohttp.FormData) -> Dict[str, Any]:
        """向 ComfyUI 发送 multipart 表单请求。"""

        return await self._request_json("POST", path, data=form)

    async def _get_json(self, path: str) -> Dict[str, Any]:
        """从 ComfyUI 获取 JSON 响应。"""

        return await self._request_json("GET", path)

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """执行 ComfyUI JSON HTTP 请求并记录精确错误。"""

        url = f"{self.base_url}{path}"
        started = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()) as session:
            async with session.request(
                method, url, **kwargs, allow_redirects=False, **self.proxy_settings.aiohttp_request_kwargs()
            ) as response:
                response_text = await read_response_text(response)
                try:
                    response_json = await asyncio.to_thread(json.loads, response_text)
                except json.JSONDecodeError as exc:
                    if response.status not in {200, 201}:
                        raise self._http_error(method, url, response.status, response_text) from None
                    raise ProviderOutcomeUnknown(
                        f"ComfyUI 接口返回非 JSON 数据 ({response.status})：{sanitize_provider_text(response_text)}"
                    ) from exc
                if response.status not in {200, 201}:
                    raise self._http_error(method, url, response.status, response_json)
                if not isinstance(response_json, dict):
                    raise ProviderOutcomeUnknown(f"ComfyUI 接口响应不是 JSON 对象：{sanitize_provider_text(response_json)}")
                self._log_debug("ComfyUI 接口响应: method=%s status=%s url=%s elapsed=%.2fs", method, response.status, url, time.monotonic() - started)
                return response_json

    def _http_error(self, method: str, url: str, status: int, data: Any) -> ProviderRequestError:
        detail = self._error_details(data)
        error = data.get("error") if isinstance(data, dict) else None
        code = sanitize_provider_text(error.get("type", "http_error"), max_chars=100) if isinstance(error, dict) else "http_error"
        failure = ProviderRequestError(status, code, f"ComfyUI 接口错误 HTTP {status}：{detail}")
        failure.retryable = failure.allow_fallback = False
        self._log_error("ComfyUI 接口请求失败: method=%s status=%s url=%s detail=%s", method, status, url, detail)
        return failure

    @staticmethod
    def _error_details(data: Any) -> str:
        """保留校验原因与节点位置，不输出完整工作流和节点输入。"""
        parts: List[str] = []
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                parts.append(str({key: error[key] for key in ("type", "message", "details") if key in error}))
            elif isinstance(error, str):
                parts.append(error)
            for key in ("message", "detail", "error_msg"):
                if isinstance(data.get(key), str):
                    parts.append(f"{key}={data[key]}")
            node_errors = data.get("node_errors")
            if isinstance(node_errors, dict):
                for node_id, info in list(node_errors.items())[:8]:
                    if not isinstance(info, dict):
                        continue
                    errors = info.get("errors", [])
                    if not isinstance(errors, list):
                        continue
                    for item in errors[:4]:
                        if isinstance(item, dict):
                            parts.append(f"node={node_id} class={info.get('class_type', '')} " + str({key: item[key] for key in ("type", "message", "details") if key in item}))
        unrecognized = {"response_keys": list(data)[:20]} if isinstance(data, dict) else data
        return sanitize_provider_text("；".join(parts) if parts else unrecognized, max_chars=1800)

    @staticmethod
    def _execution_error(status: Dict[str, Any]) -> str:
        messages = status.get("messages")
        details: List[str] = []
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, list) and len(message) == 2 and message[0] in {"execution_error", "execution_interrupted"} and isinstance(message[1], dict):
                    details.append(str({key: message[1][key] for key in ("node_id", "node_type", "exception_type", "exception_message") if key in message[1]}))
        return sanitize_provider_text("；".join(details) if details else {"status_str": status.get("status_str"), "completed": status.get("completed")}, max_chars=1800)

    def _log_debug(self, message: str, *args: Any) -> None:
        """轮询请求仅记录调试日志，避免刷屏。"""
        if self.logger is not None:
            self.logger.debug(message, *sanitized_log_args(args, ""))

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""
        if self.logger is not None:
            self.logger.info(message, *sanitized_log_args(args, ""))

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""
        if self.logger is not None:
            self.logger.warning(message, *sanitized_log_args(args, ""))

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""
        if self.logger is not None:
            self.logger.error(message, *sanitized_log_args(args, ""))
