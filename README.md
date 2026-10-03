# X-WIDE Image / Latent Sender & Receiver

[English](https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/blob/main/README.en.md) | **中文**

把画布上一处的东西「发」给另一处，四颗节点：

- **图像**：`X-WIDE Image Sender` 发送 → `X-WIDE Image Receiver` 接收，输出 `IMAGE` / `MASK`；
- **潜空间**：`X-WIDE Latent Sender` 发送 → `X-WIDE Latent Receiver` 接收，输出 `LATENT`（直接传 latent，省掉一次「解码成图再编码回 latent」）。

本包是 **ltdrdata (Dr.Lt.Data)** 在 [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) 中的 `Image Sender` / `Image Receiver` / `Latent Sender` / `Latent Receiver` 的独立封装版本，由 **X-WIDE** 维护：

> **只优化界面显示（中英双语）并修复原节点的 BUG，没有新增功能**，也**不需要安装 Impact Pack**。

当前版本：**1.1.0**（新增潜空间那一对节点）—— 变更明细见 [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/blob/main/CHANGELOG.md)。

收发协议与原版完全一致（`img-send` / `latent-send` 事件、`名称.png [temp]` 的控件写法），因此可以和 Impact Pack 的收发节点混用、互相配对，老工作流也能照着替换。

---

## 修复了什么

| # | 问题（原版） | 原因 | 现在的行为 |
| --- | --- | --- | --- |
| 1 | **切换工作流再切回来，收到的图就失效了** | 前端 `node.imgs` 的 getter 里写的是 `api.fetchApi(...).then(r => r)`（恒等映射），`res.status` 永远是 `undefined`，`image.src` 从来没被换成 `/view?...` | 同步拼出 `/view?filename=…&type=temp&subfolder=…` 直接赋给 `image.src`；失败时按候选地址依次回退（临时文件 → 输入目录 → 旧草稿里的 base64） |
| 2 | **勾选「保存到工作流」后不停弹「保存工作流草稿失败」** | 收到的图被 `canvas.toDataURL()` 写进 `image_data` 控件值 → 几 MB base64 进了 `widgets_values` → 进了工作流与 localStorage 草稿 → `QuotaExceededError` | `image_data` 的 value 恒为空串，base64 不再进入工作流 / 草稿；改由 `widget.serializeValue` 在**排队那一刻**按需生成，只注入 API 提示 |
| 3 | **大图会让整个画布卡顿** | 控件值会被画进画布、还要进文本测量缓存，几 MB 字符串每帧都在做重活；`node.imgs` 的 getter 每次重绘都会被调用 | 控件值不再承载 base64；`node.imgs` 只读一份缓存，且恢复预览**只尝试一次** |
| 4 | **图片文件没了，节点直接报错** | `doit` 直接调用 `LoadImage().load_image()`，临时文件被清空后抛异常 | 改为带回退的读取函数：读不到就 `logging.warning` + 输出 64×64 占位图，不打断工作流 |
| 5 | **latent 文件没了（重启后 temp 被清空），节点报红** | 原版 `LatentReceiver` 在 `VALIDATE_INPUTS` 里直接拒绝不存在的文件 | 只拒绝绝对路径与 `..`；文件缺失时告警 + 回退空 latent（`1×4×8×8`），不打断工作流 |
| 6 | **原版 `LatentReceiver` 拿不到输入时返回裸张量** | 返回 `torch.zeros([1,4,8,8])` 而不是 `{"samples": …}`，下游拿到错误类型 | 统一返回合法的 `LATENT` |

![修复前的报错：保存工作流草稿失败](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-image-sender-receiver/main/docs/images/draft-save-error.png)

---

## 安装

**方式一：ComfyUI Manager（推荐）**

1. 打开 Manager → **Install via Git URL**；
2. 填入仓库地址：`https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver`
3. 重启 ComfyUI，刷新页面（`Ctrl` + `F5`）。

