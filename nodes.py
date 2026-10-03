"""
X-WIDE Image Sender / Receiver  +  X-WIDE Latent Sender / Receiver
=================================================================

原节点 Image Sender / Image Receiver / Latent Sender / Latent Receiver 由
**ltdrdata (Dr.Lt.Data)** 在 ComfyUI-Impact-Pack 中开发（GPL-3.0）。本包把它们
独立封装成中英双语的 X-WIDE 版本，**不依赖 Impact Pack**，并且只做了两类改动：

1. 界面：控件名 / 提示中英双语，节点归到 X-WIDE 分类，附带「信息 / About」署名页。
2. 修复：见 CHANGELOG.md —— 主要是「切换工作流后收到的图失效」「勾选保存到工作流时
   内联 base64 撑爆 localStorage 草稿配额 / 造成画布卡顿」，以及文件已经不存在时
   优雅回退成占位内容（原版会直接让节点报红）。

因此凡是与收发协议有关的部分（节点类型、控件顺序、`img-send` / `latent-send`
事件、图像编码、`.latent` / `.latent.png` 文件格式）都与原版保持一致：两个包的
节点可以同画布共存、互相配对，老工作流也能迁移。
"""

import base64
import hashlib
import json
import logging
import os
import re
import sys
import zipfile
from io import BytesIO

import numpy as np
import torch
from PIL import Image, ImageOps, PngImagePlugin

import folder_paths
import nodes as comfy_nodes
from server import PromptServer

try:
    # 只有「预览 PNG 里内嵌 latent」这条路径需要 piexif（装了 Impact Pack 的环境已有）。
    # 缺了它不会报错：发送端自动改成写纯 .latent 文件，接收端读不了内嵌 latent 时回退。
    import piexif
except ImportError:  # pragma: no cover - 取决于运行环境
    piexif = None

try:
    import safetensors.torch
except ImportError:  # pragma: no cover - ComfyUI 一定自带 safetensors
    safetensors = None

LOG_PREFIX = "[X-WIDE Image/Latent Sender/Receiver]"

# 接收端在拿不到图像时回退用的空图尺寸（与原版一致，避免下游节点因尺寸突变报错）
EMPTY_SIZE = 64

# 接收端拿不到 latent 时回退用的空 latent（与原版一致）
EMPTY_LATENT_SHAPE = (1, 4, 8, 8)

# 老式 .latent 文件（没有 latent_format_version_0 标记）里存的是未缩放的 latent，
# 读回来要乘这个系数；ComfyUI 自己的 LoadLatent 也是同样的处理。
LEGACY_LATENT_MULTIPLIER = 1.0 / 0.18215

# 预览图的尺寸夹取范围（与原版一致：太小放大、太大缩小）
PREVIEW_LOWER_BOUND = 128
PREVIEW_UPPER_BOUND = 256

# 与原版逐项相同的下拉列表：老工作流里存着这些字符串，删项或改名会让工作流校验失败。
LATENT_PREVIEW_METHODS = [
    "Latent2RGB-FLUX.1",
    "Latent2RGB-SDXL",
    "Latent2RGB-SD15",
    "Latent2RGB-SD3",
    "Latent2RGB-SD-X4",
    "Latent2RGB-Playground-2.5",
    "Latent2RGB-SC-Prior",
    "Latent2RGB-SC-B",
    "Latent2RGB-LTXV",
    "TAEF1",
    "TAESDXL",
    "TAESD15",
    "TAESD3",
    # ↓ 本包新增，只能追加在末尾：上面 13 项与原版逐字相同，老工作流里存的就是这些字符串，
    #    删项或改名会让老工作流校验失败。
    "Latent2RGB-Qwen-Image",
    "Latent2RGB-HunyuanImage",
    "Latent2RGB-Flux.2",
    "Latent2RGB-Wan2.1",
    "Latent2RGB-Wan2.2",
    "Latent2RGB-MingImage",
]

