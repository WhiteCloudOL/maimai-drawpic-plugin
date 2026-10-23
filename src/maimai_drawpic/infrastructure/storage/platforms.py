"""按需添加的平台配置、密钥保护和旧 TOML 迁移。"""

from copy import deepcopy
from datetime import datetime
from functools import wraps
from hashlib import sha256
from threading import RLock
from maibot_sdk.config import extract_plugin_config_version, generate_plugin_config_schema
from pathlib import Path
from pydantic import BaseModel, ValidationError
from typing import Any, Dict, List, Mapping, Tuple
from uuid import uuid4
import json
import re
import shutil
import tomlkit

from ...domain.configuration.models import (
    DrawpicConfig,
    OpenAICompatibleInstanceConfig,
    StylePresetConfig,
    migrate_legacy_review_config,
)
from ...application.routing import ProviderRouter
from .atomic import write_json_atomically, write_text_atomically
from .config_recovery import is_reseeded_defaults, remove_reseeded_defaults
from .identifiers import migrate_model_identifiers, remap_preferences
from .preferences import SessionPreferenceStore
from .settings import LEGACY_REVIEW_SECTIONS, WorkspaceSettingsStore, read_json_file, workspace_config


PLATFORM_NAMES = {
    "openai": "OpenAI / 兼容服务",
    "google": "Google Gemini",
    "aliyun": "阿里百炼",
    "volcengine": "火山引擎",
    "siliconflow": "硅基流动",
    "zhipu": "智谱",
    "novelai": "NovelAI / NovelAPI",
    "agnes": "Agnes AI",
    "comfyui": "ComfyUI",
}
PLATFORM_DEFAULT_NAMES = {kind: kind for kind in PLATFORM_NAMES}
PLATFORM_DEFAULT_NAMES["openai"] = "OpenAI_Compatible"
COMMON_SECTIONS = ("plugin", "general", "style", "proxy")
HOST_SECTIONS = ("plugin", "proxy")
SECRET_FIELDS = {"api_key", "password"}


def common_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    """只保留宿主管理的非平台配置。"""
    result = {key: deepcopy(config[key]) for key in COMMON_SECTIONS if key in config}
    general = result.get("general", {})
    legacy_fallback = general.pop("fallback_model", "")
    if legacy_fallback and not general.get("fallback_models"):
        general["fallback_models"] = [legacy_fallback]
    return result


def host_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: deepcopy(config[key]) for key in HOST_SECTIONS if key in config}


def host_default_config(defaults: Dict[str, Any], config_path: Path) -> Dict[str, Any]:
    """只向 Runner 提供宿主默认节，并保留磁盘上尚待迁移的旧节。"""
    result = host_config(defaults)
    if not config_path.exists():
        return result
    # Runner 在 on_load 前按默认结构重建升级配置。这个同步配置回调必须
    # 先识别原文件中的旧节，否则 Runner 会在异步迁移前丢弃旧平台和设置。
    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    legacy_sections = set(document) & (set(defaults) - set(HOST_SECTIONS))
    if legacy_sections:
        for section in legacy_sections:
            result[section] = deepcopy(defaults[section])
        # 先让 on_load 在线程中按字节备份、检查冲突并迁移原文件；下一次
        # 加载只有宿主节时再由 Runner 升级版本，避免备份前就改写旧 TOML。
        result["plugin"]["config_version"] = extract_plugin_config_version(document)
    return result