**方式二：手动**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver
```

本包**不需要**额外依赖：只用到 ComfyUI 自带的 `torch` / `numpy` / `Pillow` 与前端 API。

---

## 使用

1. 添加一个 **X-WIDE Image Sender**，把图接到它的 `images` 输入；
2. 添加一个 **X-WIDE Image Receiver**，把它的 `image` 输出接到下游节点；
3. 让两个节点的 **`link_id` 相同**（默认都是 `0`），Sender 执行后图片就会出现在 Receiver 上。

> `link_id` 也可以右键「转换成输入」，用 `Primitive` / `ImpactInt` 连线来驱动（和原版一样）：
> 转换后视为「已连接」，Receiver 会直接接收图片。

| 节点 | 控件 | 说明 |
| --- | --- | --- |
| X-WIDE Image Sender | `images` | 要发送的图像 |
| | `filename_prefix` | 存到临时目录时用的文件名前缀（默认 `ImgSender`） |
| | `link_id` | 配对编号：和 Receiver 相同才会发过去 |
| X-WIDE Image Receiver | `image` | 收到图后自动填入临时文件名，也可手动选择输入目录里的图片 |
| | `link_id` | 配对编号 |
| | `save_to_workflow` | 勾选后，收到的图会在排队时作为图像数据随提示一起发送（**工作流文件本身不会内联 base64**） |
| | `image_data` | 图像数据，由前端在排队时按需生成；平时保持为空 |
| | `trigger_always` | 开启后本节点每次都重新执行（忽略缓存） |

### 两种工作方式

- **不勾 `save_to_workflow`**：Receiver 直接读取 `image` 控件里记录的**临时文件**，所以图片必须还留在 `ComfyUI/temp` 里。切换工作流再切回，预览依然会恢复。
- **勾上 `save_to_workflow`**：排队时前端把收到的图编码为 base64 注入提示的 `image_data`，后端据此还原图像，**执行时不再依赖临时文件**；同时工作流与草稿保持轻量。

> ⚠️ 两种方式下，图片本体都存在 `ComfyUI/temp` 中。**ComfyUI 重启后 temp 会被清空**，此时需要重新发送一次图片。想让图片永久保留在工作流里，请使用 `Load Image` / `Save Image` 这类节点。

### 潜空间（Latent）那一对（v1.1.0 起）

用法与图像那一对完全相同，只是传的是 `LATENT` 本体：

1. 添加 **X-WIDE Latent Sender**，把 `LATENT` 接到它的 `samples` 输入；
2. 添加 **X-WIDE Latent Receiver**，把它的 `latent` 输出接到 `KSampler` / `VAEDecode` 等下游；
3. 两个节点的 **`link_id` 相同**（默认 `0`），Sender 执行后 latent 就会出现在 Receiver 上。

| 节点 | 控件 | 说明 |
| --- | --- | --- |
| X-WIDE Latent Sender | `samples` | 要发送的 latent |
| | `filename_prefix` | 存到临时目录时用的文件名前缀（默认 `latents/LatentSender`） |
| | `link_id` | 配对编号 |
| | `preview_method` | 预览图的解码方式（Latent2RGB-SDXL / SD15 / FLUX.1 … 前 13 项与原版逐项一致，另追加 Qwen-Image / HunyuanImage / Flux.2 / Wan2.1 / Wan2.2 / MingImage；只影响预览图，不影响传递的 latent） |
| X-WIDE Latent Receiver | `latent` | 收到后自动填入临时文件名，也可手动选择输入目录里的 `.latent` / `.latent.png` |
| | `link_id` | 配对编号 |
| | `trigger_always` | 开启后本节点每次都重新执行（忽略缓存） |

- Sender 写出的文件是 `<前缀>_<序号>_.latent.png`：一张 Latent2RGB 预览图，latent 本体打包在它的 EXIF 里（与原版一致），接收端可原样读回。
- 预览格式会**按 latent 的通道数自动匹配**：选中的格式和 latent 对不上时（典型是 64 通道的千问 Qwen-Image latent 配了下拉里 4 通道的 SDXL）会自动换成合适的格式并在日志里写明，所以千问 / 混元等新模型也能出预览图；实在没有匹配格式时缩略图是占位图，但文件仍是 `.latent.png`、latent 照常传递。
- 同样存放在 `ComfyUI/temp`，**重启后会被清空**，需要重新发送一次；此时 Receiver 不会报红，只会输出一个空 latent 并打一条警告。
- 预览图依赖 `piexif`、latent 序列化依赖 `safetensors`（ComfyUI 环境里通常都已存在）。若 `piexif` 缺失，Sender 会退化成写纯 `.latent` 文件：收发照常，只是接收节点上没有缩略图。

### 「信息 / About」署名页

在**画布空白处右键**或**节点上右键**，选择 `ℹ 信息 / About` 即可打开：里面写明了本版本的作者（X-WIDE）、原作者（ltdrdata）与可点击的作者主页 / 项目主页链接，以及本版本只做界面优化与 BUG 修复的说明。

---

## 中英双语

界面按浏览器语言自动切换：

- 中文环境：`图像 / image`、`保存到工作流 / save_to_workflow` …
- 英文环境：显示同样的「中文名 / 参数名」对照，方便照着原版教程使用。

节点显示名为 `X-WIDE Image Sender 图像发送器`、`X-WIDE Image Receiver 图像接收器`、`X-WIDE Latent Sender 潜空间发送器`、`X-WIDE Latent Receiver 潜空间接收器`；搜索框输入 `xwide`、`x-wide`、`sender`、`receiver`、`latent`、`图像发送`、`图像接收`、`潜空间发送`、`潜空间接收` 都能找到。节点分类为 `X-WIDE/Image`（图像）与 `X-WIDE/Latent`（潜空间）。

---

## 与 Impact Pack 的关系

- 本包**不依赖** Impact Pack，可单独安装；
- 两个包**可以同时安装**：因为协议一致（`img-send` / `latent-send` 事件与 `名称.png [temp]` 的写法），X-WIDE 版的 Sender 能把图 / latent 发给原版 Receiver，反之亦然；
- 原节点与本包的节点类型名不同（`ImageSender` ↔ `XWIDE_ImageSender`、`LatentSender` ↔ `XWIDE_LatentSender`），所以同一张画布上可以同时存在，不会互相覆盖。

## 目录结构

```
comfyui-x-wide-image-sender-receiver/
├── __init__.py              # 注册节点 + WEB_DIRECTORY
├── nodes.py                 # 两个节点（Python 侧）
├── web/xwide_image.js       # 前端：双语控件名、img-send 接收、预览恢复、About 页、右键菜单
├── web/logo_xwide.png       # About 页用的作者 logo
├── web/logo_xwide_icon.png  # 节点管理器图标（Registry Icon）
├── pyproject.toml           # Comfy Registry 元数据
├── CHANGELOG.md             # 更新日志
├── NOTICE                   # 版权与来源说明（GPL-3.0 义务）
├── LICENSE                  # GPL-3.0
└── docs/发布指南.md         # 发布到 GitHub / Comfy Registry 的步骤
```

## 许可与致谢

- 本项目以 **GPL-3.0** 授权，见 [LICENSE](https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/blob/main/LICENSE)；
- 原节点 `Image Sender` / `Image Receiver` / `Latent Sender` / `Latent Receiver` 由 **ltdrdata (Dr.Lt.Data)** 在 ComfyUI-Impact-Pack 中开发，版权归原作者所有；
- 本版本的修改部分版权归 **X-WIDE** 所有。修改内容与 GPL-3.0 义务声明见 [NOTICE](https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/blob/main/NOTICE) 与 [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/blob/main/CHANGELOG.md)。

原作者主页：<https://github.com/ltdrdata> · 原项目：<https://github.com/ltdrdata/ComfyUI-Impact-Pack>

## 交流

- 作者主页：<https://space.bilibili.com/374064919>
- 问题反馈：<https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/issues>