# preview_method → comfy.latent_formats 里的类名（原版 prepare_preview 的等价映射）
LATENT_FORMAT_BY_PREVIEW_METHOD = {
    "Latent2RGB-SD15": "SD15",
    "Latent2RGB-SDXL": "SDXL",
    "Latent2RGB-SD3": "SD3",
    "Latent2RGB-SD-X4": "SD_X4",
    "Latent2RGB-Playground-2.5": "SDXL_Playground_2_5",
    "Latent2RGB-SC-Prior": "SC_Prior",
    "Latent2RGB-SC-B": "SC_B",
    "Latent2RGB-FLUX.1": "Flux",
    "Latent2RGB-LTXV": "LTXV",
    # 本包新增（上面的映射与原版一致，未改动）
    "Latent2RGB-Qwen-Image": "QwenImage21",
    "Latent2RGB-HunyuanImage": "HunyuanImage21",
    "Latent2RGB-Flux.2": "Flux2",
    "Latent2RGB-Wan2.1": "Wan21",
    "Latent2RGB-Wan2.2": "Wan22",
    "Latent2RGB-MingImage": "MingImage",
}

# 选中的预览方式和 latent 的通道数对不上时，按这个优先级自动换一个能出预览的格式。
# 典型场景：Qwen-Image 的 latent 是 64 通道，而下拉默认是 4 通道的 SDXL，
# 硬套 SDXL 系数会直接报 "mat1 and mat2 shapes cannot be multiplied"、预览失败。
AUTO_LATENT_FORMAT_PREFERENCE = [
    "QwenImage21",
    "HunyuanImage21",
    "MingImage",
    "SD3",
    "Flux",
    "Wan21",
    "Wan22",
    "HunyuanVideo15",
    "HunyuanVideo",
    "LTXV",
    "SDXL",
    "SD15",
    "SD_X4",
    "SC_B",
    "SC_Prior",
    "SDXL_Playground_2_5",
]


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
    def VALIDATE_INPUTS(
        cls,
        image=None,
        link_id=0,
        save_to_workflow=False,
        image_data=None,
        trigger_always=False,
        **kwargs,
    ):
        # 参数一律给默认值 + 收 **kwargs：控件被转成输入（或没连线）时 ComfyUI 传不齐参数，
        # 硬写成必填会直接报 "missing 1 required positional argument"。
        if image is None or image == "":
            return True

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
    def IS_CHANGED(
        cls,
        image=None,
        link_id=0,
        save_to_workflow=False,
        image_data=None,
        trigger_always=False,
        **kwargs,
    ):
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


# --------------------------------------------------------------------------- #
#  Latent 收发（原版 LatentSender / LatentReceiver 的等价物）
# --------------------------------------------------------------------------- #


def is_latent_file(name):
    return name.endswith(".latent") or name.endswith(".latent.png")


def empty_latent():
    return {"samples": torch.zeros(EMPTY_LATENT_SHAPE)}


def parse_annotated_value(value, default_type="input"):
    """
    解析 `sub/xxx.latent.png [temp]` 这种带注解的写法。

    等价于原版 LatentReceiver.parse_filename：注解里的 type 决定去哪个目录找文件
    （收到的文件在 temp；用户自己在下拉列表里选的属于 input）。
    """
    text = str(value or "").strip()

    match = re.match(r"^(.*)/(.*?)\[(.*)\]\s*$", text)
    if match:
        return {"filename": match.group(2).rstrip(), "subfolder": match.group(1), "type": match.group(3)}

    match = re.match(r"^(.*?)\[(.*)\]\s*$", text)
    if match:
        return {"filename": match.group(1).rstrip(), "subfolder": "", "type": match.group(2)}

    filename = text.rsplit("/", 1)[-1]
    subfolder = text[: len(text) - len(filename) - 1] if len(text) > len(filename) else ""
    return {"filename": filename, "subfolder": subfolder, "type": default_type}


