"""commands/quota.py 的插件组件。"""

import asyncio

from ..interfaces.chat.texts import build_quota_adjust_text
from ..infrastructure.storage.quotas import QuotaPeriod, QuotaReservation

class QuotaMixin:
    """commands/quota.py 对应的插件行为。"""

    @staticmethod
    def _is_group_chat(group_id: str) -> bool:
        """判断当前会话是否为群聊（用于额度配置选择）。"""

        return bool(group_id.strip())

    def _resolve_quota_config(self, group_id: str) -> tuple[bool, QuotaPeriod, int]:
        """按群聊/私聊选择额度配置，返回 (enabled, period, default_quota)。"""

        general = self.config.general
        if self._is_group_chat(group_id):
            return (
                general.group_quota_enabled,
                general.group_quota_period,
                general.group_default_quota,
            )
        return (
            general.private_quota_enabled,
            general.private_quota_period,
            general.private_default_quota,
        )

    @staticmethod
    def _build_quota_key(platform: str, group_id: str, user_id: str) -> str:
        """按平台和聊天类型构建额度归属键。"""

        normalized_platform = platform.strip() or "qq"
        normalized_group_id = group_id.strip()
        normalized_user_id = user_id.strip()
        if normalized_group_id:
            return f"{normalized_platform}:group:{normalized_group_id}"
        return f"{normalized_platform}:user:{normalized_user_id}"

    @staticmethod
    def _build_quota_key_for_target(platform: str, chat_type: str, target_id: str) -> str:
        """按管理员命令参数构建额度归属键。chat_type: group / private。"""

        normalized_platform = platform.strip() or "qq"
        normalized_target_id = target_id.strip()
        if chat_type == "group":
            return f"{normalized_platform}:group:{normalized_target_id}"
        return f"{normalized_platform}:user:{normalized_target_id}"

    def _quota_status_text(self, user_id: str, group_id: str, stream_id: str) -> str:
        """构建用户额度状态文本。"""

        quota_enabled, quota_period, default_quota = self._resolve_quota_config(group_id)
        if not quota_enabled:
            self.ctx.logger.debug(
                "绘图额度状态: quota_enabled=false stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return "未启用次数管理"
        if self._is_admin(user_id):
            self.ctx.logger.debug(
                "绘图额度状态: admin_user=true stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return "管理员不受次数限制"
        is_group = self._is_group_chat(group_id)
        if is_group:
            quota_key = self._build_quota_key(self._resolve_quota_platform(group_id), group_id, "")
        elif user_id.strip():
            quota_key = self._build_quota_key(self._resolve_quota_platform(group_id), "", user_id)
        else:
            self.ctx.logger.warning(
                "绘图额度状态失败: 无法识别归属 user_id=%s group_id=%s stream_id=%s",
                user_id,
                group_id,
                stream_id,
            )
            return "无法识别聊天归属，不能查询绘图次数"
        remaining = self._usage_store.get_remaining(
            quota_key,
            period=quota_period,
            default_quota=default_quota,
        )
        scope_label = "群聊" if self._is_group_chat(group_id) else "用户"
        scope_value = group_id.strip() or user_id.strip()
        self.ctx.logger.debug(
            "绘图额度状态: quota_key=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
            quota_key,
            remaining,
            quota_period,
            default_quota,
            stream_id,
            user_id,
            group_id,
        )
        return f"{scope_label} {scope_value} 当前周期剩余 {remaining} 次（周期：{quota_period}）"

    def _resolve_quota_platform(self, group_id: str) -> str:
        """额度键使用的平台标识，当前固定为 qq。"""

        del group_id
        return "qq"

    def _check_draw_quota(self, user_id: str, group_id: str, stream_id: str) -> tuple[bool, str, str]:
        """检查绘图额度是否足够，但不实际扣除。返回是否可用、提示文本和额度键。"""

        quota_enabled, quota_period, default_quota = self._resolve_quota_config(group_id)
        if not quota_enabled:
            self.ctx.logger.debug(
                "跳过绘图额度检查: quota_enabled=false stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return True, "未启用次数管理", ""
        if self._is_admin(user_id):
            self.ctx.logger.debug(
                "跳过绘图额度检查: admin_user=true stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return True, "管理员不受次数限制", ""
        is_group = self._is_group_chat(group_id)
        if is_group:
            quota_key = self._build_quota_key(self._resolve_quota_platform(group_id), group_id, "")
        elif user_id.strip():
            quota_key = self._build_quota_key(self._resolve_quota_platform(group_id), "", user_id)
        else:
            self.ctx.logger.warning(
                "绘图额度检查失败: 无法识别归属 user_id=%s group_id=%s stream_id=%s",
                user_id,
                group_id,
                stream_id,
            )
            return False, "无法识别聊天归属，不能使用绘图次数", ""
        remaining = self._usage_store.get_remaining(
            quota_key,
            period=quota_period,
            default_quota=default_quota,
        )
        scope_label = "群聊" if is_group else "用户"
        scope_value = group_id.strip() or user_id.strip()
        if remaining <= 0:
            self.ctx.logger.debug(
                "绘图额度不足: quota_key=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
                quota_key,
                remaining,
                quota_period,
                default_quota,
                stream_id,
                user_id,
                group_id,
            )
            return (
                False,
                f"{scope_label} {scope_value} 的绘图次数已用尽（周期：{quota_period}）",
                "",
            )
        self.ctx.logger.debug(
            "绘图额度检查通过: quota_key=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
            quota_key,
            remaining,
            quota_period,
            default_quota,
            stream_id,
            user_id,
            group_id,
        )
        return True, f"{scope_label} {scope_value} 当前周期剩余 {remaining} 次", quota_key

    def _reserve_draw_quota(
        self,
        user_id: str,
        group_id: str,
        stream_id: str,
        *,
        return_reservation: bool = False,
    ) -> tuple[bool, str, str | QuotaReservation | None]:
        """原子预留额度；任务提交使用凭据，保留旧额度键返回方式。"""

        allowed, message, quota_key = self._check_draw_quota(user_id, group_id, stream_id)
        if not allowed or not quota_key:
            return allowed, message, None if return_reservation else quota_key
        quota_enabled, quota_period, default_quota = self._resolve_quota_config(group_id)
        if not quota_enabled:
            return True, message, None if return_reservation else ""
        reservation = None
        if return_reservation:
            reservation, remaining = self._usage_store.reserve(
                quota_key,
                period=quota_period,
                default_quota=default_quota,
            )
            success = reservation is not None
        else:
            success, remaining = self._usage_store.consume(
                quota_key,
                period=quota_period,
                default_quota=default_quota,
            )
        if not success:
            self.ctx.logger.debug(
                "绘图额度预留失败: quota_key=%s remaining=%s period=%s stream_id=%s group_id=%s",
                quota_key,
                remaining,
                quota_period,
                stream_id,
                group_id,
            )
            return False, "绘图次数已用尽", None if return_reservation else ""
        self.ctx.logger.debug(
            "绘图额度已预留: quota_key=%s remaining=%s period=%s stream_id=%s group_id=%s",
            quota_key,
            remaining,
            quota_period,
            stream_id,
            group_id,
        )
        return True, message, reservation if return_reservation else quota_key

    def _commit_draw_quota(self, reservation: QuotaReservation | None) -> None:
        """结束成功任务的额度预留，保留消费并清除可退款凭据。"""

        if reservation is not None:
            self._usage_store.commit_reservation(reservation)

    def _refund_draw_quota(
        self,
        quota_key: str,
        group_id: str,
        stream_id: str,
        task_id: str = "",
        *,
        quota_period: QuotaPeriod | None = None,
        default_quota: int | None = None,
        reservation: QuotaReservation | None = None,
    ) -> None:
        """退回失败任务预留的绘图额度。"""

        normalized_quota_key = quota_key.strip()
        if not normalized_quota_key:
            return
        if reservation is not None:
            if reservation.quota_key != normalized_quota_key:
                raise ValueError("额度凭据与退款归属不一致")
            quota_period = reservation.period
            remaining = self._usage_store.refund_reservation(reservation)
        else:
            if quota_period is None or default_quota is None:
                quota_enabled, quota_period, default_quota = self._resolve_quota_config(group_id)
                if not quota_enabled:
                    return
            remaining = self._usage_store.refund(
                normalized_quota_key,
                period=quota_period,
                default_quota=default_quota,
            )
        self.ctx.logger.debug(
            "绘图额度已退回: quota_key=%s remaining=%s period=%s stream_id=%s group_id=%s task_id=%s",
            normalized_quota_key,
            remaining,
            quota_period,
            stream_id,
            group_id,
            task_id,
        )

    @staticmethod
    def _normalize_scope_name(scope_name: str) -> str:
        """归一化管理员命令中的范围词：群聊/用户 → group/private。"""

        scope_map = {
            "群聊": "group",
            "群": "group",
            "group": "group",
            "用户": "private",
            "私聊": "private",
            "user": "private",
            "private": "private",
        }
        return scope_map.get(scope_name.strip(), "")

    async def _handle_times_command(
        self,
        *,
        rest_payload: str,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[bool, str, int]:
        """处理绘图次数调整命令。

        命令格式：/绘图 设置/添加/减少 群聊/用户 群ID/用户ID 数量
        例如：/绘图 设置 用户 12345678 10
        """

        if not self._can_manage_session(user_id):
            await self._send_command_reply(
                title="权限不足",
                body="当前已启用权限管理。\n只有插件管理员可以调整绘图次数。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "权限不足", 1

        action_word, action_rest = self._split_command_payload(rest_payload)
        action = self._normalize_command_name(action_word)
        if action not in {"add", "remove", "set"}:
            await self._send_command_reply(
                title="次数命令用法",
                body=("/绘图 设置/添加/减少 群聊/用户 群ID/用户ID 数量\n例如：/绘图 设置 用户 12345678 10"),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "次数命令参数不足", 1

        scope_word, scope_rest = self._split_command_payload(action_rest)
        scope = self._normalize_scope_name(scope_word)
        if scope not in {"group", "private"}:
            await self._send_command_reply(
                title="次数命令用法",
                body=(
                    "请指定调整范围：群聊 或 用户。\n"
                    "格式：/绘图 设置/添加/减少 群聊/用户 群ID/用户ID 数量\n"
                    "例如：/绘图 设置 群聊 673381211 50"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "次数命令参数不足", 1

        target_id, count_text = self._split_command_payload(scope_rest)
        try:
            count = int(count_text.strip())
        except ValueError:
            count = -1
        if not target_id or count < 0 or (action in {"add", "remove"} and count == 0):
            await self._send_command_reply(
                title="次数命令参数无效",
                body=(
                    "请提供有效的群ID/用户ID和次数。\n"
                    "添加/减少需要正整数，设置可设置为 0。\n"
                    "例如：/绘图 设置 用户 12345678 10"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "次数命令参数无效", 1

        quota_key = self._build_quota_key_for_target(platform, scope, target_id)
        # 按目标范围选择对应的额度配置（周期与默认额度）
        if scope == "group":
            quota_period = self.config.general.group_quota_period
            default_quota = self.config.general.group_default_quota
        else:
            quota_period = self.config.general.private_quota_period
            default_quota = self.config.general.private_default_quota
        remaining = await asyncio.to_thread(
            self._usage_store.adjust_remaining,
            quota_key,
            action=action,  # type: ignore[arg-type]
            count=count,
            period=quota_period,
            default_quota=default_quota,
        )
        scope_label = "群聊" if scope == "group" else "用户"
        self.ctx.logger.info(
            "绘图额度已调整: action=%s scope=%s target_id=%s quota_key=%s count=%s remaining=%s operator_user_id=%s stream_id=%s group_id=%s period=%s default_quota=%s",
            action,
            scope,
            target_id,
            quota_key,
            count,
            remaining,
            user_id,
            stream_id,
            group_id,
            quota_period,
            default_quota,
        )
        action_label_map = {
            "add": "添加",
            "remove": "减少",
            "set": "设置",
        }
        await self._send_command_reply(
            title="次数已更新",
            body=build_quota_adjust_text(action_label_map[action], scope_label, target_id, remaining),
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        return True, "已调整绘图次数", 2
