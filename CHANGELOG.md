# 更新日志 / Changelog

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
