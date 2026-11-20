"""将旧平台名称、模型别名和模型引用迁成统一的 平台/模型 标识。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Set, Tuple
from uuid import uuid4
import re

from ...application.routing import ProviderRouter
from .preferences import SessionPreferenceStore
from .settings import read_json_file

if TYPE_CHECKING:
    from .platforms import WorkspaceConfigStore


def _name_plan(label: str, default_name: str, original: str) -> Tuple[str, str]:
    """类型说明不作为实例名；只修复已知旧默认名及其自动编号。"""
    if re.search(r"\s|/", label):
        for old_default in (label, re.sub(r"\s", "_", label)):
            match = re.fullmatch(re.escape(old_default) + r"(?:[ _]([1-9][0-9]*))?", original)
            if match is not None:
                return default_name + (f"_{match[1]}" if match[1] else ""), default_name
    normalized = re.sub(r"\s", "_", original)
    return normalized, normalized


def normalize_model_identifiers(
    providers: List[Dict[str, Any]], labels: Mapping[str, str], defaults: Mapping[str, str], repairs: List[str]
) -> List[Dict[str, Any]]:
    """在写盘前校验旧模型列表和覆盖项，并计算新标识。"""
    result = deepcopy(providers)
    plans = [_name_plan(labels[item["kind"]], defaults[item["kind"]], item["name"]) for item in providers]
    # 先保留已有合法自定义名称，旧默认名不能抢占“OpenAI_Compatible”或“平台_A”等实例。
    reserved = {item["name"].casefold() for item, (name, _) in zip(providers, plans, strict=True)
                if item["name"] == name}
    used: Set[str] = set()
    for platform_index, (record, (base, stem)) in enumerate(zip(result, plans, strict=True), start=1):
        original = record["name"]
        name, suffix = base, 2
        while name.casefold() in used or (original != base and name.casefold() in reserved):
            ending = f"_{suffix}"
            name = stem[:80 - len(ending)] + ending
            suffix += 1
        record["name"] = name
        used.add(name.casefold())
        config = record["config"]
        aliases: Dict[str, str] = {}
        incomplete: Set[str] = set()
        for key in ("models", "custom_models"):
            if key not in config:
                continue
            models = []
            for row, value in enumerate(config[key], start=1):
                location = f"平台 {platform_index} 的 {key} 第 {row} 项"
                if not value.strip():
                    repairs.append(f"{location} 为空，已清理")
                    continue
                entries = ProviderRouter._split_inline_items(value) if record["kind"] == "openai" else [value.strip()]
                for model in entries:
                    if record["kind"] == "openai" and "=" in model:
                        alias, model = (part.strip() for part in model.split("=", 1))
                        if not model or "=" in model:
                            repairs.append(f"{location} 缺少有效模型 ID，已跳过该映射")
                            incomplete.add(alias)
                            continue
                        if not alias:
                            repairs.append(f"{location} 缺少别名，已保留真实模型 ID")
                        elif aliases.setdefault(alias, model) != model:
                            repairs.append(f"{location} 重复定义别名，沿用首个有效映射，保留两个真实模型")
                    if model not in models:
                        models.append(model)
            config[key] = models
        for key in ("model_size_overrides", "model_endpoint_overrides"):
            if key not in config:
                continue
            overrides: Dict[str, str] = {}
            priorities: Dict[str, bool] = {}
            for row, item in enumerate(config[key], start=1):
                model, separator, value = item.partition("=")
                model = model.strip()
                location = f"平台 {platform_index} 的 {key} 第 {row} 项"
                if not separator or not model or (model in incomplete and model not in aliases and model not in config["models"]):
                    repairs.append(f"{location} 缺少模型或有效映射，已跳过该覆盖项")
                    continue
                target = model if model in config["models"] else aliases.get(model, model)
                direct = model == target
                if target in overrides and overrides[target] != value:
                    repairs.append(f"{location} 覆盖值冲突，优先真实 ID，同级采用最后一项")
                if direct or not priorities.get(target):
                    overrides[target] = value
                    priorities[target] = direct
            config[key] = [f"{model}={value}" for model, value in overrides.items()]
    return result


def remap_preferences(path: Path, replacements: Dict[str, str]) -> Tuple[Dict[str, Any], str] | None:
    """保留其余偏好原值，只改精确匹配的模型引用并绑定原始文件摘要。"""
    if not path.exists():
        return None
    original = path.read_bytes()
    raw = read_json_file(path)
    SessionPreferenceStore.validate_payload(raw)
    converted = deepcopy(raw)
    for value in converted.values():
        model = value.get("model", "")
        if model in replacements:
            value["model"] = replacements[model]
    if path.read_bytes() != original:
        raise ValueError("会话偏好已在模型标识迁移期间被外部修改，已保留原文件")
    return (converted, sha256(original).hexdigest()) if converted != raw else None


def migrate_model_identifiers(
    store: WorkspaceConfigStore, updated: List[Dict[str, Any]]
) -> None:
    """备份后将平台、设置与会话引用一次提交，写入中断可由同一事务恢复。"""
    candidates: Dict[str, Set[str]] = {}
    enabled_candidates: Dict[str, Set[str]] = {}
    for previous, record in zip(store.providers, updated, strict=True):
        catalog = deepcopy(record)
        catalog["config"]["enabled"] = True
        router = ProviderRouter(store.effective_config({}, [catalog]))
        routes = {}
        if record["kind"] == "openai":
            available = set(record["config"]["models"])
            for entry in previous["config"]["models"]:
                for display, upstream in ProviderRouter._parse_model_routes(entry):
                    if upstream in available:
                        routes.setdefault(display, upstream)
        for model in router.get_all_models():
            routes.setdefault(model, model)
        for model, upstream in routes.items():
            canonical = f"{record['name']}/{upstream}"
            for value in (model, f"{previous['name']} / {model}", f"{previous['name']}/{model}"):
                candidates.setdefault(value, set()).add(canonical)
            if previous["config"]["enabled"]:
                enabled_candidates.setdefault(model, set()).add(canonical)
    for key, values in enabled_candidates.items():
        candidates[key] = values
    replacements = {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}
    settings = deepcopy(store.settings.values)
    general = settings["general"]
    general["default_model"] = replacements.get(general["default_model"], general["default_model"])
    for key in ("fallback_models", "image_edit_unsupported_models", "text_to_image_unsupported_models"):
        general[key] = list(dict.fromkeys(replacements.get(model, model) for model in general[key]))
    preference_path = store.path.parent / "session_preferences.json"
    originals = {store.path: store.path.read_bytes(), store.settings.path: store.settings.path.read_bytes()}
    if preference_path.exists():
        originals[preference_path] = preference_path.read_bytes()
    preferences = remap_preferences(preference_path, replacements)
    if updated == store.providers and settings == store.settings.values and preferences is None:
        return
    backup_dir = store.path.parent / "migration_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path, original in originals.items():
        if path.read_bytes() != original:
            raise ValueError("配置已在模型标识迁移期间被外部修改，已保留原文件")
        backup = backup_dir / f"identifiers-{path.stem}-{uuid4().hex}.json"
        backup.write_bytes(original)
        if backup.read_bytes() != original:
            raise RuntimeError("模型标识迁移备份校验失败，保留原文件")
    store._commit(updated, settings=store._validate_common(settings, settings), preferences=preferences)
    # 启动时会话偏好尚未载入，必须先完成整个事务，不能读取一半旧引用。
    if store.recovery_pending:
        store._recover_transaction()