def load_latent_from_preview_png(path):
    """从预览 PNG 的 EXIF UserComment 里取回内嵌的 latent（原版的做法）。"""
    if piexif is None or safetensors is None:
        logging.warning(
            "%s LatentReceiver - piexif/safetensors unavailable, cannot read the latent "
            "embedded in a preview PNG",
            LOG_PREFIX,
        )
        return None

    with Image.open(path) as image:
        exif_bytes = image.info.get("exif")

    if not exif_bytes:
        return None

    exif = piexif.load(exif_bytes)
    compressed = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment)
    if not compressed:
        return None

    with zipfile.ZipFile(BytesIO(compressed), mode="r") as archive:
        tensor_bytes = archive.read("latent")

    tensor = safetensors.torch.load(tensor_bytes)
    if "latent_tensor" not in tensor:
        return None

    return {"samples": tensor["latent_tensor"]}


def load_latent_file(value):
    """
    读取 `.latent` / `.latent.png`。

    本包对原版的一处修复：原版文件不存在时会在 VALIDATE_INPUTS 直接把节点标红，
    重启 ComfyUI（temp 被清空）后老工作流就全红了。这里改成警告 + 回退成空 latent。
    """
    text = str(value or "").strip()
    if not text:
        return empty_latent()

    try:
        if not folder_paths.exists_annotated_filepath(text):
            raise FileNotFoundError(text)

        path = folder_paths.get_annotated_filepath(text)

        if path.endswith(".latent"):
            if safetensors is None:
                raise RuntimeError("safetensors is not available")
            data = safetensors.torch.load_file(path, device="cpu")
            multiplier = 1.0 if "latent_format_version_0" in data else LEGACY_LATENT_MULTIPLIER
            return {"samples": data["latent_tensor"].float() * multiplier}

        samples = load_latent_from_preview_png(path)
        if samples is not None:
            return samples
    except Exception as error:  # noqa: BLE001 - 任何失败都要回退，不能打断工作流
        logging.warning("%s LatentReceiver - failed to load '%s': %s", LOG_PREFIX, text, error)

    return empty_latent()


def latent_channels_of(latent_tensor):
    """latent 的通道数（拿不到就返回 None）。"""
    try:
        shape = getattr(latent_tensor, "shape", None)
        return int(shape[1]) if shape is not None and len(shape) > 1 else None
    except Exception:  # noqa: BLE001 - 判断不了就当作未知
        return None


def latent_format_fits(latent_format, channels):
    """
    这个格式能不能给指定通道数的 latent 出 Latent2RGB 预览。

    判据和 ComfyUI 自己的一样：latent_rgb_factors 的行数就是通道数
    （Flux2 那种带 reshape 的按 reshape 首维判断）。
    """
    if channels is None:
        return True

    factors = getattr(latent_format, "latent_rgb_factors", None)
    if not factors:
        return False
    if len(factors) == channels:
        return True

    reshape = getattr(latent_format, "latent_rgb_factors_reshape", None)
    if callable(reshape):
        # 例如 Flux2：128 通道先按 2x2 打包成 32 行再乘系数（系数行数 * 4 = 通道数）。
        return len(factors) * 4 == channels
    return False


def matching_latent_format(channels):
    """按通道数找一个能出预览的格式，返回 (类名, 实例) 或 None。"""
    if channels is None:
        return None

    import comfy.latent_formats as latent_formats

    candidates = {}
    for name, factory in vars(latent_formats).items():
        if not isinstance(factory, type):
            continue
        try:
            instance = factory()
        except Exception:  # noqa: BLE001 - 少数格式类构造需要额外参数
            continue
        if latent_format_fits(instance, channels):
            candidates[name] = instance

    for name in AUTO_LATENT_FORMAT_PREFERENCE:
        if name in candidates:
            return name, candidates[name]
    if candidates:
        name = sorted(candidates)[0]
        return name, candidates[name]
    return None


