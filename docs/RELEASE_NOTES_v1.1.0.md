# v1.1.0 — 新增潜空间收发 / Latent Sender & Receiver

> 这份文件是 GitHub Release 的现成文案：在
> <https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/releases/new>
> 里选好标签 `v1.1.0`，把下面横线以内的内容整段粘进正文即可。

---

## 中文

这个版本把 **Latent Sender / Latent Receiver** 也独立封装进本包，
节点总数从 2 个增加到 4 个：

| 节点 | 类型名 | 输出 | 分类 |
| --- | --- | --- | --- |
| X-WIDE Image Sender 图像发送器 | `XWIDE_ImageSender` | — | `X-WIDE/Image` |
| X-WIDE Image Receiver 图像接收器 | `XWIDE_ImageReceiver` | `IMAGE` / `MASK` | `X-WIDE/Image` |
| X-WIDE Latent Sender 潜空间发送器 | `XWIDE_LatentSender` | — | `X-WIDE/Latent` |
| X-WIDE Latent Receiver 潜空间接收器 | `XWIDE_LatentReceiver` | `LATENT` | `X-WIDE/Latent` |

潜空间那一对和图像那一对用法相同，区别是**传的是 LATENT 本体**，
省掉一次「解码成图再编码回 latent」。协议仍与原版一致：
写 `<前缀>_<序号>_.latent.png`（Latent2RGB 预览图 + EXIF 里内嵌的 latent）、
发 `latent-send` 事件、控件写法 `名称 [temp]`，因此可以和 Impact Pack
的 `LatentSender` / `LatentReceiver` 互相配对。

### 新增

- `XWIDE_LatentSender`：控件 `samples` / `filename_prefix`(默认 `latents/LatentSender`) /
  `link_id` / `preview_method`；`preview_method` 前 13 项与原版逐项一致（未知取值退回
  SD15），另追加 `Latent2RGB-Qwen-Image`、`Latent2RGB-HunyuanImage`、`Latent2RGB-Flux.2`、
  `Latent2RGB-Wan2.1`、`Latent2RGB-Wan2.2`、`Latent2RGB-MingImage`（只追加，不动前 13 项）。
- `XWIDE_LatentReceiver`：控件 `latent`（自动列出输入目录里的 `.latent` / `.latent.png`）/
  `link_id` / `trigger_always`，输出 `LATENT`。
- 前端新增 `latent-send` 监听：收到后把文件名写进 `latent` 控件并显示预览
  （纯 `.latent` 没有预览图，只刷新控件）。

### 修复（相对原版）

- **latent 文件不存在不再报红**：原版在 `VALIDATE_INPUTS` 里直接拒绝，
  ComfyUI 重启（`temp` 被清空）后老工作流整片变红；现在只拒绝绝对路径与 `..`，
  文件缺失时告警并回退空 latent（`1×4×8×8`）。
- 原版 `LatentReceiver` 拿不到输入时返回裸张量 `torch.zeros([1,4,8,8])`，
  下游会拿到错误类型；本包统一返回合法的 `LATENT`。
- 按 ComfyUI 约定处理缩放：没有 `latent_format_version_0` 标记的老 `.latent`
  乘 `1/0.18215`，本包自己写出的文件一定带标记，不会被重复缩放。

### 首次实测后的追加修复

第一轮实测（Qwen-Image 2.1 工作流）暴露出三个问题，都已修掉：

- **预览格式不和 latent 通道数匹配时不再失败**：64 通道的千问 latent 配上下拉默认的
  4 通道 `Latent2RGB-SDXL`，`Latent2RGBPreviewer` 会报
  `mat1 and mat2 shapes cannot be multiplied (…x64 and 4x3)`。现在会**按 latent 的实际
  通道数自动挑一个能出预览的格式**（优先 Qwen-Image / HunyuanImage，其次 SD3 / Flux /
  Wan / LTXV / SDXL / SD15 …），并在日志里写明换成了哪个；用户可以仍然随便选，
  选错也不会失败。
