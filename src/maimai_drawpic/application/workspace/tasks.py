"""网页及实例内插件联动的任务提交、源图和状态查询。"""

from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List
from uuid import uuid4
import asyncio
import base64
import json
import re

from ...infrastructure.media.images import validate_image_bytes
from ...interfaces.chat.message_images import decode_image_base64
from ...infrastructure.storage.results import ImageResultStore
from ...infrastructure.storage.atomic import write_json_atomically
from ...domain.styles import StylePromptResolver
from ...infrastructure.storage.tasks import DrawTaskStore
from ...domain.task_errors import TaskRequestError, task_error
from ..drawing.admission import update_task_owned
from ..access import access_restricted, require_chat_access, require_integration_api
from .preferences import validate_preferences


def validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{12}", task_id):
        raise ValueError("任务 ID 格式错误")


class WorkspaceTaskService:
    """仅使用当前实例的服务对象和授予目录，不接受任意文件路径。"""

    def __init__(
        self,
        *,
        ctx: Any,
        data_dir: Path,
        task_store: DrawTaskStore,
        results: ImageResultStore,
        get_config: Callable,
        get_service: Callable,
        submit_chat: Callable,
        active_services: Callable,
    ) -> None:
        self.ctx, self.data_dir = ctx, data_dir
        self.task_store, self.results = task_store, results
        self.get_config, self.get_service = get_config, get_service
        self.submit_chat, self.active_services = submit_chat, active_services
        self.lock = asyncio.Lock()
        self.metadata_path = data_dir / "workspace_tasks.json"
        self.metadata: Dict[str, Dict[str, Any]] = {}

    def initialize(self) -> None:
        if self.metadata_path.exists():
            self.metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if not isinstance(self.metadata, dict):
                raise ValueError("网页任务元数据格式错误")
        self.cleanup_storage()
        for record in self.task_store.snapshot():
            if record["submission"]:
                self.metadata[record["task_id"]] = record["submission"]
            if record["status"] in {"pending", "running"}:
                self.task_store.update_task(
                    record["task_id"],
                    status="failed",
                    message="插件已重启，旧任务结果待确认，请先核对提供商记录",
                    error=task_error("RESTART_UNCONFIRMED", "插件重启中断本地等待，未自动重新提交"),
                )

    def _save_metadata(self) -> None:
        retained = {item["task_id"] for item in self.task_store.snapshot()}
        self.metadata = {key: value for key, value in self.metadata.items() if key in retained}
        write_json_atomically(self.metadata_path, self.metadata)

    def _public_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """任务诊断可被其他插件读取，不能携带提示词、内部会话键或上游凭证。"""
        record.pop("session_key", None)
        record.pop("prompt", None)
        record.pop("submission", None)
        record["message"] = self.task_store.sanitize_message(record["message"])
        if record.get("persistence_pending"):
            record["message"] += "；终态尚未落盘，请恢复存储后查询以重试保存，不会重新生成或发送"
        return record

    async def claim_source(self, upload_id: str) -> Dict[str, Any]:
        claimed = await self.ctx.webui.claim_upload(upload_id)
        path = Path(claimed["path"])
        if not path.resolve().is_relative_to((self.data_dir / "uploads").resolve()) or path.is_symlink():
            raise ValueError("上传文件不属于当前插件")
        identifier, raw = await asyncio.to_thread(self.results.retention.claim_input, path, claimed["sha256"])
        preview = await asyncio.to_thread(ImageResultStore._preview, raw, 480, 40000)
        return {
            "source_id": identifier,
            "preview": "data:image/webp;base64," + base64.b64encode(preview).decode("ascii"),
        }

    async def _sources(self, source_ids: List[str], source_images: List[str]) -> List[bytes]:
        if not isinstance(source_ids, list) or not isinstance(source_images, list):
            raise ValueError("源图片参数必须为列表")
        if len(source_ids) + len(source_images) > 8:
            raise ValueError("最多提供 8 张源图")
        images = []
        for identifier in source_ids:
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
                raise ValueError("源图 ID 无效")
            path = self.data_dir / "inputs" / f"{identifier}.image"
            if path.is_symlink() or not path.resolve().is_relative_to((self.data_dir / "inputs").resolve()):
                raise ValueError("源图不属于当前插件")
            try:
                images.append(await asyncio.to_thread(path.read_bytes))
            except FileNotFoundError:
                raise ValueError("源图片已过期或被清理，请重新上传") from None
        for encoded in source_images:
            if not isinstance(encoded, str) or len(encoded) > 8 * 1024 * 1024:
                raise ValueError("接口源图必须是真实 Base64，单张编码最多 8 MiB")
            decoded = await asyncio.to_thread(decode_image_base64, encoded)
            if decoded is None:
                raise ValueError("无法解码源图片")
            images.append(decoded)
        for raw in images:
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError("单张源图片不能超过 20 MiB")
            await asyncio.to_thread(validate_image_bytes, raw)
        if sum(map(len, images)) > 40 * 1024 * 1024:
            raise ValueError("源图片总大小不能超过 40 MiB")
        return images

    async def submit(
        self,
        *,
        prompt: str,
        model: str = "",
        negative_prompt: str = "",
        style: str = "",
        task_type: str = "draw",
        stream_id: str = "",
        source_ids: List[str] | None = None,
        source_images: List[str] | None = None,
        request_id: str = "",
        origin: str = "webui",
        openai_compatibility_mode: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: str | None = None,
        require_existing_stream: bool = False,
    ) -> Dict[str, Any]:
        if origin == "plugin":
            require_integration_api(self.get_config().general, self.ctx.logger, "submit")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
            raise ValueError("提示词应为 1～16000 个字符")
        if not all(
            isinstance(value, str) for value in (model, negative_prompt, style, task_type, stream_id, request_id)
        ):
            raise ValueError("绘图文本参数必须为字符串")
        if task_type not in {"draw", "edit_image"}:
            raise ValueError("任务类型只能是 draw 或 edit_image")
        if len(negative_prompt) > 16000 or len(model) > 200 or len(style) > 80 or len(stream_id) > 200:
            raise ValueError("绘图参数超过长度限制")
        if request_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id 应为 8～80 位字母、数字、下划线或横线")
        if (
            source_ids is not None
            and not isinstance(source_ids, list)
            or source_images is not None
            and not isinstance(source_images, list)
        ):
            raise ValueError("源图片参数必须为列表")
        if len(source_ids or []) + len(source_images or []) > 8:
            raise ValueError("最多提供 8 张源图")
        context = {}
        if stream_id and access_restricted(self.get_config().general):
            context = await self.get_service().stream_service.existing_stream_context(stream_id)
            if not context:
                raise TaskRequestError("STREAM_UNAVAILABLE", "必须提供当前实例中已存在的真实聊天流 ID")
            require_chat_access(self.get_config().general, context, self.ctx.logger)
        options = {"openai_compatibility_mode": openai_compatibility_mode, "novelai_mode": novelai_mode}
        if novelai_artist_tags is not None:
            options["novelai_artist_tags"] = novelai_artist_tags
        options = validate_preferences(options)
        signature_values = [prompt, model, negative_prompt, style, task_type, stream_id, source_ids, source_images]
        # 保留旧请求的签名；只有显式覆盖新参数时才扩展签名，不能让升级破坏幂等恢复。
        if any(options.values()) or novelai_artist_tags is not None:
            signature_values.append(options)
        signature = await asyncio.to_thread(
            lambda: sha256(
                json.dumps(
                    signature_values,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        )
        async with self.lock:
            if origin == "plugin":
                require_integration_api(self.get_config().general, self.ctx.logger, "submit")
            if context:
                require_chat_access(self.get_config().general, context, self.ctx.logger)
            retained = await asyncio.to_thread(self.task_store.retained_task_ids)
            self.metadata = {key: value for key, value in self.metadata.items() if key in retained}
            if request_id:
                persisted = await asyncio.to_thread(self.task_store.find_request, request_id)
                previous = next(
                    ((key, value) for key, value in self.metadata.items() if value["request_id"] == request_id), None
                )
                if persisted is not None:
                    previous = (persisted["task_id"], persisted["submission"])
                if previous is not None:
                    if previous[1]["signature"] != signature:
                        raise TaskRequestError("REQUEST_ID_CONFLICT", "相同 request_id 不能用于不同绘图参数")
                    return {"task_id": previous[0], "reused": True}
            if not self.get_config().plugin.enabled:
                raise ValueError("绘图插件已停用，请先启用插件")
            if sum(len(service.background_tasks) for service in self.active_services()) >= 4:
                raise TaskRequestError(
                    "CONCURRENCY_LIMIT", "已有 4 个绘图任务正在执行，请等待完成后再提交", retry_submit=True
                )
            images = await self._sources(source_ids or [], source_images or [])
            if task_type == "draw" and images:
                raise ValueError("文生图不能附带源图，请选择图生图")
            if task_type == "edit_image" and not images:
                raise ValueError("图生图需要真实源图片")
            service = self.get_service()
            router = service.router
            resolved_model = router.resolve_model_name(model, allow_unknown_model=False)
            capability = router.evaluate_model_task_capability(resolved_model, task_type)
            if not capability.allowed:
                raise ValueError(capability.reason)
            router.validate_source_image_count(resolved_model, len(images))
            await asyncio.to_thread(router.validate_forced_command_task, resolved_model, task_type)
            if images:
                router.validate_local_source_images(resolved_model)
            resolved_style = StylePromptResolver(self.get_config().style).resolve(
                style_name=style, user_prompt=prompt, user_negative_prompt=negative_prompt
            )
            submission = {
                "origin": origin,
                "request_id": request_id or uuid4().hex,
                "signature": signature,
                "prompt": prompt,
                "style": style,
            }
            if origin == "plugin":
                require_integration_api(self.get_config().general, self.ctx.logger, "submit")
            if context:
                require_chat_access(self.get_config().general, context, self.ctx.logger)
            if stream_id:
                if require_existing_stream and not context:
                    context = await service.stream_service.existing_stream_context(stream_id)
                    if not context:
                        raise TaskRequestError("STREAM_UNAVAILABLE", "必须提供当前实例中已存在的真实聊天流 ID")
                    require_chat_access(self.get_config().general, context, self.ctx.logger)
                result = await self.submit_chat(
                    prompt=resolved_style.positive_prompt,
                    stream_id=stream_id,
                    requested_model=resolved_model,
                    request_negative_prompt=negative_prompt,
                    style_negative_prompt_template=resolved_style.negative_prompt_template,
                    requested_openai_compatibility_mode=options["openai_compatibility_mode"],
                    requested_novelai_mode=options["novelai_mode"],
                    requested_novelai_artist_tags=options.get("novelai_artist_tags"),
                    **({"user_id": context["user_id"], "group_id": context["group_id"],
                        "platform_name": context["platform"]} if context else {}),
                    source_image_bytes_list=images,
                    notify_start=False,
                    defer_prompt_review=True,
                    submission=submission,
                )
            else:
                result = await service.start_background_image_request(
                    prompt=resolved_style.positive_prompt,
                    stream_id="",
                    resolved_model=resolved_model,
                    resolved_openai_mode=options["openai_compatibility_mode"],
                    novelai_mode=options["novelai_mode"],
                    novelai_artist_tags=options.get("novelai_artist_tags", ""),
                    provider_name=router.get_model_provider(resolved_model),
                    request_negative_prompt=negative_prompt,
                    style_negative_prompt_template=resolved_style.negative_prompt_template,
                    source_image_bytes_list=images,
                    prompt_reviewed=False,
                    submission=submission,
                )
            task_id = result["task_id"]
            self.metadata[task_id] = submission
            return {"task_id": task_id, "reused": False}

    async def tasks(self, *, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 100:
            raise ValueError("分页参数无效")
        if status and status not in {"pending", "running", "completed", "failed", "rejected"}:
            raise ValueError("任务状态无效")
        if len(search) > 200:
            raise ValueError("搜索内容过长")
        await asyncio.to_thread(self.task_store.retry_pending_terminal)
        records = await asyncio.to_thread(self.task_store.snapshot)
        records.sort(key=lambda item: item["created_at"], reverse=True)
        counts = {
            name: sum(item["status"] == name for item in records)
            for name in ("pending", "running", "completed", "failed", "rejected")
        }
        filtered = [
            item
            for item in records
            if (not status or item["status"] == status)
            and (
                not search
                or search.casefold()
                in f"{item['task_id']} {item['model']} {item['provider']} {item['message']}".casefold()
            )
        ]
        items = filtered[(page - 1) * 12 : page * 12]
        for item in items:
            self._public_record(item)
            item["origin"] = self.metadata.get(item["task_id"], {}).get("origin", "chat")
            images = await asyncio.to_thread(self.results.images, item["task_id"])
            item["image_count"] = len(images)
            item["thumbnail"] = (
                (await asyncio.to_thread(self.results.preview, item["task_id"], 0, True))["data_url"]
                if images
                else None
            )
        return {"items": items, "total": len(filtered), "page": page, "page_size": 12, "counts": counts}

    async def detail(self, task_id: str, *, include_prompt: bool = False) -> Dict[str, Any]:
        validate_task_id(task_id)
        await asyncio.to_thread(self.task_store.retry_pending_terminal)
        record = next(
            (item for item in await asyncio.to_thread(self.task_store.snapshot) if item["task_id"] == task_id), None
        )
        if record is None:
            raise ValueError("当前实例不存在该任务")
        self._public_record(record)
        record["images"] = await asyncio.to_thread(self.results.images, task_id)
        if include_prompt:
            record["prompt"] = self.metadata.get(task_id, {}).get("prompt", "")
        return record

    async def cancel(self, task_id: str) -> Dict[str, Any]:
        validate_task_id(task_id)
        # 先从内存确认状态并发出取消信号；详情读取包含文件 IO，不能让其
        # 排在取消之前，否则进度写盘结束后仍可能启动一次新的生成请求。
        record = self.task_store.get_task(task_id)
        if record is None:
            raise ValueError("当前实例不存在该任务")
        if record.status not in {"pending", "running"}:
            raise ValueError("该任务已经结束")
        for service in self.active_services():
            task = next(
                (task for task in service.background_tasks if task.get_name() == f"maimai-drawpic:{task_id}"), None
            )
            if task is not None:
                if not task.cancel():
                    raise ValueError("该任务已经结束")
                _, pending = await asyncio.wait({task}, timeout=service.CANCEL_WAIT_SECONDS)
                if pending:
                    return {"task_id": task_id, "cancelled": False, "cancel_requested": True,
                            "message": "取消已请求，仍等待本地工作线程退出；不代表上游撤单或停止计费"}
                await service.wait_settlement()
                settled = await self.detail(task_id)
                if settled["status"] not in {"pending", "running"}:
                    if (settled.get("error") or {}).get("code") == "CANCELLED":
                        return {"task_id": task_id, "cancelled": True}
                    raise ValueError("该任务已经结束")
                # Cancellation may lose to a shielded completion/settlement. Never
                # overwrite the actual result just because cancel() was requested.
                if not task.cancelled():
                    raise ValueError("该任务已经结束")
                await update_task_owned(
                    self.task_store,
                    task_id,
                    status="failed",
                    message="任务已取消",
                    error=task_error("CANCELLED", "本地等待已取消，不代表上游撤单或停止计费"),
                )
                return {"task_id": task_id, "cancelled": True}
        raise ValueError("任务已不在当前执行队列中")

    def cleanup_storage(self, protected: set[str] | None = None) -> dict:
        self._save_metadata()
        inputs = self.results.retention.prune_inputs()
        results = self.results.cleanup(protected or set())
        return {"inputs": inputs["removed"], "results": results["removed"]}