def latent_format_for(preview_method, latent_tensor=None):
    """
    preview_method 字符串 → comfy.latent_formats 的实例（未知取值退回 SD15，与原版一致）。

    本包新增：选中的格式和 latent 的通道数不匹配时（例如 64 通道的 Qwen-Image latent
    配了下拉默认的 SDXL），自动换一个能出预览的格式，并在日志里说明换成了哪个。
    """
    import comfy.latent_formats as latent_formats  # 惰性导入：不拖慢 ComfyUI 启动

    channels = latent_channels_of(latent_tensor)

    class_name = LATENT_FORMAT_BY_PREVIEW_METHOD.get(preview_method)
    factory = getattr(latent_formats, class_name, None) if class_name else None
    if factory is None:
        logging.warning(
            "%s LatentSender - unsupported preview method '%s', falling back to SD15",
            LOG_PREFIX,
            preview_method,
        )
        factory = latent_formats.SD15

    instance = factory()
    if latent_format_fits(instance, channels):
        return instance

    matched = matching_latent_format(channels)
    if matched is not None:
        name, instance = matched
        logging.info(
            "%s LatentSender - preview method '%s' does not fit a %s-channel latent, "
            "using '%s' for the preview instead",
            LOG_PREFIX,
            preview_method,
            channels,
            name,
        )
        return instance

    logging.warning(
        "%s LatentSender - no latent format with preview factors for %s channels, "
        "the thumbnail will be a placeholder",
        LOG_PREFIX,
        channels,
    )
    return factory()


def render_latent_preview(latent_tensor, preview_method):
    """
    把 latent 画成预览图（Latent2RGB，纯 CPU、不需要任何额外模型文件）；失败返回 None。

    与原版的区别：不再往预览图底部贴 Impact Pack 自带的 "latent" 贴纸
    （那是原项目的图片资源，本包不打包它），只保留 latent 本身的画面。
    """
    try:
        from latent_preview import Latent2RGBPreviewer  # ComfyUI 自带的模块

        latent_format = latent_format_for(preview_method, latent_tensor)
        try:
            previewer = Latent2RGBPreviewer(
                latent_format.latent_rgb_factors,
                getattr(latent_format, "latent_rgb_factors_bias", None),
                getattr(latent_format, "latent_rgb_factors_reshape", None),
            )
        except TypeError:  # 老版本 ComfyUI 的构造函数只接受 factors
            previewer = Latent2RGBPreviewer(latent_format.latent_rgb_factors)

        image = previewer.decode_latent_to_preview(latent_tensor)

        min_size = min(image.size[0], image.size[1])
        max_size = max(image.size[0], image.size[1])
        scale_factor = 1
        if max_size > PREVIEW_UPPER_BOUND:
            scale_factor = PREVIEW_UPPER_BOUND / max_size
        if min_size * scale_factor < PREVIEW_LOWER_BOUND:
            scale_factor = PREVIEW_LOWER_BOUND / min_size

        return image.resize(
            (int(image.size[0] * scale_factor), int(image.size[1] * scale_factor)),
            resample=Image.NEAREST,
        )
    except Exception as error:  # noqa: BLE001 - 预览失败不该影响 latent 的传递
        logging.warning(
            "%s LatentSender - preview rendering failed (%s): %s", LOG_PREFIX, preview_method, error
        )
        return None


def placeholder_preview(latent_tensor):
    """
    预览渲染失败时的占位缩略图。

    为什么要有它：以前只要预览渲染失败（例如格式和 latent 通道数对不上）就整个降级成
    `<名字>_<序号>_.latent` 纯文件，接收端连缩略图框都不出现、看起来像"没收到"。
    现在仍然写 `.latent.png`，只是缩略图是空的 —— 文件格式没变、EXIF 里的 latent 也一个字节不少。
    """
    size = PREVIEW_LOWER_BOUND
    tile = Image.new("RGB", (size, size), (32, 32, 32))
    return tile


