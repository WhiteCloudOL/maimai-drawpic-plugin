"""在一个既有后台任务内完成固定的素材准备与预设应用。"""

from hashlib import sha256
from typing import Any, Callable, Dict, List, Optional
import asyncio

from ...domain.references import PreparedRequest, ReferenceImage, ReferenceOptions, normalize_tag
from ...domain.configuration.models import StylePresetConfig
from ...domain.styles import StylePromptResolver, merge_prompt_parts
from ...domain.task_errors import TaskRequestError
from ...infrastructure.references.materials import MaterialSource
from ...infrastructure.storage.reference_assets import ReferenceAssetStore
from ..access import require_chat_access
from .recognition import ReferenceRecognizer
from .chat import read_chat_materials


class ReferencePreparation:
    def __init__(self, *, ctx: Any, config: Any, options: ReferenceOptions, prompt: str, style: str,
                 negative: str, stream_id: str, required_mode: str, images: List[ReferenceImage],
                 frozen: Dict[str, ReferenceImage], self_ids: List[str], streams: Any,
                 get_config: Optional[Callable[[], Any]] = None) -> None:
        self.ctx, self.config, self.options = ctx, config, options
        self.prompt, self.style, self.negative = prompt, style, negative
        self.stream_id, self.required_mode, self.streams = stream_id, required_mode, streams
        self.images, self.frozen, self.self_ids = images, frozen, self_ids
        self.recognizer = ReferenceRecognizer(ctx, config.general.references.material_model)
        self.sources = MaterialSource(ctx, config)
        self.get_config = get_config
        self.self_reference_used = False

    @property
    def self_reference_enabled(self) -> bool:
        live = self.get_config() if self.get_config is not None else self.config
        return (self.config.general.references.self_reference_enabled
                and self.options.self_reference != "off" and live.general.references.self_reference_enabled)

    def validate_self_reference_usage(self) -> None:
        """自我图片提交生成前仍须保持开启。"""
        if self.self_reference_used and not self.self_reference_enabled:
            raise TaskRequestError("SELF_REFERENCE_DISABLED", "自我参考已关闭，本次任务未继续使用自我图片")

    @property
    def expected_mode(self) -> str:
        if self.required_mode:
            return self.required_mode
        if self.images or self.options.reference_ids or self.options.self_reference == "required":
            return "edit_image"
        explicit = next((item for item in self.config.style.presets if item.name.casefold() == self.style.casefold()), None)
        if explicit is not None and explicit.preset_type == "image_to_image":
            return "edit_image"
        return ""

    def _preset_images(self, preset: Optional[StylePresetConfig]) -> List[ReferenceImage]:
        images: List[ReferenceImage] = []
        if preset is not None:
            for binding in preset.reference_bindings:
                image = self.frozen[binding.asset_id]
                images.append(ReferenceImage(image.raw, image.source, binding.role, binding.subject_id, image.url,
                                             image.asset_id, image.version, merge_prompt_parts((image.note, binding.note))))
        return images

    async def prepare(self, task_id: str) -> PreparedRequest:
        # 配置仅允许收紧在途请求；任务使用已读取的资产和模板版本。
        refs = self.config.general.references
        live = self.get_config() if self.get_config is not None else self.config
        if self.options.self_reference == "required" and not live.general.references.self_reference_enabled:
            raise TaskRequestError("SELF_REFERENCE_DISABLED", "自我参考已关闭")
        refs.self_reference_enabled = refs.self_reference_enabled and live.general.references.self_reference_enabled
        self.config.style.image_edit_presets_enabled = self.config.style.image_edit_presets_enabled and live.style.image_edit_presets_enabled
        for source in self.options.material_sources:
            enabled = live.general.references.allow_chat_material_search if source == "chat" else live.general.references.allow_web_material_search
            if not enabled:
                raise TaskRequestError("MATERIAL_SOURCE_DISABLED", f"素材来源已关闭：{source}")
        images = list(self.images)
        images.extend(self.frozen[identifier] for identifier in self.options.reference_ids)
        if self.self_reference_enabled:
            subject = "self" if self.options.self_reference == "required" else await self.recognizer.self_subject(
                self.options.user_request, refs.self_names)
            if subject == "uncertain":
                raise TaskRequestError("SELF_SUBJECT_UNCERTAIN", "无法确定要描绘谁，请明确是否描绘机器人自身")
            if subject == "self":
                if not self.self_ids:
                    raise TaskRequestError("SELF_REFERENCE_MISSING", "自我参考图库为空，请先上传图片")
                self.self_reference_used = True
                self.validate_self_reference_usage()
                images.extend(self.frozen[identifier] for identifier in self.self_ids)

        resolver = StylePromptResolver(self.config.style)
        initial_preset = resolver.select_for_task(
            self.style, self.expected_mode or ("edit_image" if images else "draw"), self.options.user_request or self.prompt,
        )
        images.extend(self._preset_images(initial_preset))
        if self.options.material_sources:
            plan = await self.recognizer.needs(self.options.user_request, source_count=len(self.images))
            chat_images: Optional[List[ReferenceImage]] = None
            if plan.chat_followup and "chat" in self.options.material_sources:
                context = await self.streams.existing_stream_context(self.stream_id)
                if not context:
                    raise TaskRequestError("STREAM_UNAVAILABLE", "继续改图需要可访问的聊天记录")
                require_chat_access(live.general, context, self.ctx.logger)
                try:
                    chat_images = await read_chat_materials(
                        self.ctx, self.stream_id, message_limit=min(
                            refs.chat_material_search_limit, live.general.references.chat_material_search_limit,
                        ),
                    )
                except TaskRequestError:
                    raise
                except Exception as exc:
                    raise TaskRequestError("CHAT_MATERIAL_UNAVAILABLE", f"聊天素材读取失败（{type(exc).__name__}）") from exc
                def previous_image() -> Optional[ReferenceImage]:
                    return next((candidate for candidate in chat_images if not any(candidate.raw == image.raw for image in self.images)), None)
                previous = await asyncio.to_thread(previous_image)
                if previous is None:
                    raise TaskRequestError("MATERIAL_MISSING", "没有找到要接续的前图，请回复或补充那张图片")
                images.append(previous)
            visual_calls = 0
            for need in plan.needs:
                self_enabled = self.self_reference_enabled
                if need.role == "identity" and (need.kind == "bot" or self_enabled and normalize_tag(need.subject) in {normalize_tag(name) for name in refs.self_names}):
                    if not self_enabled:
                        continue
                    if not any(image.source == "self" for image in images):
                        raise TaskRequestError("SELF_REFERENCE_MISSING", "机器人自身形象需要已启用的自我参考，不能用同名网图替代")
                    continue
                if need.kind != "user" and (not need.web_search or "web" not in self.options.material_sources):
                    continue
                found = False
                candidates = list(images)
                for source in ("existing", "web"):
                    if source == "web":
                        if "web" not in self.options.material_sources or not need.web_search:
                            continue
                        if need.kind == "user" or need.subject.strip() in {"用户", "我", "本人", "user"}:
                            raise TaskRequestError("MATERIAL_MISSING", "用户本人形象需要明确提供照片，不能使用同名网图")
                        try:
                            candidates = await self.sources.web(need.query, subject=need.mention)
                        except TaskRequestError:
                            raise
                        except Exception as exc:
                            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", f"网络素材获取失败（{type(exc).__name__}）") from exc
                    for candidate in candidates:
                        self.validate_self_reference_usage()
                        if visual_calls >= 12:
                            raise TaskRequestError("MATERIAL_BUDGET_EXCEEDED", "素材识别已达到本次 12 张次上限，请直接补充参考图")
                        visual_calls += 1
                        if await self.recognizer.matches(candidate, need):
                            # 同一真实图片可承担多个用途，最终仅发送一次。
                            images.append(ReferenceImage(candidate.raw, candidate.source, need.role, need.subject, candidate.url))
                            found = True
                            break
                    if found:
                        break
                if not found:
                    raise TaskRequestError("MATERIAL_MISSING", f"未找到符合 {need.subject}（{need.role}）的参考图片，请补图")

        mode = "edit_image" if images else "draw"
        if self.required_mode and mode != self.required_mode:
            raise TaskRequestError("SOURCE_IMAGE_REQUIRED" if mode == "draw" else "TASK_MODE_CONFLICT",
                                   "图生图必须有真实源图片" if mode == "draw" else "文生图不能隐式加入参考图，请改用图生图")
        preset = resolver.select_for_task(self.style, mode, self.options.user_request or self.prompt)
        if preset is not initial_preset:
            images.extend(self._preset_images(preset))
        unique: Dict[str, ReferenceImage] = {}
        uses: Dict[str, List[str]] = {}
        digests = await asyncio.to_thread(lambda: [sha256(image.raw).hexdigest() for image in images])
        for image, digest in zip(images, digests, strict=True):
            if digest not in unique or not unique[digest].url and image.url:
                unique[digest] = image
            label = f"{image.role}: {image.subject}".strip(": ")
            if image.note:
                label += "; " + image.note
            uses.setdefault(digest, [])
            if label not in uses[digest]:
                uses[digest].append(label)
        if len(unique) > 8 or sum(len(image.raw) for image in unique.values()) > 40 * 1024 * 1024:
            raise TaskRequestError("REFERENCE_LIMIT_EXCEEDED", "合并后的源图最多 8 张、总计 40 MiB")
        # 同图去重后仍保留所有来源的约束，不能因上传图覆盖参考图而绕过多图确认。
        sources = {image.source for image in images}
        if len(unique) > 1 and sources & {"self", "preset"}:
            if "self" in sources and not (refs.multi_reference_confirmed or self.options.multi_reference_confirmed):
                raise TaskRequestError("MULTI_REFERENCE_CONFIRMATION_REQUIRED", "请先确认所用模型支持自我参考和其他图片合用")
            if preset is not None and preset.reference_bindings and not (preset.multi_reference_confirmed or self.options.multi_reference_confirmed):
                raise TaskRequestError("MULTI_REFERENCE_CONFIRMATION_REQUIRED", "请先确认所用模型支持预设的多图合用方式")
            if self.options.reference_ids and not self.options.multi_reference_confirmed:
                raise TaskRequestError("MULTI_REFERENCE_CONFIRMATION_REQUIRED", "直接使用图库多图时，请先确认模型支持多图参考")
        resolved = resolver.resolve(style_name=preset.name if preset is not None else "none", user_prompt=self.prompt,
                                    user_negative_prompt=self.negative, task_type=mode)
        prompt = resolved.positive_prompt
        if unique:
            mapping = "\n".join(f"Image {index}: {', '.join(uses[digest])}" for index, digest in enumerate(unique, 1))
            prompt += "\nReference image uses (apply only the listed features):\n" + mapping
        self.ctx.logger.info("素材准备完成: task_id=%s task_type=%s source_image_count=%s preset=%s",
                             task_id, mode, len(unique), resolved.style_name)
        self.validate_self_reference_usage()
        return PreparedRequest(prompt, resolved.negative_prompt_template, [image.raw for image in unique.values()],
                               [image.url for image in unique.values()], mode, resolved.style_name,
                               len(unique) > 1 and bool(sources - {"input"}))