- **预览渲染失败不再降级成纯 `.latent`**：以前预览画不出来就整份写成
  `<前缀>_<序号>_.latent`，接收节点上连缩略图框都不出现，看起来像「没收到」。
  现在照旧写 `.latent.png`（缩略图退化成占位图），协议与 EXIF 里内嵌的 latent 都不变。
- **接收节点的输入控件被转成输入 / 未连线时不再报错**：`VALIDATE_INPUTS` / `IS_CHANGED`
  原来把 `latent`（图像版是 `image`）写成必填参数，ComfyUI 少传一个就报
  `missing 1 required positional argument: 'latent'` 并**忽略整个 prompt**；现在参数都有
  默认值并接收 `**kwargs`，缺失时照常回退成空 latent / 占位图。
- **界面**：画布 / 节点右键菜单里的入口现在带插件名与版本号
  （`ℹ X-WIDE Image Latent Sender/Receiver v1.1.0 · 信息 / About`），不会再和别的插件的
  「关于 / About」混淆。
- **命名**：插件总名统一为 **`X-WIDE Image Latent Sender / Receiver`**（中文「图片 和 潜空间收发」），
  管理器卡片 / Registry 卡片 / 画布菜单 / About 窗口 / README 一致；四颗节点自己的名字不变。

### 兼容性

- 不依赖 Impact Pack，可与它同时安装、互相配对；
- 只用到环境里本就存在的可选库 `piexif` 与 `safetensors`；缺失时不报错，
  退化为写 / 读纯 `.latent` 文件，收发照常，只是接收节点上没有缩略图；
- 图像那一对的 4 项修复、双语界面、画布 / 节点右键的「信息 / About」署名页全部保留。

### 验证

- 前端行为测试台 **54/54**（新增 18 条 latent 用例：配对、写控件、预览、
  纯 `.latent` 不请求图片、两个事件互不串扰、link_id 转输入后仍接收、双语控件名、
  About 文案、菜单项与 About 标题带插件名与版本、About 副标题的中文名）；
- 后端离线验证 **63/63**（新增：控件契约、`preview_method` 前 13 项与原版逐项一致、
  Sender 落盘 + `latent-send` 事件、**往返读回同一个 latent（maxdiff = 0）**、
  64 通道 latent 自动改用 Qwen-Image 出预览、8 通道等无匹配格式时仍写 `.latent.png` 占位、
  四个「完全不传参数」的 `VALIDATE_INPUTS` / `IS_CHANGED` 用例、
  老格式缩放、缺失文件 / 普通 PNG 回退空 latent）；
- 实机端到端 **52/52**（对运行中的 ComfyUI 发真实 prompt：四节点注册与双语显示名、
  `/view` 取回产物、两个路径穿越负例 400、跨 prompt 复用 temp 文件、64 通道千问场景、
  前端脚本线上与磁盘逐字节一致）；
- `py_compile` 通过。

---

## English

This release packages the **Latent Sender / Latent Receiver** pair as well —
four nodes in total, all bilingual, no Impact Pack required:

- `XWIDE_LatentSender` (category `X-WIDE/Latent`): widgets `samples` /
  `filename_prefix` (default `latents/LatentSender`) / `link_id` / `preview_method`
  (the same 13 options as the original).
- `XWIDE_LatentReceiver`: widgets `latent` / `link_id` / `trigger_always`,
  outputting `LATENT`.

The latent pair works like the image pair, but passes the `LATENT` itself,
saving a decode-then-re-encode round trip. The protocol is unchanged from the
original — `<prefix>_<counter>_.latent.png` (a Latent2RGB preview with the latent
embedded in its EXIF), the `latent-send` event, and the `name [temp]` widget
format — so it can pair with Impact Pack's `LatentSender` / `LatentReceiver`.

Fixes over the original: a missing latent file no longer turns the node red after
a restart (warning + empty latent fallback), the receiver always returns a valid
`LATENT` instead of a bare tensor, and the legacy scaling of `.latent` files
without a `latent_format_version_0` marker is handled per ComfyUI convention.

Verified with a 54/54 front-end behaviour suite, a 63/63 back-end suite (including
an exact latent round trip), a 52/52 end-to-end suite against a running ComfyUI,
and `py_compile`.
