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
  `link_id` / `preview_method`；`preview_method` 选项与原版逐项一致（13 项，
  未知取值退回 SD15）。
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

### 兼容性

- 不依赖 Impact Pack，可与它同时安装、互相配对；
- 只用到环境里本就存在的可选库 `piexif` 与 `safetensors`；缺失时不报错，
  退化为写 / 读纯 `.latent` 文件，收发照常，只是接收节点上没有缩略图；
- 图像那一对的 4 项修复、双语界面、画布 / 节点右键的「信息 / About」署名页全部保留。

### 验证

- 前端行为测试台 **50/50**（新增 15 条 latent 用例：配对、写控件、预览、
  纯 `.latent` 不请求图片、两个事件互不串扰、link_id 转输入后仍接收、双语控件名、
  About 文案）；
- 后端离线验证 **50/50**（新增：控件契约、`preview_method` 与原版逐项一致、
  Sender 落盘 + `latent-send` 事件、**往返读回同一个 latent（maxdiff = 0）**、
  老格式缩放、缺失文件 / 普通 PNG 回退空 latent、VALIDATE 与 IS_CHANGED）；
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

Verified with a 50/50 front-end behaviour suite, a 50/50 back-end suite
(including an exact latent round trip) and `py_compile`.
