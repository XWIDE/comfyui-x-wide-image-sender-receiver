"""
X-WIDE Image Sender / X-WIDE Image Receiver
===========================================

原节点 Image Sender / Image Receiver 由 **ltdrdata (Dr.Lt.Data)** 在
ComfyUI-Impact-Pack 中开发（GPL-3.0）。本包把它们独立封装成中英双语的
X-WIDE 版本，**不依赖 Impact Pack**，并且只做了两类改动：

1. 界面：控件名 / 提示中英双语，节点归到 X-WIDE 分类，附带「信息 / About」署名页。
2. 修复：见 CHANGELOG.md —— 主要是「切换工作流后收到的图失效」与
   「勾选保存到工作流时内联 base64 撑爆 localStorage 草稿配额 / 造成画布卡顿」。

因此凡是与收发协议有关的部分（节点类型、控件顺序、`img-send` 事件、图像编码）
都与原版保持一致：两个包的节点可以同画布共存、互相配对，老工作流也能迁移。
"""

import base64
import logging
import os
import sys
from io import BytesIO

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths
import nodes as comfy_nodes
from server import PromptServer

LOG_PREFIX = "[X-WIDE Image Sender/Receiver]"

# 接收端在拿不到图像时回退用的空图尺寸（与原版一致，避免下游节点因尺寸突变报错）
EMPTY_SIZE = 64


def empty_image(size=EMPTY_SIZE):
    """返回一张全黑的占位图 + 全零遮罩，形状与 LoadImage 一致（带 batch 维）。"""
    image = torch.zeros((1, size, size, 3), dtype=torch.float32)
    mask = torch.zeros((1, size, size), dtype=torch.float32)
    return image, mask


def load_image_from_path(image):
    """
    按 LoadImage 的方式读取一个文件（支持 `name.png [temp]` 这种 annotated 路径）。

    这是本包对原版的关键修复之一：勾选「保存到工作流」后，工作流里不再内联
    base64（否则草稿会撑爆 localStorage），重新打开工作流时 image_data 是空的，
    此时必须回退到 image 控件里记录的图片文件，而不是静默返回一张 64×64 黑图。
    """
    try:
        if image and image != "#DATA" and folder_paths.exists_annotated_filepath(image):
            return comfy_nodes.LoadImage().load_image(image)
    except Exception as error:  # noqa: BLE001 - 回退失败也必须继续往下走
        logging.warning("%s load image failed: %s (%s)", LOG_PREFIX, image, error)
    return empty_image()