def save_latent_file(latent_tensor, full_output_folder, filename, counter, preview_method, prompt, extra_pnginfo):
    """
    写出文件，返回文件名。

    正常情况写 `<名字>_<序号>_.latent.png`：预览图 + EXIF 里内嵌的 latent，
    与原版完全一致（接收端也就能从 EXIF 里读回来）。
    预览渲染不出来时用占位缩略图，文件格式与内嵌的 latent 都不变。
    只有没有 piexif（写不了 EXIF）时才退化成 `<名字>_<序号>_.latent` 纯文件。
    """
    base = f"{filename}_{counter:05}_"

    if safetensors is None:
        raise RuntimeError("safetensors is not available, cannot save the latent")

    # 没有 piexif 就塞不进 EXIF，只能写纯 .latent（收发照旧，只是接收端没有缩略图）。
    if piexif is None:
        file = base + ".latent"
        # 带上 ComfyUI 的版本标记：值已经是现代缩放，读端不要再去乘 1/0.18215。
        safetensors.torch.save_file(
            {"latent_tensor": latent_tensor, "latent_format_version_0": torch.tensor([])},
            os.path.join(full_output_folder, file),
        )
        return file

    preview = render_latent_preview(latent_tensor, preview_method)
    if preview is None:
        logging.warning(
            "%s LatentSender - using a placeholder thumbnail for '%s'", LOG_PREFIX, base
        )
        preview = placeholder_preview(latent_tensor)

    file = base + ".latent.png"

    compressed = BytesIO()
    with zipfile.ZipFile(compressed, mode="w") as archive:
        archive.writestr("latent", safetensors.torch.save({"latent_tensor": latent_tensor}))

    metadata = PngImagePlugin.PngInfo()
    if prompt is not None:
        metadata.add_text("prompt", json.dumps(prompt))
    if extra_pnginfo is not None:
        for key in extra_pnginfo:
            metadata.add_text(key, json.dumps(extra_pnginfo[key]))

    preview.save(
        os.path.join(full_output_folder, file),
        format="png",
        exif=piexif.dump({"Exif": {piexif.ExifIFD.UserComment: compressed.getvalue()}}),
        pnginfo=metadata,
        optimize=True,
    )
    return file


