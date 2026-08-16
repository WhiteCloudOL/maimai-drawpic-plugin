"""验证插件所有模块可在包上下文中完整导入。"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_PKG_NAME = "maimai_drawpic_pkg"

pkg = types.ModuleType(_PKG_NAME)
pkg.__path__ = [str(_PLUGIN_DIR)]
sys.modules[_PKG_NAME] = pkg

for sub in ("core", "providers"):
    sub_path = _PLUGIN_DIR / sub
    init_file = sub_path / "__init__.py"
    full = f"{_PKG_NAME}.{sub}"
    if init_file.exists():
        spec = importlib.util.spec_from_file_location(
            full, init_file, submodule_search_locations=[str(sub_path)]
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
    else:
        ns = types.ModuleType(full)
        ns.__path__ = [str(sub_path)]
        sys.modules[full] = ns

# 尝试导入所有核心模块
modules_to_check = [
    "core.image_utils",
    "core.task_store",
    "core.usage_store",
    "core.provider_options",
    "core.texts",
    "core.session_preferences",
    "core.moderation",
    "core.message_utils",
    "core.stream_service",
    "core.provider_router",
    "core.draw_service",
    "core.config",
    "providers.aliyun_platform",
    "providers.google_platform",
    "providers.novelai_platform",
    "providers.openai_platform",
    "providers.siliconflow_platform",
    "providers.volcengine_platform",
    "providers.zhipu_platform",
]

failed = []
for mod_name in modules_to_check:
    full_name = f"{_PKG_NAME}.{mod_name}"
    try:
        importlib.import_module(full_name)
        print(f"[OK] {mod_name}")
    except Exception as exc:
        print(f"[FAIL] {mod_name}: {exc}")
        failed.append(mod_name)

if failed:
    print(f"\n[FAILED] {len(failed)} module(s) failed to import")
    sys.exit(1)
else:
    print(f"\n[ALL OK] {len(modules_to_check)} modules imported successfully")