class XWIDE_ImageReceiver:
    """X-WIDE Image Receiver —— 接收 X-WIDE Image Sender（或原版 Image Sender）发来的图。"""

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        try:
            files = [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f))
            ]
        except FileNotFoundError:
            files = []

        return {
            "required": {
                "image": (
                    sorted(files),
                    {
                        "tooltip": "要读取的图片。收到 Sender 发来的图后，这里会自动填入临时文件。 / "
                        "Image to load. Filled automatically with the received temp file."
                    },
                ),
                "link_id": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": sys.maxsize,
                        "step": 1,
                        "tooltip": "配对编号：和 Image Sender 的 link_id 相同才会收到它的图。 / "
                        "Pairing id: only the Sender with the same link_id will send to this node.",
                    },
                ),
                "save_to_workflow": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "勾选后，收到的图会在排队时作为图像数据随提示一起发送（工作流文件本身不会内联 base64，"
                        "所以不会撑爆草稿存储，也不会让画布变卡）。 / "
                        "When enabled, the received image is injected into the queued prompt. "
                        "The image data is NOT inlined into the workflow file itself.",
                    },
                ),
                "image_data": (
                    "STRING",
                    {
                        "multiline": False,
                        "tooltip": "图像数据（由前端在排队时按需生成，平时为空）。 / "
                        "Image data, generated on demand by the frontend when the prompt is queued. "
                        "Kept empty in the saved workflow on purpose.",
                    },
                ),
                "trigger_always": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "enable",
                        "label_off": "disable",
                        "tooltip": "开启后本节点每次都重新执行（忽略缓存）。 / "
                        "When enabled the node always re-executes, ignoring the cache.",
                    },
                ),
            }
        }

    FUNCTION = "doit"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")

    CATEGORY = "X-WIDE/Image"

    DESCRIPTION = (
        "接收 Image Sender（X-WIDE 版或 Impact Pack 原版）传过来的图片，输出 IMAGE / MASK。"
        " / Receives the image sent by Image Sender (X-WIDE or the original Impact Pack node)."
    )

    SEARCH_ALIASES = [
        "X-WIDE",
        "X-WIED",
        "xwide",
        "x wide",
        "image receiver",
        "receiver",
        "image sender receiver",
        "图像接收",
        "接收",
        "接收器",
        "图像",
    ]

    def doit(self, image, link_id, save_to_workflow, image_data, trigger_always):
        if save_to_workflow:
            data = image_data if isinstance(image_data, str) else ""
            if data.startswith("data:image") or "base64," in data[:64]:
                try:
                    raw = base64.b64decode(data.split(",", 1)[1])
                    pil_image = Image.open(BytesIO(raw))
                    pil_image = ImageOps.exif_transpose(pil_image)
                    array = np.array(pil_image.convert("RGB")).astype(np.float32) / 255.0
                    out_image = torch.from_numpy(array)[None,]

                    if "A" in pil_image.getbands():
                        alpha = np.array(pil_image.getchannel("A")).astype(np.float32) / 255.0
                        mask = 1.0 - torch.from_numpy(alpha)
                    else:
                        mask = torch.zeros((EMPTY_SIZE, EMPTY_SIZE), dtype=torch.float32)

                    return out_image, mask.unsqueeze(0)
                except Exception as error:  # noqa: BLE001 - 解码失败要走回退，不能打断工作流
                    logging.warning(
                        "%s ImageReceiver - invalid 'image_data' (%s); falling back to the image file",
                        LOG_PREFIX,
                        error,
                    )
            return load_image_from_path(image)

        # 本包对原版的另一处修复：原版这里直接调 LoadImage().load_image()，
        # 图不在了（例如重启后 temp 被清空）会抛异常、让整个节点报红。
        # 改成走同一个带回退的读取函数：能读就读，读不到就警告 + 占位图。
        return load_image_from_path(image)

    @classmethod
    def VALIDATE_INPUTS(cls, image, link_id, save_to_workflow, image_data, trigger_always):
        # '#DATA' 是 Impact Pack 原版在"保存到工作流"模式下写进提示里的占位符，
        # 迁移过来的工作流仍然带它，这里要放行。
        if image == "#DATA":
            return True

        if not isinstance(image, str) or image.startswith("/") or ".." in image:
            return "Invalid image file: {}".format(image)

        if save_to_workflow:
            # 勾选保存时，路径可能指向已经被清理的临时文件（ComfyUI 重启后 temp 会清空）。
            # 这时放行、由 doit 回退成占位图，比在排队阶段直接报错友好得多。
            return True

        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)

        return True

    @classmethod
    def IS_CHANGED(cls, image, link_id, save_to_workflow, image_data, trigger_always):
        if trigger_always:
            return float("NaN")

        if save_to_workflow:
            return hash(image_data)

        return hash(image)


class XWIDE_ImageSender(comfy_nodes.PreviewImage):
    """X-WIDE Image Sender —— 把图发给同 link_id 的 Image Receiver，并在节点上显示预览。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "IMAGE",
                    {
                        "tooltip": "要发送的图像。 / Images to send."
                    },
                ),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "ImgSender",
                        "tooltip": "保存到临时目录时用的文件名前缀。 / Filename prefix used in the temp folder.",
                    },
                ),
                "link_id": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": sys.maxsize,
                        "step": 1,
                        "tooltip": "配对编号：和 Image Receiver 的 link_id 相同才会发过去。 / "
                        "Pairing id: only the Receiver with the same link_id receives this image.",
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    OUTPUT_NODE = True
    FUNCTION = "doit"

    CATEGORY = "X-WIDE/Image"

    DESCRIPTION = (
        "把图像保存到临时目录并通过 img-send 事件发给同 link_id 的 Image Receiver；"
        "节点上会直接显示预览。 / Saves the image to the temp folder and sends it to the Image Receiver "
        "with the same link_id via the img-send event; the preview is shown on the node."
    )

    SEARCH_ALIASES = [
        "X-WIDE",
        "X-WIED",
        "xwide",
        "x wide",
        "image sender",
        "sender",
        "image sender receiver",
        "图像发送",
        "发送",
        "发送器",
        "图像",
    ]

    def doit(self, images, filename_prefix="ImgSender", link_id=0, prompt=None, extra_pnginfo=None):
        result = comfy_nodes.PreviewImage().save_images(
            images, filename_prefix, prompt, extra_pnginfo
        )
        PromptServer.instance.send_sync(
            "img-send", {"link_id": link_id, "images": result["ui"]["images"]}
        )
        return result


NODE_CLASS_MAPPINGS = {
    "XWIDE_ImageSender": XWIDE_ImageSender,
    "XWIDE_ImageReceiver": XWIDE_ImageReceiver,
}

# 显示名里带 X-WIDE：节点搜索框里输入 xwide / x-wide / X-WIDE / image sender 都能搜到
# （ComfyUI 的搜索会匹配显示名、分类与 SEARCH_ALIASES）。
NODE_DISPLAY_NAME_MAPPINGS = {
    "XWIDE_ImageSender": "X-WIDE Image Sender 图像发送器",
    "XWIDE_ImageReceiver": "X-WIDE Image Receiver 图像接收器",
}