class XWIDE_LatentReceiver:
    """X-WIDE Latent Receiver —— 接收 X-WIDE Latent Sender（或原版 LatentSender）发来的 latent。"""

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        try:
            files = [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f)) and is_latent_file(f)
            ]
        except FileNotFoundError:
            files = []

        return {
            "required": {
                "latent": (
                    sorted(files),
                    {
                        "tooltip": "要读取的 latent 文件（.latent 或带预览的 .latent.png）。"
                        "收到 Sender 发来的文件后这里会自动填入。 / "
                        "Latent file to load (.latent, or a preview .latent.png). "
                        "Filled automatically with the received file."
                    },
                ),
                "link_id": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": sys.maxsize,
                        "step": 1,
                        "tooltip": "配对编号：和 Latent Sender 的 link_id 相同才会收到它的 latent。 / "
                        "Pairing id: only the Sender with the same link_id will send to this node.",
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
    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)

    CATEGORY = "X-WIDE/Latent"

    DESCRIPTION = (
        "接收 Latent Sender（X-WIDE 版或 Impact Pack 原版）传过来的 latent，输出 LATENT。"
        " / Receives the latent sent by Latent Sender (X-WIDE or the original Impact Pack node)."
    )

    SEARCH_ALIASES = [
        "X-WIDE",
        "X-WIED",
        "xwide",
        "x wide",
        "latent receiver",
        "latent",
        "receiver",
        "潜空间接收",
        "潜空间接收器",
        "潜空间",
        "接收",
    ]

    def doit(self, latent, link_id, trigger_always):
        return {
            "ui": {"images": [parse_annotated_value(latent)]},
            "result": (load_latent_file(latent),),
        }

    @classmethod
    def IS_CHANGED(cls, latent=None, link_id=0, trigger_always=False, **kwargs):
        # 参数一律给默认值 + 收 **kwargs：控件被转成输入（或没连线）时 ComfyUI 传不齐参数，
        # 硬写成必填会直接报 "missing 1 required positional argument"。
        if trigger_always:
            return float("NaN")

        try:
            if latent and folder_paths.exists_annotated_filepath(latent):
                digest = hashlib.sha256()
                with open(folder_paths.get_annotated_filepath(latent), "rb") as handle:
                    digest.update(handle.read())
                return digest.digest().hex()
        except Exception as error:  # noqa: BLE001 - 退化到按名字判断
            logging.warning("%s LatentReceiver - hashing '%s' failed: %s", LOG_PREFIX, latent, error)

        return hash(latent)

    @classmethod
    def VALIDATE_INPUTS(cls, latent=None, link_id=0, trigger_always=False, **kwargs):
        # 还没来得及连线 / 值是空的都放行，由 doit 回退成空 latent，不要在排队阶段把节点标红。
        if latent is None or latent == "":
            return True

        if not isinstance(latent, str) or latent.startswith("/") or ".." in latent:
            return "Invalid latent file: {}".format(latent)

        # 文件可能已经被清空（ComfyUI 重启会清 temp）：放行，由 doit 回退成空 latent。
        return True


class XWIDE_LatentSender(comfy_nodes.SaveLatent):
    """X-WIDE Latent Sender —— 把 latent 发给同 link_id 的 Latent Receiver，并在节点上显示预览。"""

    def __init__(self):
        super().__init__()
        # 与原版一致：发出去的文件放临时目录，重启即清空
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": (
                    "LATENT",
                    {
                        "tooltip": "要发送的 latent。 / Latent to send."
                    },
                ),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "latents/LatentSender",
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
                        "tooltip": "配对编号：和 Latent Receiver 的 link_id 相同才会发过去。 / "
                        "Pairing id: only the Receiver with the same link_id receives this latent.",
                    },
                ),
                "preview_method": (
                    LATENT_PREVIEW_METHODS,
                    {
                        "default": "Latent2RGB-SDXL",
                        "tooltip": "预览图的解码方式（只影响预览图，不影响传递的 latent 本身）。 / "
                        "How the preview image is decoded (it does not affect the latent itself).",
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    OUTPUT_NODE = True
    FUNCTION = "doit"

    CATEGORY = "X-WIDE/Latent"

    DESCRIPTION = (
        "把 latent 保存到临时目录并通过 latent-send 事件发给同 link_id 的 Latent Receiver；"
        "节点上会显示一个预览图（预览图里同时内嵌了 latent 本体）。 / Saves the latent to the temp "
        "folder and sends it to the Latent Receiver with the same link_id via the latent-send event; "
        "a preview image is shown on the node (the latent itself is embedded in that PNG)."
    )

    SEARCH_ALIASES = [
        "X-WIDE",
        "X-WIED",
        "xwide",
        "x wide",
        "latent sender",
        "latent",
        "sender",
        "潜空间发送",
        "潜空间发送器",
        "潜空间",
        "发送",
    ]

    def doit(
        self,
        samples,
        filename_prefix="latents/LatentSender",
        link_id=0,
        preview_method="Latent2RGB-SDXL",
        prompt=None,
        extra_pnginfo=None,
    ):
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir
        )

        # safetensors 要求连续内存、CPU 上的张量
        tensor = samples["samples"].detach().cpu().contiguous()

        file = save_latent_file(
            tensor, full_output_folder, filename, counter, preview_method, prompt, extra_pnginfo
        )

        latent_path = {"filename": file, "subfolder": subfolder, "type": self.type}

        PromptServer.instance.send_sync(
            "latent-send", {"link_id": link_id, "images": [latent_path]}
        )

        return {"ui": {"images": [latent_path]}}


NODE_CLASS_MAPPINGS = {
    "XWIDE_ImageSender": XWIDE_ImageSender,
    "XWIDE_ImageReceiver": XWIDE_ImageReceiver,
    "XWIDE_LatentSender": XWIDE_LatentSender,
    "XWIDE_LatentReceiver": XWIDE_LatentReceiver,
}

# 显示名里带 X-WIDE：节点搜索框里输入 xwide / x-wide / X-WIDE / image sender 都能搜到
# （ComfyUI 的搜索会匹配显示名、分类与 SEARCH_ALIASES）。
NODE_DISPLAY_NAME_MAPPINGS = {
    "XWIDE_ImageSender": "X-WIDE Image Sender 图像发送器",
    "XWIDE_ImageReceiver": "X-WIDE Image Receiver 图像接收器",
    "XWIDE_LatentSender": "X-WIDE Latent Sender 潜空间发送器",
    "XWIDE_LatentReceiver": "X-WIDE Latent Receiver 潜空间接收器",
}
