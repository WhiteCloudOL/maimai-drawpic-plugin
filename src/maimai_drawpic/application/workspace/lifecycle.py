"""在插件生命周期中组装与释放工作台资源。"""

from pathlib import Path
from typing import Any, List
import asyncio

from ...infrastructure.observability.logging import WorkspaceLogStore
from ...infrastructure.concurrency import run_owned_thread, wait_owned
from .service import WorkspaceService
from .tasks import WorkspaceTaskService
from ...interfaces.chat.message_images import _evict_expired_source_image_cache, clear_source_image_cache
from ..drawing import DrawService
from ...infrastructure.storage.platforms import WorkspaceConfigStore, host_config
from ...infrastructure.storage.results import ImageResultStore


def active_services(plugin: Any) -> List[DrawService]:
    with plugin._service_lifecycle_lock:
        return list(plugin._draw_services)


async def prepare_workspace(plugin: Any, config_path: Path) -> None:
    raw = plugin.get_plugin_config_data()
    store = WorkspaceConfigStore(plugin.ctx.paths.data_dir, config_path)
    recovery_backup = await run_owned_thread(store.initialize, raw)
    if recovery_backup is not None:
        plugin.ctx.logger.warning(
            "已备份并移除已知升级错误生成的 TOML 默认配置，继续使用工作台 JSON；backup=%s", recovery_backup
        )
    plugin._redactor.add(store.secrets())
    plugin._platform_store = store
    plugin._effective_config = await asyncio.to_thread(store.effective_config, raw)
    plugin._result_store = ImageResultStore(
        plugin.ctx.paths.data_dir,
        runtime_dir=plugin.ctx.paths.runtime_dir,
        protected_tasks=lambda: {
            task.get_name().removeprefix("maimai-drawpic:")
            for service in active_services(plugin)
            for task in tuple(service.background_tasks)
        },
    )
    limits = plugin.config.plugin
    await run_owned_thread(plugin._result_store.configure_limits, limits.image_cache_max_mb, limits.upload_cache_max_mb)
    plugin.set_plugin_config(host_config(raw))


async def refresh_runtime(plugin: Any) -> None:
    plugin._redactor.add(plugin._platform_store.secrets())
    plugin._redactor.add_config(plugin.get_plugin_config_data())
    plugin._effective_config = await asyncio.to_thread(
        plugin._platform_store.effective_config, plugin.get_plugin_config_data()
    )
    limits = plugin.config.plugin
    await asyncio.to_thread(
        plugin._result_store.configure_limits, limits.image_cache_max_mb, limits.upload_cache_max_mb
    )
    if plugin._workspace_service is not None:
        workspace = plugin._workspace_service
        await asyncio.to_thread(workspace.logs.configure_limit, limits.log_max_mb)
        protected = {
            task.get_name().removeprefix("maimai-drawpic:")
            for service in active_services(plugin)
            for task in tuple(service.background_tasks)
        }
        async with workspace.tasks.lock:
            await asyncio.to_thread(workspace.tasks.cleanup_storage, protected)
    await asyncio.to_thread(plugin._refresh_services)


async def attach_workspace(plugin: Any) -> None:
    async def apply_settings(values):
        del values
        await refresh_runtime(plugin)

    def secrets():
        values = plugin._platform_store.secrets()
        if plugin.config.proxy.password:
            values.append(plugin.config.proxy.password)
        return values

    pending_log_store = asyncio.create_task(asyncio.to_thread(
        WorkspaceLogStore, plugin.ctx.paths.data_dir, plugin.ctx.logger, secrets, plugin.config.plugin.log_max_mb
    ))
    try:
        log_store = await asyncio.shield(pending_log_store)
    except asyncio.CancelledError:
        log_store = await wait_owned(pending_log_store)
        await run_owned_thread(log_store.close)
        raise
    tasks = WorkspaceTaskService(
        ctx=plugin.ctx,
        data_dir=plugin.ctx.paths.data_dir,
        task_store=plugin._task_store,
        results=plugin._result_store,
        get_config=lambda: plugin.config,
        get_service=plugin._require_draw_service,
        submit_chat=plugin._start_background_image_request,
        active_services=lambda: active_services(plugin),
    )
    try:
        await run_owned_thread(tasks.initialize)
    except BaseException:
        await run_owned_thread(log_store.close)
        raise
    plugin._workspace_service = WorkspaceService(
        ctx=plugin.ctx,
        store=plugin._platform_store,
        tasks=tasks,
        logs=log_store,
        get_config=lambda: plugin.config,
        apply_settings=apply_settings,
        refresh=lambda: refresh_runtime(plugin),
    )

    store = plugin._platform_store
    for repair in store.identifier_repairs:
        plugin.ctx.logger.warning("已自动修复旧模型配置：%s。原配置备份位于 %s", repair, store.path.parent / "migration_backups")
    plugin._workspace_cleanup_task = asyncio.create_task(maintain_workspace(plugin), name="drawpic-storage-cleanup")


async def maintain_workspace(plugin: Any) -> None:
    while True:
        await asyncio.sleep(600)
        _evict_expired_source_image_cache()
        workspace = plugin._workspace_service
        if workspace is None:
            return
        protected = {
            task.get_name().removeprefix("maimai-drawpic:")
            for service in active_services(plugin)
            for task in service.background_tasks
        }
        try:
            async with workspace.tasks.lock:
                counts = await asyncio.to_thread(workspace.tasks.cleanup_storage, protected)
            if any(counts.values()):
                plugin.ctx.logger.debug("已清理过期运行产物: inputs=%s results=%s", counts["inputs"], counts["results"])
        except (OSError, ValueError):
            plugin.ctx.logger.exception("清理运行产物失败")


async def close_workspace(plugin: Any) -> None:
    # Finish an already committed configuration refresh before taking the final
    # service snapshot; it may retire/create a drawing service.
    if plugin._workspace_service is not None:
        await plugin._workspace_service.close()
    # Stop new admissions before awaiting any shutdown work.
    with plugin._service_lifecycle_lock:
        plugin._closing = True
        services = list(plugin._draw_services)
        for service in services:
            service.close_admission()
    clear_source_image_cache()
    if plugin._workspace_cleanup_task is not None:
        plugin._workspace_cleanup_task.cancel()
        await asyncio.gather(plugin._workspace_cleanup_task, return_exceptions=True)
        plugin._workspace_cleanup_task = None
    for service in services:
        await service.cancel_submissions()
        await service.cancel_background_tasks()
    # Flush known terminal outcomes before releasing diagnostics. Unlike a
    # read-only query retry, unload must report a persistent storage failure.
    if any(record["persistence_pending"] for record in plugin._task_store.snapshot()):
        await asyncio.to_thread(plugin._task_store.save)
    if plugin._workspace_service is not None:
        await asyncio.to_thread(plugin._workspace_service.logs.close)
        plugin._workspace_service = None