async def freeze_reference_request(*, ctx: Any, config: Any, store: ReferenceAssetStore, streams: Any,
                                   prompt: str, style: str, negative: str, stream_id: str,
                                   options: ReferenceOptions, images: List[bytes], urls: List[str],
                                   required_mode: str = "", get_config: Optional[Callable[[], Any]] = None) -> ReferencePreparation:
    style = style.strip()
    refs = config.general.references
    if options.self_reference == "required" and not refs.self_reference_enabled:
        raise TaskRequestError("SELF_REFERENCE_DISABLED", "自我参考未启用")
    if not refs.self_reference_enabled and (options.self_reference_ids or options.self_reference_tags):
        raise TaskRequestError("SELF_REFERENCE_DISABLED", "自我参考未启用，不能指定自身图片或 tag")
    for source in options.material_sources:
        if not (refs.allow_chat_material_search if source == "chat" else refs.allow_web_material_search):
            raise TaskRequestError("MATERIAL_SOURCE_DISABLED", f"素材来源尚未开启：{source}")
    if "chat" in options.material_sources:
        context = await streams.existing_stream_context(stream_id) if stream_id else None
        if not context:
            raise TaskRequestError("STREAM_UNAVAILABLE", "聊天素材搜索需要真实可访问的 stream_id")
        require_chat_access(config.general, context, ctx.logger)
    resolver = StylePromptResolver(config.style)
    frozen: Dict[str, ReferenceImage] = {}
    self_ids: List[str] = []
    if refs.self_reference_enabled and options.self_reference != "off":
        self_ids = options.self_reference_ids or list(refs.self_reference_ids)
        if not self_ids:
            snapshot = await asyncio.to_thread(store.snapshot)
            if any(item["kind"] == "self" for item in snapshot["assets"]):
                self_ids = [await asyncio.to_thread(store.select_self, options.self_reference_tags, options.user_request)]
        if len(self_ids) > 1 and not (options.multi_reference_confirmed or refs.multi_reference_confirmed and self_ids == refs.self_reference_ids):
            raise TaskRequestError("MULTI_REFERENCE_CONFIRMATION_REQUIRED", "请先确认模型支持所选自我参考图片")
        if options.self_reference == "required" and not self_ids:
            raise TaskRequestError("SELF_REFERENCE_MISSING", "自我参考图库为空，请先上传参考图片")
        for identifier in self_ids:
            frozen[identifier] = await asyncio.to_thread(store.read, identifier, kind="self", subject="bot")
    for identifier in options.reference_ids:
        frozen[identifier] = await asyncio.to_thread(store.read, identifier, kind="preset", role="base")
    explicit = next((item for item in config.style.presets if item.name.casefold() == style.casefold()), None)
    if explicit is not None and explicit.preset_type == "image_to_image" and not required_mode:
        required_mode = "edit_image"
    if required_mode == "draw" and (images or self_ids or options.reference_ids or options.material_sources or explicit is not None and explicit.reference_bindings):
        raise TaskRequestError("TASK_MODE_CONFLICT", "文生图不能使用会加入图片的参考选项，请改用 edit_image")
    modes = [required_mode] if required_mode else ["draw", "edit_image"]
    for mode in modes:
        if not required_mode and explicit is not None and explicit.preset_type == "image_to_image" and mode == "draw":
            continue
        try:
            preset = resolver.select_for_task(style, mode, options.user_request or prompt)
        except ValueError:
            if required_mode:
                raise
            continue  # 自动模式只冻结适用于该模式的候选，最终模式确定后仍严格校验显式选择。
        if preset is not None:
            for binding in preset.reference_bindings:
                frozen[binding.asset_id] = await asyncio.to_thread(store.read, binding.asset_id, kind="preset",
                                                                  role=binding.role, subject=binding.subject_id)
    if required_mode == "edit_image" and not (images or frozen or options.material_sources):
        raise TaskRequestError("SOURCE_IMAGE_REQUIRED", "图生图需要真实源图片，请提供图片或选择已开启的参考来源")
    return ReferencePreparation(ctx=ctx, config=config.model_copy(deep=True), options=options, prompt=prompt, style=style,
                                negative=negative, stream_id=stream_id, required_mode=required_mode,
                                images=[ReferenceImage(raw, "input", url=url) for raw, url in zip(images, urls, strict=True)],
                                frozen=frozen, self_ids=self_ids, streams=streams, get_config=get_config)
