# 導入標準庫
import json
import logging
import tempfile
from datetime import datetime, time

# 導入 AstrBot 核心庫
import os
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent

# 嘗試導入圖片生成模組
try:
    from .image_generator import generate_image_with_text
    IMAGE_GENERATOR_AVAILABLE = True
except ImportError:
    IMAGE_GENERATOR_AVAILABLE = False
    generate_image_with_text = None
    logger.warning("【通用指令插件】圖片生成模組 'image_generator.py' 未找到或依賴不完整，圖片指令功能將被禁用。")

# 輔助類，用於安全地格式化字串。如果範本中的鍵不存在，則返回鍵本身，方便使用者偵錯。
class SafeDict(dict):
    def __missing__(self, key):
        return f'{{{key}}}'

@register(
    "astrbot_plugin_freecmd",
    "Magstic, Gemini 2.5 Pro",
    "提供高度可自訂的、包含動態時間與靜態文本的指令系統。",
    "1.0.0"
)
class UniversalCommandPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.static_commands = {}
        self.time_commands = []
        self._load_config(config)

    def _load_config(self, config: dict):
        """解析 JSON 設定，載入所有靜態與動態指令。"""
        config_json = config.get("command_config", "{}")
        try:
            full_config = json.loads(config_json)

            # 載入靜態指令
            static_list = full_config.get("static_commands", [])
            for cmd_data in static_list:
                name = cmd_data.get("name", "").strip()
                reply = cmd_data.get("reply")
                if name and reply is not None:
                    # 將完整的指令設定儲存起來，而不僅僅是回覆文本
                    self.static_commands[f"/{name}"] = cmd_data
            logger.info(f"【通用指令插件】成功載入 {len(self.static_commands)} 個靜態指令。")

            # 載入時間動態指令
            time_list = full_config.get("time_commands", [])
            for time_cmd_config in time_list:
                # 對時間段進行預處理
                for period in time_cmd_config.get("time_periods", []):
                    period['start_time_obj'] = datetime.strptime(period['start_time'], '%H:%M').time()
                    period['end_time_obj'] = datetime.strptime(period['end_time'], '%H:%M').time()
                self.time_commands.append(time_cmd_config)
            logger.info(f"【通用指令插件】成功載入 {len(self.time_commands)} 個時間動態指令。")

        except json.JSONDecodeError:
            logger.error("【通用指令插件】解析指令設定 JSON 失敗。")
        except Exception as e:
            logger.error(f"【通用指令插件】載入指令設定時發生未知錯誤: {e}", exc_info=True)

    def _get_current_period_info(self, time_cmd_config: dict):
        """根據當前時間取得對應的時間段資訊。"""
        now_time = datetime.now().time()
        for period in time_cmd_config.get("time_periods", []):
            start = period['start_time_obj']
            end = period['end_time_obj']
            if start <= end:
                if start <= now_time < end:
                    return period
            else:  # 跨天
                if now_time >= start or now_time < end:
                    return period
        return None

    def _format_reply(self, time_cmd_config: dict, period_info: dict) -> str:
        """使用範本與時間段資訊格式化回覆文本。"""
        reply_format = time_cmd_config.get("reply_format")
        if not reply_format:
            return f"錯誤：指令 '{time_cmd_config.get('command_name')}' 的設定中缺少 'reply_format' 欄位。"

        safe_info = SafeDict(period_info)
        return reply_format.format_map(safe_info)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def handle_commands(self, event: AstrMessageEvent):
        """統一處理所有靜態與動態指令。"""
        content = event.message_obj.message_str.strip()
        if not content:
            return

        # 優先匹配靜態指令
        # 優先匹配靜態指令
        for command, cmd_data in self.static_commands.items():
            if content.startswith(command):
                reply_text = cmd_data.get("reply")
                image_options = cmd_data.get("image_options")

                if image_options and IMAGE_GENERATOR_AVAILABLE:
                    image_buffer, image_format = generate_image_with_text(reply_text, image_options)
                    temp_image_path = None
                    if image_buffer is not None:
                        try:
                            # 創建帶有正確擴展名的臨時檔案
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{image_format}") as temp_file:
                                temp_file.write(image_buffer.tobytes())
                                temp_image_path = temp_file.name
                            
                            yield event.image_result(temp_image_path).stop_event()
                        finally:
                            # 無論成功或失敗，都嘗試刪除臨時檔案
                            if temp_image_path and os.path.exists(temp_image_path):
                                os.remove(temp_image_path)
                    else:
                        yield event.plain_result(f"'{command}'…？（歪頭）").stop_event()
                else:
                    yield event.plain_result(reply_text).stop_event()
                return

        # 匹配動態時間指令
        for time_cmd in self.time_commands:
            command_name = time_cmd.get("command_name", "")
            trigger_command = f"/{command_name}"
            if content.startswith(trigger_command):
                period_info = self._get_current_period_info(time_cmd)
                image_options = time_cmd.get("image_options")

                if period_info:
                    reply_text = self._format_reply(time_cmd, period_info)
                    if image_options and IMAGE_GENERATOR_AVAILABLE:
                        image_buffer, image_format = generate_image_with_text(reply_text, image_options)
                        temp_image_path = None
                        if image_buffer is not None:
                            try:
                                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{image_format}") as temp_file:
                                    temp_file.write(image_buffer.tobytes())
                                    temp_image_path = temp_file.name
                                
                                yield event.image_result(temp_image_path).stop_event()
                            finally:
                                if temp_image_path and os.path.exists(temp_image_path):
                                    os.remove(temp_image_path)
                        else:
                            yield event.plain_result(f"'{command_name}'…？（歪頭）").stop_event()
                    else:
                        yield event.plain_result(reply_text).stop_event()
                else:
                    fallback_reply = time_cmd.get("fallback_reply", "沒事做喔。")
                    yield event.plain_result(fallback_reply).stop_event()
                return