def parse_json_object(value: str) -> Dict[str, Any]:
    if len(value.encode("utf-8")) > 60 * 1024:
        raise ValueError("配置超过 60 KiB，请精简配置内容")
    result = json.loads(value, parse_constant=lambda _: _invalid_number())
    if not isinstance(result, dict):
        raise ValueError("配置必须是对象")
    pending = [(result, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 16 or count > 5000:
            raise ValueError("配置嵌套或元素数量超过限制")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return result


def _invalid_number() -> None:
    raise ValueError("配置不能包含非有限数字")


def _mask_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "" if key in SECRET_FIELDS else _mask_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_secrets(item) for item in value]
    return deepcopy(value)


def _validate_fields(model: Any, values: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("配置字段必须是对象")
    unknown = values.keys() - model.model_fields.keys()
    if unknown:
        raise ValueError(f"未知配置字段: {', '.join(sorted(unknown))}")
    try:
        validated = model.model_validate(values)
    except ValidationError as exc:
        # 错误只返回字段位置与错误类型，不能把含密钥的输入值带回页面或日志。
        fields = [
            f"{'.'.join(map(str, error['loc']))}: {error['type']}"
            for error in exc.errors(include_input=False, include_context=False)
        ]
        raise ValueError("配置校验失败: " + "; ".join(fields)) from None

    def check_nested(value: Any, raw: Any) -> None:
        if isinstance(value, BaseModel) and isinstance(raw, dict):
            if raw.keys() - type(value).model_fields.keys():
                raise ValueError("嵌套配置包含未知字段")
            for key, child in raw.items():
                check_nested(value.__dict__[key], child)
        elif isinstance(value, list) and isinstance(raw, list):
            for child, original in zip(value, raw, strict=True):
                check_nested(child, original)

    check_nested(validated, values)
    return validated.model_dump(mode="json")


def _locked(method):
    @wraps(method)
    def synchronized(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return synchronized


def _payload_digest(payload: Dict[str, Any]) -> str:
    # 与 write_json_atomically 的序列化完全相同；恢复不覆盖任何第三种内容。
    return sha256((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).hexdigest()


class WorkspaceConfigStore:
    """拥有平台配置；未添加的平台在运行时明确禁用。"""

    def __init__(self, data_dir: Path, config_path: Path) -> None:
        self.path = data_dir / "platforms.json"
        self.config_path = config_path
        self.providers: List[Dict[str, Any]] = []
        self.revision = 0
        self.platform_revision = 0
        self.settings = WorkspaceSettingsStore(data_dir, config_path)
        self.transaction_path = data_dir / "workspace_config_transaction.json"
        self.recovery_pending = False
        self.pending_model_renames: Dict[str, str] = {}
        self._lock = RLock()

    @staticmethod
    def platform_model(kind: str) -> Any:
        if kind not in PLATFORM_NAMES:
            raise ValueError("未知绘图平台")
        return DrawpicConfig.model_fields[kind].annotation

    @_locked
    def initialize(self, legacy_config: Dict[str, Any]) -> Path | None:
        """平台配置成功持久化并备份之后，才移除 TOML 平台节。"""
        # 在写 JSON、重命名平台或移除任何 TOML 节之前完成全部冲突检查。
        original = self.config_path.read_bytes() if self.config_path.exists() else b""
        document = tomlkit.parse(original.decode("utf-8"))
        reseeded = is_reseeded_defaults(document) and self.path.exists() and self.settings.path.exists()
        if reseeded:
            # 已知完整默认模板没有用户绘图设置；两份权威 JSON 都必须有效，
            # 之后仍走原有事务与冲突校验，不能借修复跳过损坏文件或未提交数据。
            self._validate_platform_payload(read_json_file(self.path))
            self.settings.read_payload()
            document = host_config(document)
        self._recover_transaction(document)
        self.settings.check_legacy_conflicts(document)
        settings_revision = self.settings.read_payload().get("revision", 0) if self.settings.path.exists() else 0
        if self.path.exists():
            payload = read_json_file(self.path)
            self.providers, self.platform_revision = self._validate_platform_payload(payload)
            self.revision = max(self.platform_revision, settings_revision)
            legacy = WorkspaceConfigStore(self.path.parent, self.config_path)
            legacy._import_legacy_platforms(document)

            def comparable(records):
                return sorted((item["kind"], json.dumps(item["config"], sort_keys=True)) for item in records)

            if legacy.providers and comparable(legacy.providers) != comparable(self.providers):
                raise ValueError(
                    "旧 config.toml 与 platforms.json 存在冲突，已保留原文件。请先备份，确认保留哪份平台配置，再移走另一份后重新加载插件。"
                )
        else:
            self._import_legacy_platforms(legacy_config)
            self.revision = self.platform_revision = max(1, settings_revision)
            self._save()

        recovery_backup = None
        if reseeded:
            recovery_backup = remove_reseeded_defaults(self.config_path, self.path.parent, original)
        else:
            current = self.config_path.read_bytes() if self.config_path.exists() else b""
            if current != original:
                raise ValueError("config.toml 已在外部修改，已保留原文件，请重新加载插件")
        if self.config_path.exists():
            document = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            if any(key in document for key in PLATFORM_NAMES):
                backup_dir = self.path.parent / "migration_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"config-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.toml"
                shutil.copy2(self.config_path, backup)
                if backup.read_bytes() != self.config_path.read_bytes():
                    raise RuntimeError("配置备份校验失败，保留原配置")
                if self.config_path.read_bytes() != original:
                    raise ValueError("config.toml 已在外部修改，已保留原文件，请重新加载插件")
                for kind in PLATFORM_NAMES:
                    document.pop(kind, None)
                write_text_atomically(self.config_path, tomlkit.dumps(document))

        self.settings.initialize(legacy_config)
        self.revision = max(self.platform_revision, self.settings.revision)
        migrate_model_identifiers(self, PLATFORM_NAMES, PLATFORM_DEFAULT_NAMES)
        return recovery_backup

    def _import_legacy_platforms(self, legacy_config: Dict[str, Any]) -> None:
        """只导入有实际配置的平台，用于首次迁移与无副作用冲突检查。"""
        normalized = DrawpicConfig.model_validate(migrate_legacy_review_config(legacy_config)).model_dump(mode="json")
        defaults = DrawpicConfig().model_dump(mode="json")
        for kind in PLATFORM_NAMES:
            values = deepcopy(normalized[kind])
            instances = values.pop("instances", []) if kind == "openai" else []
            # 只迁移启用、填过密钥或修改过参数的平台，不展示无用的默认平台。
            meaningful = bool(values.get("api_key", "")) and values.get("api_key") != defaults[kind].get("api_key")
            meaningful = meaningful or (kind == "comfyui" and values.get("enabled", False))
            meaningful = meaningful or any(
                value != defaults[kind].get(key) for key, value in values.items() if key != "enabled"
            )
            if meaningful:
                self.providers.append(self._new_record(kind, PLATFORM_NAMES[kind], values))
            for index, instance in enumerate(instances, 1):
                values = deepcopy(instance)
                name = values.pop("name") or f"兼容服务 {index}"
                model_text = values.pop("models")
                values["models"] = [
                    f"{display}={upstream}" if display != upstream else upstream
                    for display, upstream in ProviderRouter._parse_model_routes(model_text)
                ]
                for field in ("model_size_overrides", "extra_parameters"):
                    values[field] = ProviderRouter._parse_key_value_text(values[field])
                self.providers.append(self._new_record("openai", name, values))

    def _validate_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(record, dict) or set(record) != {"id", "kind", "name", "config"}:
            raise ValueError("平台记录格式错误")
        if not isinstance(record["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", record["id"]):
            raise ValueError("平台 ID 格式错误")
        if (
            not isinstance(record["name"], str)
            or not record["name"].strip()
            or len(record["name"]) > 80
            or any(ord(char) < 32 for char in record["name"])
        ):
            raise ValueError("平台名称应为 1～80 个字符")
        if not isinstance(record["kind"], str) or record["kind"] not in PLATFORM_NAMES:
            raise ValueError("未知绘图平台")
        result = deepcopy(record)
        # 加载旧记录时保留首尾空格，交给统一迁移逐个转换为下划线。
        result["name"] = record["name"]
        result["config"] = _validate_fields(self.platform_model(record["kind"]), record["config"])
        if record["kind"] == "novelai":
            # 仅在完成原字段类型校验后合并，保留旧顺序、去重且不丢自定义模型。
            values = result["config"]
            values["models"] = list(dict.fromkeys(
                model.strip() for model in values["models"] + values.pop("custom_models", []) if model.strip()
            ))
        if record["kind"] == "openai":
            result["config"]["instances"] = []
        return result

    def _new_record(self, kind: str, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        base, suffix = name, 2
        while any(item["name"].strip().casefold() == name.strip().casefold() for item in self.providers):
            name = f"{base[:70]} {suffix}"
            suffix += 1
        return self._validate_record({"id": uuid4().hex, "kind": kind, "name": name, "config": config})

    def _validate_platform_payload(self, payload: Any) -> tuple[List[Dict[str, Any]], int]:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "revision", "providers"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or not isinstance(payload["providers"], list)
        ):
            raise ValueError("platforms.json 格式或版本不受支持")
        providers = [self._validate_record(record) for record in payload["providers"]]
        ids = [item["id"] for item in providers]
        if len(ids) != len(set(ids)):
            raise ValueError("platforms.json 存在重复平台 ID")
        if type(payload["revision"]) is not int or payload["revision"] < 0:
            raise ValueError("platforms.json 修订号无效")
        return providers, payload["revision"]

    def _platform_payload(self, providers=None, revision=None) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "revision": self.platform_revision if revision is None else revision,
            "providers": self.providers if providers is None else providers,
        }

    def _save(self, providers=None, revision=None) -> None:
        write_json_atomically(self.path, self._platform_payload(providers, revision))

    def _validate_transaction(self, transaction: Any) -> None:
        if (
            not isinstance(transaction, dict)
            or type(transaction.get("schema_version")) is not int
            or transaction["schema_version"] not in (1, 2)
            or set(transaction) != {"schema_version", "platforms", "settings"} | (
                {"preferences"} if transaction["schema_version"] == 2 else set()
            )
        ):
            raise ValueError("工作台配置事务格式不正确，已保留原文件")
        for key in ("platforms", "settings", *(["preferences"] if transaction["schema_version"] == 2 else [])):
            entry = transaction[key]
            if (
                not isinstance(entry, dict)
                or set(entry) != {"previous_sha256", "payload"}
                or not isinstance(entry["previous_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", entry["previous_sha256"])
            ):
                raise ValueError("工作台配置事务格式不正确，已保留原文件")
        providers, revision = self._validate_platform_payload(transaction["platforms"]["payload"])
        settings = self.settings.validate_payload(transaction["settings"]["payload"])
        if settings["schema_version"] != 2 or settings["revision"] != revision:
            raise ValueError("工作台配置事务修订号不一致，已保留原文件")
        names = [record["name"].casefold() for record in providers]
        if len(names) != len(set(names)):
            raise ValueError("工作台配置事务包含重复平台名称，已保留原文件")
        if transaction["schema_version"] == 2:
            SessionPreferenceStore.validate_payload(transaction["preferences"]["payload"])

    def _materialize_transaction(self, transaction: Dict[str, Any]) -> None:
        entries = [(self.path, transaction["platforms"]), (self.settings.path, transaction["settings"])]
        if transaction["schema_version"] == 2:
            entries.append((self.path.parent / "session_preferences.json", transaction["preferences"]))
        pending = []
        # 必须先校验全部文件，再写任意一个；损坏或未知内容不能被恢复操作抹掉。
        for path, entry in entries:
            digest = sha256(path.read_bytes()).hexdigest()
            committed = _payload_digest(entry["payload"])
            if digest not in (entry["previous_sha256"], committed):
                raise ValueError("工作台配置事务与现有文件存在冲突，已保留原文件，请从备份核对后恢复")
            if digest != committed:
                pending.append((path, entry["payload"]))
        for path, payload in pending:
            write_json_atomically(path, payload)
        self.transaction_path.unlink()
        self.recovery_pending = False

    def _recover_transaction(self, document: Dict[str, Any] | None = None) -> None:
        if not self.transaction_path.exists():
            self.recovery_pending = False
            return
        transaction = read_json_file(self.transaction_path)
        self._validate_transaction(transaction)
        if document:
            legacy = WorkspaceConfigStore(self.path.parent, self.config_path)
            legacy._import_legacy_platforms(document)
            providers = transaction["platforms"]["payload"]["providers"]

            def comparable(records):
                return sorted((item["kind"], json.dumps(item["config"], sort_keys=True)) for item in records)

            saved = transaction["settings"]["payload"]["settings"]
            restored = workspace_config(
                DrawpicConfig.model_validate(migrate_legacy_review_config(document)).model_dump(mode="json")
            )
            sections = set(document) & {"general", "style"}
            if set(document) & set(LEGACY_REVIEW_SECTIONS):
                sections.add("general")
            if (legacy.providers and comparable(legacy.providers) != comparable(providers)) or any(
                saved[section] != restored[section] for section in sections
            ):
                raise ValueError("旧 config.toml 与已提交配置事务存在冲突，已保留原文件")
        self._materialize_transaction(transaction)

    def _check_disk_state(self) -> None:
        providers, revision = self._validate_platform_payload(read_json_file(self.path))
        payload = self.settings.read_payload()
        values = workspace_config(DrawpicConfig.model_validate(payload["settings"]).model_dump(mode="json"))
        if (
            providers != self.providers
            or revision != self.platform_revision
            or values != self.settings.values
            or payload.get("revision", 0) != self.settings.revision
        ):
            raise ValueError("配置文件已在外部修改，已保留原文件，请重新加载插件后再保存")

    def _commit_rename(
        self, providers: List[Dict[str, Any]], values: Dict[str, Any], revision: int,
        preferences: Tuple[Dict[str, Any], str] | None = None,
    ) -> None:
        transaction = {
            "schema_version": 1,
            "platforms": {
                "previous_sha256": sha256(self.path.read_bytes()).hexdigest(),
                "payload": self._platform_payload(providers, revision),
            },
            "settings": {
                "previous_sha256": sha256(self.settings.path.read_bytes()).hexdigest(),
                "payload": self.settings.payload(values, revision),
            },
        }
        if preferences is not None:
            transaction["schema_version"] = 2
            transaction["preferences"] = {"previous_sha256": preferences[1], "payload": preferences[0]}
        self._validate_transaction(transaction)
        # 日志原子发布是唯一提交点。之后的故障只表示物化待恢复，不能报告保存失败。
        write_json_atomically(self.transaction_path, transaction)
        self.providers, self.platform_revision, self.revision = providers, revision, revision
        self.settings.values, self.settings.revision = values, revision
        self.recovery_pending = True
        try:
            self._materialize_transaction(transaction)
        except Exception:
            # 完整快照已提交且包含 revision；启动或下次写入必须先恢复，绝不静默丢弃日志。
            self.recovery_pending = True

    @_locked
    def public_snapshot(self) -> Dict[str, Any]:
        return {
            "revision": self.revision,
            "settings": _mask_secrets(self.settings.values),
            "providers": [
                {
                    **record,
                    "config": _mask_secrets(record["config"]),
                    "has_api_key": bool(record["config"].get("api_key", "")),
                }
                for record in self.providers
            ],
        }

    @_locked
    def model_discovery_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """合并连接草稿与已保存密钥，仅供内部只读请求使用，不修改配置。"""
        if payload.keys() - {"id", "kind", "config", "clear_api_key"}:
            raise ValueError("获取模型参数包含未知字段")
        kind, identifier, draft = payload.get("kind"), payload.get("id", ""), payload.get("config", {})
        if not isinstance(kind, str) or kind not in PLATFORM_NAMES or not isinstance(identifier, str):
            raise ValueError("获取模型的平台类型或 ID 无效")
        if not isinstance(draft, dict) or draft.keys() - {"api_key", "base_url"}:
            raise ValueError("获取模型仅接受服务地址和密钥")
        if any(not isinstance(value, str) or len(value) > 4096 for value in draft.values()):
            raise ValueError("服务地址和密钥应为不超过 4096 个字符的文本")
        clear = payload.get("clear_api_key", False)
        if type(clear) is not bool:
            raise ValueError("清除密钥标记无效")
        previous = next((item for item in self.providers if item["id"] == identifier), None)
        if identifier and (previous is None or previous["kind"] != kind):
            raise ValueError("平台不存在或类型不匹配，请刷新后重试")
        values = deepcopy(previous["config"]) if previous else self.platform_model(kind)().model_dump(mode="json")
        saved_key = values.get("api_key", "") if previous else ""
        values.update(draft)
        if not values.get("api_key", "").strip():
            values["api_key"] = "" if clear else saved_key
        return values

    @_locked
    def save_provider(self, payload: Dict[str, Any], revision: int) -> Dict[str, Any]:
        if revision != self.revision:
            raise ValueError("配置已被其他页面更新，请刷新后再保存")
        if payload.keys() - {"id", "kind", "name", "config", "clear_api_key"}:
            raise ValueError("平台参数包含未知字段")
        if not {"kind", "name", "config"} <= payload.keys() or not isinstance(payload["name"], str):
            raise ValueError("平台类型、名称与配置为必填项")
        if any(char.isspace() for char in payload["name"]):
            raise ValueError("平台名称不能包含空格，可使用中文、英文和下划线 _")
        if type(revision) is not int or type(payload.get("clear_api_key", False)) is not bool:
            raise ValueError("平台参数类型无效")
        identifier = payload.get("id", "")
        previous = next((item for item in self.providers if item["id"] == identifier), None)
        if identifier and previous is None:
            raise ValueError("平台不存在，请刷新列表")
        kind = payload["kind"]
        if previous is not None and kind != previous["kind"]:
            raise ValueError("平台类型不能修改，请新建平台")
        if any(
            item["name"].strip().casefold() == payload["name"].strip().casefold() and item["id"] != identifier
            for item in self.providers
        ):
            raise ValueError("平台名称不能重复")
        if previous is None and len(self.providers) >= 40:
            raise ValueError("最多添加 40 个平台实例")
        values = deepcopy(payload["config"])
        if not isinstance(values, dict):
            raise ValueError("平台配置必须是对象")
        for field in ("models", "custom_models"):
            if isinstance(values.get(field), list) and any(
                isinstance(model, str) and "=" in model for model in values[field]
            ):
                raise ValueError("模型列表仅填写真实模型 ID，不再支持显示名称或别名")
        if "instances" in values and values["instances"]:
            raise ValueError("请将兼容实例分别添加为平台")
        if previous is not None and not values.get("api_key", "") and not payload.get("clear_api_key", False):
            if "api_key" in previous["config"]:
                values["api_key"] = previous["config"]["api_key"]
        record = self._validate_record(
            {"id": identifier or uuid4().hex, "kind": kind, "name": payload["name"].strip(), "config": values}
        )
        updated = [record if item["id"] == identifier else item for item in self.providers]
        if previous is None:
            updated.append(record)
        renamed_settings = None
        preferences = None
        if previous is not None and previous["name"] != record["name"]:
            renamed_settings = deepcopy(self.settings.values)
            # 名称和模型本身都允许包含分隔符，只重写旧实例真正拥有的精确 selector。
            # 禁用实例也保留配置引用，提取模型目录时临时启用副本，不改变实际启用状态。
            catalog_record = deepcopy(previous)
            catalog_record["config"]["enabled"] = True
            models = ProviderRouter(self.effective_config({}, [catalog_record])).get_all_models()
            replacements = {f"{previous['name']}/{model}": f"{record['name']}/{model}" for model in models}
            general = renamed_settings["general"]
            general["default_model"] = replacements.get(general["default_model"], general["default_model"])
            for key in ("fallback_models", "image_edit_unsupported_models", "text_to_image_unsupported_models"):
                general[key] = [replacements.get(value, value) for value in general[key]]
            renamed_settings = self._validate_common(renamed_settings, renamed_settings)
            preferences = remap_preferences(self.path.parent / "session_preferences.json", replacements)
        self._commit(updated, settings=renamed_settings, preferences=preferences)
        if renamed_settings is not None:
            self.pending_model_renames = {
                old: replacements.get(current, current) for old, current in self.pending_model_renames.items()
            }
            self.pending_model_renames.update(replacements)
        return {"id": record["id"], "revision": self.revision, "saved": True, "recovery_pending": self.recovery_pending}

    @_locked
    def set_provider_enabled(self, identifier: str, enabled: bool, revision: int) -> None:
        """只更新启用状态，不经页面回传或重建平台的其他配置。"""
        if type(revision) is not int or revision != self.revision:
            raise ValueError("配置已更新，请刷新后切换平台状态")
        if type(enabled) is not bool:
            raise ValueError("平台启用状态必须是布尔值")
        updated = deepcopy(self.providers)
        record = next((item for item in updated if item["id"] == identifier), None)
        if record is None:
            raise ValueError("平台不存在")
        record["config"]["enabled"] = enabled
        self._commit(updated)

    @_locked
    def save_preferences(self, values: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """偏好写入与配置事务互斥；先恢复已提交快照，再接收新的会话修改。"""
        self._recover_transaction()
        updated = SessionPreferenceStore.validate_payload(values)
        for value in updated.values():
            value["model"] = self.pending_model_renames.get(value["model"], value["model"])
        write_json_atomically(self.path.parent / "session_preferences.json", updated)
        return updated

    @_locked
    def delete_provider(self, identifier: str, revision: int) -> None:
        if revision != self.revision:
            raise ValueError("配置已更新，请刷新")
        updated = [item for item in self.providers if item["id"] != identifier]
        if len(updated) == len(self.providers):
            raise ValueError("平台不存在")
        self._commit(updated)

    @_locked
    def _commit(
        self, providers: List[Dict[str, Any]], *, settings: Dict[str, Any] | None = None,
        preferences: Tuple[Dict[str, Any], str] | None = None,
    ) -> None:
        self._recover_transaction()
        self._check_disk_state()
        if len(json.dumps(providers, ensure_ascii=False).encode("utf-8")) > 160 * 1024:
            raise ValueError("平台配置总大小超过 160 KiB，请精简配置")
        providers = deepcopy(providers)
        revision = self.revision + 1
        if settings is not None:
            self._commit_rename(providers, deepcopy(settings), revision, preferences)
        else:
            self._save(providers, revision)
            self.providers, self.platform_revision, self.revision = providers, revision, revision

    @_locked
    def effective_config(self, base: Dict[str, Any], providers: List[Dict[str, Any]] | None = None) -> DrawpicConfig:
        records = self.providers if providers is None else providers
        values = DrawpicConfig.model_validate({**base, **self.settings.values}).model_dump(mode="json")
        for kind in PLATFORM_NAMES:
            values[kind] = self.platform_model(kind)().model_dump(mode="json")
            values[kind]["enabled"] = False
        openai_records = [item for item in records if item["kind"] == "openai"]
        for record in records:
            if record["kind"] != "openai":
                values[record["kind"]] = deepcopy(record["config"])
        if openai_records:
            instance_model = OpenAICompatibleInstanceConfig
            for record in openai_records:
                instance = {key: value for key, value in record["config"].items() if key in instance_model.model_fields}
                instance["name"] = record["name"]
                instance["models"] = ", ".join(record["config"]["models"])
                for field in ("model_size_overrides", "extra_parameters"):
                    instance[field] = "\n".join(record["config"][field])
                values["openai"]["instances"].append(instance)
        return DrawpicConfig.model_validate(values)

    def _validate_common(self, values: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        if values.keys() - {"general", "style"}:
            raise ValueError("工作台仅维护通用与审核、风格预设")
        for section, fields in values.items():
            _validate_fields(DrawpicConfig.model_fields[section].annotation, fields)
        candidate = {**workspace_config(current), **deepcopy(values)}
        validated = workspace_config(DrawpicConfig.model_validate(candidate).model_dump(mode="json"))
        presets = validated["style"]["presets"]
        names = [item["name"].strip().casefold() for item in presets]
        if len(presets) > 100 or any(not name or len(name) > 80 for name in names) or len(names) != len(set(names)):
            raise ValueError("预设名称应为 1～80 字且不能重复，最多保存 100 个预设")
        if len(json.dumps(validated, ensure_ascii=False).encode("utf-8")) > 48 * 1024:
            raise ValueError("工作台配置总大小超过 48 KiB，请精简提示词模板")
        return validated

    @_locked
    def save_common(self, values: Dict[str, Any], current: Dict[str, Any], revision: int | None = None) -> Dict[str, Any]:
        self._recover_transaction()
        self._check_disk_state()
        if revision is not None and (type(revision) is not int or revision != self.revision):
            raise ValueError("配置已更新，请刷新后保存")
        validated = self._validate_common(values, self.settings.values or current)
        revision = self.revision + 1
        self.settings.save(validated, revision)
        self.revision = revision
        return validated

    @staticmethod
    def schema() -> Dict[str, Any]:
        schema = generate_plugin_config_schema(DrawpicConfig)
        # SDK 2.12 的列表子模型不输出 hint；在插件工作台补齐，避免模板占位符说明丢失。
        fields = schema["sections"]["style"]["fields"]["presets"]["item_fields"]
        for name, field in StylePresetConfig.model_fields.items():
            extra = field.json_schema_extra
            if isinstance(extra, dict) and extra.get("hint"):
                fields[name]["hint"] = extra["hint"]
        return schema

    @_locked
    def secrets(self) -> List[str]:
        return [item["config"]["api_key"] for item in self.providers if item["config"].get("api_key")]
