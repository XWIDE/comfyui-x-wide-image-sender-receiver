# 更新日志 / Changelog

## 1.1.0 — 2026-10-04

新增潜空间（LATENT）那一对节点，功能对齐 ComfyUI-Impact-Pack 原版：
`X-WIDE Latent Sender 潜空间发送器` / `X-WIDE Latent Receiver 潜空间接收器`。
仍然是**等价实现 + 只修 BUG、不新增原版没有的能力**，依旧不依赖 Impact Pack。

### 新增

- **X-WIDE Latent Sender**（`XWIDE_LatentSender`，输出节点）
  - 控件：`samples` / `filename_prefix`（默认 `latents/LatentSender`）/ `link_id` / `preview_method`。
  - 文件名、事件名与元数据写法与原版一致：写到 ComfyUI 的 `temp` 目录，发 `latent-send` 事件
    （`{"link_id": …, "images": [{"filename", "subfolder", "type"}]}`）。
  - 正常写 `<前缀>_<序号>_.latent.png`：Latent2RGB 预览图 + 把 latent 打包塞进 PNG 的
    EXIF `UserComment`（zip + safetensors），接收端可原样读回。预览图不再贴 Impact Pack 自带的
    「latent」贴纸（那是原项目的图片资源，本包不打包它）。
  - `preview_method` 选项与原版逐项一致：Latent2RGB-FLUX.1 / SDXL / SD15 / SD3 / SD-X4 /
    Playground-2.5 / SC-Prior / SC-B / LTXV / TAEF1 / TAESDXL / TAESD15 / TAESD3；
    未知取值退回 SD15 并告警。
- **X-WIDE Latent Receiver**（`XWIDE_LatentReceiver`，输出 `LATENT`）
  - 控件：`latent`（自动列出输入目录里的 `.latent` / `.latent.png`）/ `link_id` / `trigger_always`。
  - `doit` 返回 `{"ui": {"images": [...]}, "result": (latent,)}`，与原版一致。
- 前端新增 `latent-send` 监听：把收到的文件名写进 `latent` 控件，并在节点上显示预览
  （纯 `.latent` 没有预览图，只刷新控件）。X-WIDE 与 Impact Pack 混装时，两边各写各的节点类型。

### 修复（相对原版）

- **文件不存在不再报红**：原版在 `VALIDATE_INPUTS` 里直接拒绝，ComfyUI 重启（`temp` 被清空）
  后老工作流整片变红。现在只拒绝绝对路径与 `..`，文件缺失改为 `logging.warning` +
  回退空 latent（`1×4×8×8`）。
- 原版 `doit` 在拿不到 `latent` 参数时返回裸张量 `torch.zeros([1,4,8,8])` 而不是
  `{"samples": …}`，下游会收到错误类型；本包统一返回合法的 `LATENT`。
- 读 `.latent` 时按 ComfyUI 的约定处理缩放：没有 `latent_format_version_0` 标记的老文件
  乘 `1/0.18215`，本包自己写出的文件一定带标记，避免被重复缩放。

### 兼容性

- 沿用原版协议（`latent-send` 事件、`名称 [temp]` 的控件写法），可与 Impact Pack 的
  `LatentSender` / `LatentReceiver` 互相配对。
- 只用到 ComfyUI 环境里本就存在的可选库 `piexif` 与 `safetensors`；缺失时不报错，
  退化为写/读纯 `.latent` 文件，收发依旧可用，只是接收节点上没有缩略图。
- 版本号统一：`__init__.py` / `web/xwide_image.js` / `CHANGELOG.md` 均为 `1.1.0`。

## 1.0.0 — 2026-10-04

首个发布版本：把 ComfyUI-Impact-Pack（原作者 **ltdrdata**）里的
`Image Sender` / `Image Receiver` 独立封装为 X-WIDE 版。
**只优化界面显示并修复 BUG，没有新增功能**；不依赖 Impact Pack。
收发协议（`img-send` 事件、`名称.png [temp]` 的控件写法）与原版保持一致。

### 修复

1. **切换工作流再切回来，收到的图失效**
   - 原版前端在 `node.imgs` 的 getter 里写 `api.fetchApi(...).then(r => r)`，这是恒等映射，
     `res.status` 恒为 `undefined`，所以 `image.src` 从未被替换成 `/view?...`。
   - 现在同步拼出 `/view?filename=…&type=temp&subfolder=…` 赋给 `image.src`；
     加载失败时按候选地址依次回退（临时文件 → 输入目录 → 旧草稿里残留的 base64）。
2. **勾选「保存到工作流」后不停弹「保存工作流草稿失败」**
   - 原版把收到的图 `canvas.toDataURL()` 写进 `image_data` 控件值，几 MB 的 base64
     进入 `widgets_values` → 进入工作流与 localStorage 草稿 → `QuotaExceededError`。
   - 现在 `image_data` 的 value getter 恒返回空串，base64 不再进入工作流 / 草稿；
     改由 `widget.serializeValue` 在排队时按需生成，只注入 API 提示。
3. **大图导致画布卡顿**
   - 控件值会被画进画布、还要进文本测量缓存；`node.imgs` 的 getter 每次重绘都会被调用，
     每次都在做重活。
   - 现在控件值不再承载 base64；`node.imgs` 只读一份缓存，且恢复预览**只尝试一次**。
4. **图片文件不存在时节点直接抛异常**
   - 原版 `doit` 直接调用 `LoadImage().load_image()`，临时文件被清空后会抛异常、整个节点报红。
   - 现在统一走带回退的读取函数：读不到就 `logging.warning` + 输出 64×64 占位图。

### 界面

- 控件名、提示、节点说明中英双语（按浏览器语言自动切换）。
- 新增「信息 / About」署名页：本版本作者 **X-WIDE** + 原作者 **ltdrdata**，
  含可点击的作者主页 / 项目主页链接，并注明本版本只做界面优化与 BUG 修复。
  入口：画布右键菜单、节点右键菜单。
- 节点分类为 `X-WIDE/Image`；显示名 `X-WIDE Image Sender 图像发送器`、
  `X-WIDE Image Receiver 图像接收器`；搜索别名支持 `xwide` / `x-wide` / `sender` /
  `receiver` / `图像发送` / `图像接收` 等。
- 补充 `DESCRIPTION` 与每个控件的 `tooltip`（中英双语）。

### 兼容性

- 与原版 Impact Pack 的收发节点可共存、可互相配对（协议一致）。
- `link_id` 支持转成输入（用 `Primitive` / `ImpactInt` 连线驱动）：与原版一致，
  此时视为「已连接」直接接收图片，不再按控件数值过滤。
- 节点类型名改为 `XWIDE_ImageSender` / `XWIDE_ImageReceiver`，可与原节点同画布共存。
- `VALIDATE_INPUTS` 放行原版写进提示的 `#DATA` 占位符，并继续拒绝绝对路径与 `..`。
