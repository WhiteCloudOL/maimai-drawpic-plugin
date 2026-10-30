"""绘图工作台的配置、模型、会话和预设业务边界。"""

from typing import Any, Awaitable, Callable, Dict
import asyncio

from ...domain.configuration.models import DrawpicConfig, StylePresetConfig
from ...domain.models.novelai_catalog import NOVELAI_PRESET_HINT, NOVELAI_PRESET_MODELS
from ...infrastructure.storage.platforms import (
    PLATFORM_DEFAULT_NAMES,
    PLATFORM_NAMES,
    WorkspaceConfigStore,
    _mask_secrets,
    _validate_fields,
    parse_json_object,
)
from .tasks import WorkspaceTaskService
from ...infrastructure.storage.settings import workspace_config
from ...infrastructure.providers.model_discovery import DISCOVERY_HINTS, DISCOVERY_KINDS, fetch_models


class WorkspaceService:
    def __init__(
        self,
        *,
        ctx: Any,
        store: WorkspaceConfigStore,
        tasks: WorkspaceTaskService,
        logs: Any,
        get_config: Callable,
        apply_settings: Callable,
        refresh: Callable,
    ) -> None:
        self.ctx, self.store, self.tasks, self.logs = ctx, store, tasks, logs
        self.get_config, self.apply_settings, self.refresh = get_config, apply_settings, refresh
        self.lock = asyncio.Lock()
        self._transaction: asyncio.Task | None = None
        self._closing = False
        self.runtime_refresh_pending = False

    async def _run_transaction(self, operation: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
        # Acquire before spawning: cancelled waiters never become detached writes,
        # and at most one transaction owns the lock and worker lifecycle.
        await self.lock.acquire()
        if self._closing:
            self.lock.release()
            raise RuntimeError("工作台正在关闭，不能保存配置")

        async def complete():
            try:
                return await operation()
            finally:
                self.lock.release()

        task = asyncio.create_task(complete(), name="drawpic-config-commit")
        self._transaction = task

        def settled(done):
            if self._transaction is done:
                self._transaction = None
            # A caller may have left. Always retrieve and report failures without
            # leaking exception contents or claiming an uncommitted write saved.
            if not done.cancelled() and done.exception() is not None:
                self.ctx.logger.warning("配置事务失败: error_type=%s", type(done.exception()).__name__)

        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def close(self) -> None:
        """Stop admissions and finish the single owned transaction before teardown."""
        self._closing = True
        task = self._transaction
        if task is not None:
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))

    def models(self) -> Dict[str, Any]:
        router = self.tasks.get_service().router
        default_model, default_model_error = "", ""
        if router.get_all_models():
            try:
                default_model = router.resolve_default_model()
            except ValueError as exc:
                default_model_error = str(exc)
        models = []
        for model in router.get_all_models():
            draw = router.evaluate_model_task_capability(model, "draw")
            edit = router.evaluate_model_task_capability(model, "edit_image")
            api_edit_reason = edit.reason
            if edit.allowed:
                try:
                    router.validate_local_source_images(model)
                except ValueError as exc:
                    api_edit_reason = str(exc)
            maximum = router.get_max_source_images(model)
            models.append({
                **router.describe_model(model),
                "draw": draw.allowed,
                "draw_reason": draw.reason,
                "edit_image": edit.allowed,
                "edit_reason": edit.reason,
                "api_edit_image": edit.allowed and not api_edit_reason,
                "api_edit_reason": api_edit_reason,
                "max_source_images": min(8, maximum) if maximum is not None else 8,
            })
        return {
            "models": models,
            "default_model": default_model,
            "default_model_error": default_model_error,
        }

    async def bootstrap(self) -> Dict[str, Any]:
        snapshot = await asyncio.to_thread(self.store.public_snapshot)
        config = snapshot["settings"]
        config.pop("plugin", None)
        defaults = workspace_config(DrawpicConfig().model_dump(mode="json"))
        defaults.pop("plugin", None)
        schema = self.store.schema()
        schema["sections"].pop("plugin", None)
        schema["sections"].pop("proxy", None)
        return {
            **snapshot,
            "config_update_pending": self._transaction is not None,
            "runtime_refresh_pending": self.runtime_refresh_pending or self._transaction is not None,
            "settings": _mask_secrets(config),
            "defaults": _mask_secrets(defaults),
            "schema": schema,
            "catalog": [
                {
                    "kind": key,
                    "name": name,
                    "default_name": PLATFORM_DEFAULT_NAMES[key],
                    "model_discovery": key in DISCOVERY_KINDS,
                    "model_discovery_hint": DISCOVERY_HINTS.get(key, ""),
                    "model_presets": list(NOVELAI_PRESET_MODELS) if key == "novelai" else [],
                    "model_presets_hint": NOVELAI_PRESET_HINT if key == "novelai" else "",
                    "defaults": _mask_secrets(self.store.platform_model(key)().model_dump(mode="json")),
                }
                for key, name in PLATFORM_NAMES.items()
            ],
            **self.models(),
            "presets": config["style"]["presets"],
            "proxy_password_set": bool(self.get_config().proxy.password),
        }

    async def _refresh_committed(self, values: Dict[str, Any] | None = None) -> Dict[str, Any]:
        status = {"saved": True, "revision": self.store.revision, "recovery_pending": self.store.recovery_pending}
        warnings = []
        if self.store.recovery_pending:
            warnings.append("配置已保存，文件同步尚未完成；下次保存或重新加载插件时将先恢复已提交事务")
        self.runtime_refresh_pending = True
        try:
            if values is None:
                await self.refresh()
            else:
                await self.apply_settings(values)
        except Exception as exc:
            # 持久化已经成功。不得让运行时刷新故障把成功提交误报为保存失败。
            status["runtime_refresh_pending"] = True
            warnings.append("配置已保存，但运行时刷新未完成，请重新加载插件后检查")
            self.ctx.logger.warning("配置已保存但运行时刷新失败: error_type=%s", type(exc).__name__)
        else:
            self.runtime_refresh_pending = False
        if warnings:
            status["warning"] = "；".join(warnings)
        return status

    async def discover_models(self, provider_json: str) -> Dict[str, Any]:
        payload = parse_json_object(provider_json)
        values = await asyncio.to_thread(self.store.model_discovery_config, payload)
        kind = payload["kind"]
        proxy = self.tasks.get_service().router._get_proxy_settings(kind)
        return await fetch_models(kind, values, proxy)

    async def save_provider(self, provider_json: str, revision: int) -> Dict[str, Any]:
        return await self._run_transaction(lambda: self._save_provider(provider_json, revision))

    async def delete_provider(self, provider_id: str, revision: int) -> Dict[str, Any]:
        return await self._run_transaction(lambda: self._delete_provider(provider_id, revision))

    async def set_provider_enabled(self, provider_id: str, enabled: bool, revision: int) -> Dict[str, Any]:
        return await self._run_transaction(lambda: self._set_provider_enabled(provider_id, enabled, revision))

    async def save_settings(self, config_json: str, revision: int) -> Dict[str, Any]:
        return await self._run_transaction(lambda: self._save_settings(config_json, revision))

    async def presets(self, operation: str = "list", name: str = "", preset_json: str = "") -> Dict[str, Any]:
        if operation in {"list", "get"}:
            async with self.lock:
                return await self._presets(operation, name, preset_json)
        return await self._run_transaction(lambda: self._presets(operation, name, preset_json))

    async def _save_provider(self, provider_json: str, revision: int) -> Dict[str, Any]:
        payload = parse_json_object(provider_json)
        result = await asyncio.to_thread(self.store.save_provider, payload, revision)
        result.update(await self._refresh_committed())
        self.ctx.logger.info("平台配置已保存: platform_id=%s kind=%s", result["id"], payload["kind"])
        return result

    async def _delete_provider(self, provider_id: str, revision: int) -> Dict[str, Any]:
        await asyncio.to_thread(self.store.delete_provider, provider_id, revision)
        status = await self._refresh_committed()
        self.ctx.logger.info("平台配置已移除: platform_id=%s", provider_id)
        return {"deleted": True, **status}

    async def _set_provider_enabled(self, provider_id: str, enabled: bool, revision: int) -> Dict[str, Any]:
        await asyncio.to_thread(self.store.set_provider_enabled, provider_id, enabled, revision)
        status = await self._refresh_committed()
        self.ctx.logger.info("平台启用状态已保存: platform_id=%s enabled=%s", provider_id, enabled)
        return {"enabled": enabled, **status}

    async def _save_settings(self, config_json: str, revision: int) -> Dict[str, Any]:
        values = parse_json_object(config_json)
        # 旧页面可能仍回传宿主字段；明确忽略这些已移出工作台的字段，避免阻止绘图设置保存。
        if values.keys() - {"plugin", "proxy", "general", "style", "clear_proxy_password"}:
            raise ValueError("工作台配置包含未知分类")
        values = workspace_config(values)
        if revision != self.store.revision:
            raise ValueError("配置已更新，请刷新后保存")
        current = self.get_config().model_dump(mode="json")
        updated = await asyncio.to_thread(self.store.save_common, values, current, revision)
        status = await self._refresh_committed(updated)
        review = self.store.settings.values["general"]
        self.ctx.logger.info(
            "审核配置已保存: revision=%s runtime_refresh_pending=%s "
            "prompt_enabled=%s prompt_model=%s prompt_timeout_seconds=%s prompt_retry_count=%s "
            "image_enabled=%s image_model=%s image_timeout_seconds=%s image_retry_count=%s",
            self.store.revision, self.runtime_refresh_pending,
            review["prompt_review_enabled"], review["prompt_review_model"],
            review["prompt_review_timeout_seconds"], review["prompt_review_retry_count"],
            review["image_review_enabled"], review["image_review_model"],
            review["image_review_timeout_seconds"], review["image_review_retry_count"],
        )
        return status

    async def _presets(self, operation: str = "list", name: str = "", preset_json: str = "") -> Dict[str, Any]:
        if operation not in {"list", "get", "save", "delete"} or len(name) > 80:
            raise ValueError("预设操作或名称无效")
        snapshot = await asyncio.to_thread(self.store.public_snapshot)
        current = snapshot["settings"]
        presets = current["style"]["presets"]
        target = next((item for item in presets if item["name"].casefold() == name.casefold()), None)
        if operation == "list":
            return {"presets": presets, "default_style": current["style"]["default_style"]}
        if operation == "get":
            if target is None:
                raise ValueError("预设不存在")
            return {"preset": target}
        if operation == "delete":
            if target is None:
                raise ValueError("预设不存在")
            presets.remove(target)
            if current["style"]["default_style"].casefold() == name.casefold():
                current["style"]["default_style"] = ""
        else:
            preset = _validate_fields(StylePresetConfig, parse_json_object(preset_json))
            if not preset["name"].strip() or len(preset["name"]) > 80 or len(presets) >= 100 and target is None:
                raise ValueError("预设名称必须为 1～80 个字符，最多保存 100 个预设")
            if target is not None:
                if any(
                    item is not target and item["name"].casefold() == preset["name"].casefold() for item in presets
                ):
                    raise ValueError("已有同名预设")
                if current["style"]["default_style"].casefold() == target["name"].casefold():
                    current["style"]["default_style"] = preset["name"]
                presets[presets.index(target)] = preset
            else:
                if any(item["name"].casefold() == preset["name"].casefold() for item in presets):
                    raise ValueError("已有同名预设")
                presets.append(preset)
        updated = await asyncio.to_thread(self.store.save_common, workspace_config(current), current, snapshot["revision"])
        status = await self._refresh_committed(updated)
        return {"presets": presets, **status}

    async def streams(self, platform: str = "qq") -> Dict[str, Any]:
        if not platform or len(platform) > 80:
            raise ValueError("平台标识无效")
        raw = await self.ctx.chat.get_all_streams(platform=platform)
        # SDK 返回当前宿主序列化的真实聊天流，不构造资源归属 ID。
        from ..chat import ChatStreamService

        streams = ChatStreamService._unwrap_stream_list_result(raw)
        if not isinstance(streams, list):
            raise ValueError("宿主返回的聊天流列表格式不正确")
        items = []
        for stream in streams:
            if not isinstance(stream, dict):
                raise ValueError("宿主返回了不支持的聊天流结构")
            session_id = str(stream.get("session_id") or stream.get("stream_id") or "")
            name = stream.get("group_name") or stream.get("session_name") or stream.get("name")
            if not name:
                name = f"{stream.get('user_cardname') or stream.get('user_nickname') or stream.get('user_id') or '用户'}的私聊"
            if session_id:
                items.append({"id": session_id, "name": name, "platform": platform})
        return {"streams": items}
