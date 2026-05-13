from pathlib import Path
from typing import Any, ClassVar

import base64

from maibot_sdk import CONFIG_RELOAD_SCOPE_SELF, Command, MaiBotPlugin, ON_BOT_CONFIG_RELOAD, ON_MODEL_CONFIG_RELOAD, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .core.config import DrawpicConfig
from .core.draw_service import DrawService
from .core.message_utils import find_source_image
from .core.moderation import DrawpicModerationService
from .core.provider_router import ProviderRouter
from .core.session_preferences import SessionPreferenceStore
from .core.stream_service import ChatStreamService
from .core.task_store import DrawTaskStore
from .core.texts import build_draw_help_text, build_session_status_text


class DrawpicPlugin(MaiBotPlugin):
    """麦麦绘图插件。"""

    config_model = DrawpicConfig
    config_reload_subscriptions: ClassVar[tuple[str, ...]] = ("bot", "model")

    def __init__(self) -> None:
        super().__init__()
        self._session_preferences_path = Path(__file__).with_name("session_preferences.json")
        self._router: ProviderRouter | None = None
        self._session_store: SessionPreferenceStore | None = None
        self._stream_service: ChatStreamService | None = None
        self._moderation_service: DrawpicModerationService | None = None
        self._task_store = DrawTaskStore()
        self._draw_service: DrawService | None = None

    def _refresh_services(self) -> None:
        """刷新内部服务对象。"""

        existing_preferences: dict[str, dict[str, str]] = {}
        if self._session_store is not None:
            existing_preferences = dict(self._session_store.preferences)

        self._router = ProviderRouter(self.config)
        self._session_store = SessionPreferenceStore(
            path=self._session_preferences_path,
            router=self._router,
            logger=self.ctx.logger,
        )
        self._session_store.preferences = existing_preferences
        self._session_store.normalize_all()
        self._stream_service = ChatStreamService(self.ctx)
        self._moderation_service = DrawpicModerationService(self.config)
        self._draw_service = DrawService(
            ctx=self.ctx,
            router=self._router,
            stream_service=self._stream_service,
            moderation_service=self._moderation_service,
            task_store=self._task_store,
        )

    def _require_router(self) -> ProviderRouter:
        """返回当前 Provider 路由器。"""

        if self._router is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._router

    def _require_session_store(self) -> SessionPreferenceStore:
        """返回当前会话配置存储。"""

        if self._session_store is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._session_store

    def _require_stream_service(self) -> ChatStreamService:
        """返回聊天流服务。"""

        if self._stream_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._stream_service

    def _require_moderation_service(self) -> DrawpicModerationService:
        """返回审核服务。"""

        if self._moderation_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._moderation_service

    def _require_draw_service(self) -> DrawService:
        """返回绘图服务。"""

        if self._draw_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._draw_service

    def _get_session_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """获取当前会话的模型配置。"""

        return self._require_session_store().get_preference(stream_id, user_id, group_id, platform)

    def _set_session_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        *,
        model: str | None = None,
        openai_compatibility_mode: str | None = None,
    ) -> dict[str, str]:
        """更新当前会话的模型配置。"""

        return self._require_session_store().set_preference(
            stream_id,
            user_id,
            group_id,
            platform,
            model=model,
            openai_compatibility_mode=openai_compatibility_mode,
        )

    async def on_load(self) -> None:
        """插件加载时初始化平台。"""

        self._refresh_services()
        self._require_session_store().load()
        router = self._require_router()
        moderation_service = self._require_moderation_service()
        self.ctx.logger.info(
            "麦麦绘图插件已加载: default_model=%s timeout=%ss openai_models=%s google_models=%s prompt_review=%s image_review=%s session_pref_count=%s",
            router.resolve_default_model(),
            router.resolve_request_timeout_seconds(),
            len(router.get_openai_models()),
            len(router.get_google_models()),
            moderation_service.is_prompt_review_enabled(),
            moderation_service.is_image_review_enabled(),
            len(self._require_session_store().preferences),
        )

    async def on_unload(self) -> None:
        """插件卸载回调。"""

        self._require_draw_service().cancel_background_tasks()
        self._require_session_store().save()
        self.ctx.logger.info("麦麦绘图插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置变更时重新初始化平台。"""

        del config_data
        if scope in {CONFIG_RELOAD_SCOPE_SELF, ON_MODEL_CONFIG_RELOAD, ON_BOT_CONFIG_RELOAD}:
            self._refresh_services()
            self._require_session_store().normalize_all()
            self._require_session_store().save()
            router = self._require_router()
            moderation_service = self._require_moderation_service()
            self.ctx.logger.info(
                "麦麦绘图插件配置已更新: scope=%s version=%s default_model=%s timeout=%ss openai_models=%s google_models=%s prompt_review=%s image_review=%s",
                scope,
                version,
                router.resolve_default_model(),
                router.resolve_request_timeout_seconds(),
                len(router.get_openai_models()),
                len(router.get_google_models()),
                moderation_service.is_prompt_review_enabled(),
                moderation_service.is_image_review_enabled(),
            )

    async def _start_background_draw_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        requested_model: str = "",
        requested_openai_compatibility_mode: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        notify_start: bool = True,
    ) -> dict[str, Any]:
        """按当前会话设置启动后台文生图。"""

        draw_service = self._require_draw_service()
        session_preference = self._get_session_preference(stream_id, user_id, group_id, platform_name)
        resolved_model = draw_service.resolve_model_name(
            requested_model or session_preference["model"],
            allow_unknown_model=False,
        )
        resolved_openai_mode = self._require_router().resolve_openai_compatibility_mode(
            requested_openai_compatibility_mode or session_preference["openai_compatibility_mode"]
        )
        provider_name = self._require_router().get_model_provider(resolved_model)
        if not provider_name:
            raise ValueError(f"指定模型不可用：{resolved_model}")

        await draw_service.review_prompt_or_raise(prompt)
        self.ctx.logger.info(
            "收到文生图请求: stream_id=%s user_id=%s group_id=%s platform=%s provider=%s model=%s openai_mode=%s timeout=%ss prompt_preview=%s",
            stream_id,
            user_id,
            group_id,
            platform_name,
            provider_name,
            resolved_model,
            resolved_openai_mode,
            draw_service.resolve_request_timeout_seconds(),
            prompt[:120],
        )
        return await draw_service.start_background_draw_request(
            prompt=prompt,
            stream_id=stream_id,
            resolved_model=resolved_model,
            resolved_openai_mode=resolved_openai_mode,
            provider_name=provider_name,
            user_id=user_id,
            group_id=group_id,
            platform_name=platform_name,
            notify_start=notify_start,
        )

    @Tool(
        "draw",
        description="根据提示词创建图片，并发送到当前聊天流",
        parameters=[
            ToolParameterInfo(
                name="prompt",
                param_type=ToolParamType.STRING,
                description="图片提示词，尽量描述清楚主体、风格和画面内容",
                required=True,
            ),
            ToolParameterInfo(
                name="stream_id",
                param_type=ToolParamType.STRING,
                description="当前聊天流 ID",
                required=True,
            ),
            ToolParameterInfo(
                name="model",
                param_type=ToolParamType.STRING,
                description="可选，指定要使用的图片模型；未传时使用当前会话模型",
                required=False,
            ),
            ToolParameterInfo(
                name="user_id",
                param_type=ToolParamType.STRING,
                description="可选，当前私聊对象的用户 ID，用于回传时定位真实聊天流",
                required=False,
            ),
            ToolParameterInfo(
                name="group_id",
                param_type=ToolParamType.STRING,
                description="可选，当前群聊的群组 ID，用于回传时定位真实聊天流",
                required=False,
            ),
            ToolParameterInfo(
                name="platform",
                param_type=ToolParamType.STRING,
                description="可选，当前平台名称，默认 qq",
                required=False,
            ),
        ],
    )
    async def handle_draw(
        self,
        prompt: str,
        stream_id: str,
        model: str = "",
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """创建图片。"""

        if not prompt.strip():
            return {"success": False, "message": "提示词不能为空"}
        if not stream_id.strip():
            return {"success": False, "message": "当前聊天流 ID 为空，无法回传图片"}

        try:
            return await self._start_background_draw_request(
                prompt=prompt.strip(),
                stream_id=stream_id.strip(),
                requested_model=model.strip(),
                user_id=user_id.strip() or str(kwargs.get("user_id") or "").strip(),
                group_id=group_id.strip() or str(kwargs.get("group_id") or "").strip(),
                platform_name=platform.strip() or str(kwargs.get("platform") or "qq").strip() or "qq",
            )
        except Exception as exc:
            self.ctx.logger.error("启动后台创建图片失败: %s", exc, exc_info=True)
            return {"success": False, "message": f"启动后台创建图片失败：{exc}"}

    @Tool(
        "edit_image",
        description="编辑当前聊天中的最近一张图片，或编辑指定消息中的图片",
        parameters=[
            ToolParameterInfo(
                name="prompt",
                param_type=ToolParamType.STRING,
                description="图片编辑提示词，描述希望修改成什么样",
                required=True,
            ),
            ToolParameterInfo(
                name="stream_id",
                param_type=ToolParamType.STRING,
                description="当前聊天流 ID",
                required=True,
            ),
            ToolParameterInfo(
                name="source_message_id",
                param_type=ToolParamType.STRING,
                description="可选，指定要编辑的源图片消息 ID；不填时自动取最近一张图片",
                required=False,
            ),
            ToolParameterInfo(
                name="source_image_base64",
                param_type=ToolParamType.STRING,
                description="可选，直接传入源图片 Base64；有值时优先使用它",
                required=False,
            ),
            ToolParameterInfo(
                name="model",
                param_type=ToolParamType.STRING,
                description="可选，指定要使用的图片模型；未传时使用当前会话模型",
                required=False,
            ),
            ToolParameterInfo(
                name="user_id",
                param_type=ToolParamType.STRING,
                description="可选，当前私聊对象的用户 ID，用于回传时定位真实聊天流",
                required=False,
            ),
            ToolParameterInfo(
                name="group_id",
                param_type=ToolParamType.STRING,
                description="可选，当前群聊的群组 ID，用于回传时定位真实聊天流",
                required=False,
            ),
            ToolParameterInfo(
                name="platform",
                param_type=ToolParamType.STRING,
                description="可选，当前平台名称，默认 qq",
                required=False,
            ),
        ],
    )
    async def handle_edit_image(
        self,
        prompt: str,
        stream_id: str,
        source_message_id: str = "",
        source_image_base64: str = "",
        model: str = "",
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """编辑图片。"""

        if not prompt.strip():
            return {"success": False, "message": "提示词不能为空"}
        if not stream_id.strip():
            return {"success": False, "message": "当前聊天流 ID 为空，无法回传图片"}

        try:
            draw_service = self._require_draw_service()
            normalized_stream_id = stream_id.strip()
            normalized_user_id = user_id.strip() or str(kwargs.get("user_id") or "").strip()
            normalized_group_id = group_id.strip() or str(kwargs.get("group_id") or "").strip()
            platform_name = platform.strip() or str(kwargs.get("platform") or "qq").strip() or "qq"
            session_preference = self._get_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                platform_name,
            )
            resolved_model = draw_service.resolve_model_name(model.strip() or session_preference["model"])
            resolved_openai_mode = session_preference["openai_compatibility_mode"]
            provider_name = self._require_router().get_model_provider(resolved_model)
            self.ctx.logger.info(
                "收到图生图请求: stream_id=%s user_id=%s group_id=%s platform=%s provider=%s model=%s openai_mode=%s timeout=%ss prompt_preview=%s source_message_id=%s has_source_base64=%s",
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                platform_name,
                provider_name,
                resolved_model,
                resolved_openai_mode,
                draw_service.resolve_request_timeout_seconds(),
                prompt[:120],
                source_message_id.strip(),
                bool(source_image_base64.strip()),
            )
            await draw_service.review_prompt_or_raise(prompt.strip())
            lookup_stream_id = await self._require_stream_service().resolve_live_stream_id(
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=platform_name,
            )
            self.ctx.logger.info(
                "图生图源消息查找使用聊天流: requested_stream_id=%s lookup_stream_id=%s",
                normalized_stream_id,
                lookup_stream_id,
            )
            image_base64, matched_message_id = await find_source_image(
                self.ctx,
                lookup_stream_id,
                source_message_id=source_message_id,
                source_image_base64=source_image_base64,
            )
            source_image_bytes = base64.b64decode(image_base64)
            self.ctx.logger.info(
                "图生图源图片已解析: stream_id=%s source_message_id=%s bytes=%s",
                normalized_stream_id,
                matched_message_id,
                len(source_image_bytes),
            )
            return await draw_service.start_background_edit_request(
                prompt=prompt.strip(),
                stream_id=normalized_stream_id,
                resolved_model=resolved_model,
                resolved_openai_mode=resolved_openai_mode,
                provider_name=provider_name,
                source_image_bytes=source_image_bytes,
                matched_message_id=matched_message_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform_name=platform_name,
            )
        except Exception as exc:
            self.ctx.logger.error("启动后台编辑图片失败: %s", exc, exc_info=True)
            return {"success": False, "message": f"启动后台编辑图片失败：{exc}"}

    @Tool(
        "draw_status",
        description="查询最近一个绘图后台任务，或查询指定 task_id 的绘图任务状态",
        parameters=[
            ToolParameterInfo(
                name="stream_id",
                param_type=ToolParamType.STRING,
                description="当前聊天流 ID，用于查询当前会话最近一个后台绘图任务",
                required=True,
            ),
            ToolParameterInfo(
                name="task_id",
                param_type=ToolParamType.STRING,
                description="可选，指定要查询的后台绘图任务 ID；不填时默认查询当前会话最近一个任务",
                required=False,
            ),
        ],
    )
    async def handle_draw_status(
        self,
        stream_id: str,
        task_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        del kwargs
        return self._require_draw_service().get_task_status_payload(stream_id=stream_id, task_id=task_id)

    @Command("draw_command", description="绘图命令", pattern=r"^/绘图(?:\s+(?P<content>.+))?$")
    async def handle_draw_command(
        self,
        stream_id: str = "",
        **kwargs: Any,
    ) -> tuple[bool, str, int]:
        """处理 /绘图 命令。"""

        matched_groups = kwargs.get("matched_groups", {})
        command_payload = str(matched_groups.get("content") or "").strip() if isinstance(matched_groups, dict) else ""
        normalized_stream_id = str(stream_id or "").strip()
        normalized_user_id = str(kwargs.get("user_id") or "").strip()
        normalized_group_id = str(kwargs.get("group_id") or "").strip()
        normalized_platform = str(kwargs.get("platform") or "qq").strip() or "qq"

        if not normalized_stream_id:
            return False, "当前聊天流不可用，无法执行绘图命令", 1

        if not command_payload or command_payload == "帮助":
            await self._require_draw_service().send_text_with_fallback(
                text=build_draw_help_text(self._require_router()),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已显示绘图帮助", 2

        session_preference = self._get_session_preference(
            normalized_stream_id,
            normalized_user_id,
            normalized_group_id,
            normalized_platform,
        )
        if command_payload == "状态":
            await self._require_draw_service().send_text_with_fallback(
                text=build_session_status_text(self._require_router(), session_preference),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已显示当前绘图状态", 2

        if command_payload.startswith("模型 "):
            model_name = command_payload[3:].strip()
            if not model_name:
                await self._require_draw_service().send_text_with_fallback(
                    text="请在“/绘图 模型”后面填写具体模型名。",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "未提供模型名", 1

            provider_name = self._require_router().get_model_provider(model_name)
            if not provider_name:
                await self._require_draw_service().send_text_with_fallback(
                    text=f"模型不存在：{model_name}\n{build_draw_help_text(self._require_router())}",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "模型不存在", 1

            next_preference = self._set_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                model=model_name,
            )
            await self._require_draw_service().send_text_with_fallback(
                text=f"当前会话绘图模型已切换为：{next_preference['model']}\n当前提供商：{provider_name}",
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已切换绘图模型", 2

        if command_payload.startswith("兼容模式 "):
            compatibility_mode = command_payload[5:].strip()
            if compatibility_mode not in {"auto", "images_api", "chat_completions", "novelai_images_api"}:
                await self._require_draw_service().send_text_with_fallback(
                    text="兼容模式仅支持：auto、images_api、chat_completions、novelai_images_api",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "兼容模式无效", 1

            next_preference = self._set_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                openai_compatibility_mode=compatibility_mode,
            )
            await self._require_draw_service().send_text_with_fallback(
                text=f"当前会话 OpenAI 兼容模式已切换为：{next_preference['openai_compatibility_mode']}",
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已切换 OpenAI 兼容模式", 2

        try:
            await self._start_background_draw_request(
                prompt=command_payload,
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform_name=normalized_platform,
            )
        except Exception as exc:
            self.ctx.logger.error("/绘图 命令启动失败: %s", exc, exc_info=True)
            await self._require_draw_service().send_text_with_fallback(
                text=f"绘图请求未能启动：{exc}",
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return False, "绘图命令执行失败", 1
        return True, "已开始处理绘图命令", 2


def create_plugin() -> DrawpicPlugin:
    """创建插件实例。"""

    return DrawpicPlugin()
