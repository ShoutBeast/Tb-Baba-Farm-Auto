"""
测试用例：验证媒体音量静音是否真正生效

背景：
    settings put system volume_music 0 在 Android 8+ 上大多无效（不作用于实际音频流），
    因此 utils.py 提供多策略静音：cmd media_session（Android 10+）→ media volume（旧）→ settings。

测试内容：
    1. test_mute_media_volume   - 调用 utils.mute_media_volume 后，dumpsys audio 中媒体流(stream 3)音量为 0
    2. test_restore_media_volume - 调用 utils.set_media_volume 恢复原音量，验证读回一致

运行方式:
    python test/test_volume_mute.py
    python -m unittest test.test_volume_mute -v

注意:
    - 测试结束会自动恢复静音前的音量，不影响手机正常使用
    - 需要已连接手机（与 淘宝芭芭农场.py 相同环境）
"""

import os
import sys
import time
import unittest

# 允许从项目根目录导入 utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，中文 print 可能报错，统一用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uiautomator2 as u2
from utils import get_media_volume, set_media_volume, mute_media_volume, select_device


class TestMediaVolumeMute(unittest.TestCase):
    """验证媒体音量静音是否真正生效"""

    @classmethod
    def setUpClass(cls):
        print("连接设备...")
        cls.d = u2.connect(select_device())
        cls.original_volume = get_media_volume(cls.d)
        print(f"静音前媒体音量(stream 3): {cls.original_volume}")
        if cls.original_volume is None:
            raise unittest.SkipTest("无法读取当前媒体音量，请确认设备已连接且 adb 可用")

    def test_mute_media_volume(self):
        """静音后，dumpsys audio 中媒体流(stream 3)音量应为 0"""
        ok = mute_media_volume(self.d)
        now = get_media_volume(self.d)
        print(f"静音后媒体音量(stream 3): {now}")
        self.assertTrue(ok, "静音函数报告失败：所有设置通道均未生效")
        self.assertEqual(
            now, 0,
            f"媒体流未真正静音！当前音量: {now}（静音前: {self.original_volume}）"
        )

    def test_restore_media_volume(self):
        """恢复音量后，dumpsys audio 中媒体流(stream 3)音量应回到原值"""
        ok = set_media_volume(self.d, self.original_volume)
        now = get_media_volume(self.d)
        print(f"恢复后媒体音量(stream 3): {now}（目标: {self.original_volume}）")
        self.assertTrue(ok, "恢复音量函数报告失败：所有设置通道均未生效")
        self.assertEqual(
            now, self.original_volume,
            f"恢复失败！当前: {now}，目标: {self.original_volume}"
        )

    @classmethod
    def tearDownClass(cls):
        """兜底恢复静音前的音量，避免测试异常退出后手机保持静音"""
        if cls.original_volume is not None:
            set_media_volume(cls.d, cls.original_volume)
            time.sleep(0.3)
            final = get_media_volume(cls.d)
            print(f"最终恢复确认: {final}（原值 {cls.original_volume}）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
