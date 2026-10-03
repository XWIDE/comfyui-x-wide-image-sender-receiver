"""
X-WIDE Image Sender / Receiver
==============================

原节点 Image Sender / Image Receiver 由 ltdrdata (Dr.Lt.Data) 在
ComfyUI-Impact-Pack 中开发（GPL-3.0）。本包是**独立**的中英双语版本，
不依赖 Impact Pack，仅优化界面显示并修复原节点的若干问题：

- 切换工作流再切回来，收到的图不再失效
- 勾选「保存到工作流」不再把内联 base64 写进草稿、撑爆 localStorage 配额
- 大图不再因为控件值里塞了几 MB 的 base64 而让画布卡顿

详见 NOTICE 与 CHANGELOG.md。
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

__version__ = "1.0.0"
