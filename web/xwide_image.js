/**
 * X-WIDE Image Sender / Image Receiver —— 前端扩展
 * ================================================
 *
 * 原节点 Image Sender / Image Receiver 由 ltdrdata (Dr.Lt.Data) 在
 * ComfyUI-Impact-Pack 中开发（GPL-3.0）。本文件是 X-WIDE 独立版本的前端部分：
 * 收发协议（`img-send` 事件、`name.png [temp]` 的控件写法）与原版一致，
 * 因此两个包可以共存、互相配对；改动只有界面双语化 + 三个 BUG 修复。
 *
 * 三个修复各自的关键点（都尽量少做事，避免又引入性能问题）：
 *
 * 1) 切换工作流后收到的图失效
 *    原版在 `node.imgs` 的 getter 里写 `api.fetchApi(...).then(r => r)`，那是个
 *    恒等映射 —— `.status` 永远是 undefined，所以 `image.src` 从来没被换成
 *    `/view?...`，预览就永远停在占位状态。这里改成同步拼 `/view?...` 直接赋值，
 *    并用 `image.onerror` 依次回退候选地址。
 *
 * 2) 勾选「保存到工作流」会撑爆 localStorage 草稿配额
 *    原版把收到的图 `canvas.toDataURL()` 后写进 `image_data` 控件值，于是几 MB 的
 *    base64 跟着工作流进了 `widgets_values` → 再进 `Comfy.Workflow.Draft.*` 草稿
 *    → `QuotaExceededError` →「保存工作流草稿失败」刷屏。这里让 `image_data` 的
 *    value getter **恒返回空串**，改由 `widget.serializeValue` 在排队时才生成
 *    base64（新版前端 `graphToPrompt` 会 await 它，且它只影响 API 提示，不影响
 *    工作流 JSON）。
 *
 * 3) 画布卡顿
 *    控件值会被画进画布、还要进文本测量缓存，几 MB 的字符串每帧都在做重活；
 *    `node.imgs` 的 getter 又是每次重绘都会调用。所以：控件值不再是 base64
 *    （见 2），getter 只读一个闭包缓存、并且**只尝试恢复一次**（一次性标志）。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION_NAME = "xwide.image_sender_receiver";
const LOG_PREFIX = "[X-WIDE Image Sender/Receiver]";
const VERSION = "1.0.0";

const SENDER_CLASS = "XWIDE_ImageSender";
const RECEIVER_CLASS = "XWIDE_ImageReceiver";

const AUTHOR_NAME = "X-WIDE";
const AUTHOR_PAGE_URL = "https://space.bilibili.com/374064919";
const REPO_URL = "https://github.com/XWIDE/comfyui-xwide-image-sender-receiver";

const ORIGINAL_AUTHOR_NAME = "ltdrdata (Dr.Lt.Data)";
const ORIGINAL_AUTHOR_URL = "https://github.com/ltdrdata";
const ORIGINAL_PROJECT_URL = "https://github.com/ltdrdata/ComfyUI-Impact-Pack";

/** 扩展自己的资源目录（用于取 logo）：/extensions/comfyui-xwide-image-sender-receiver/ */
const EXTENSION_DIR = new URL(".", import.meta.url).href;

const IMAGE_DATA_SENTINEL = "[IMAGE DATA]";

/* ------------------------------------------------------------------ *
 *  双语
 * ------------------------------------------------------------------ */

function isEnglishUi() {
  const lang = String(navigator.language || navigator.userLanguage || "en").toLowerCase();
  return !lang.startsWith("zh");
}

/** 控件显示名：中文在前（界面语言为中文时更顺手），参数名保留在后面便于对照。 */
const WIDGET_LABELS = {
  [SENDER_CLASS]: {
    filename_prefix: "文件名前缀 / filename_prefix",
    link_id: "联动 ID / link_id",
  },
  [RECEIVER_CLASS]: {
    image: "图像 / image",
    link_id: "联动 ID / link_id",
    save_to_workflow: "保存到工作流 / save_to_workflow",
    image_data: "图像数据 / image_data",
    trigger_always: "总是触发 / trigger_always",
  },
};

/* ------------------------------------------------------------------ *
 *  工具
 * ------------------------------------------------------------------ */

function findWidget(node, name) {
  return (node?.widgets || []).find((widget) => widget?.name === name) || null;
}

function viewUrl(params) {
  // api.apiURL 在不同部署下会带上 /api 前缀，所以能用就用它。
  const base = typeof api?.apiURL === "function" ? api.apiURL("/view") : "/view";
  return base + params;
}

function viewParams(filename, type, subfolder) {
  return (
    `?filename=${encodeURIComponent(filename || "")}` +
    `&type=${encodeURIComponent(type || "temp")}` +
    `&subfolder=${encodeURIComponent(subfolder || "")}`
  );
}

/**
 * 解析 image 控件里的写法：`img.png [temp]`、`sub/img.png [temp]`、`img.png`，
 * 也兼容旧草稿里可能残留的 data:image base64。
 */
function parseImageValue(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  if (text.startsWith("data:image")) return { dataUrl: text };

  let type = "temp"; // 默认按临时目录找：收到的图都存在 temp 里
  let path = text;
  let explicitType = false;
  const match = text.match(/\[([^\]]+)\]\s*$/);
  if (match) {
    type = match[1].trim();
    path = text.slice(0, match.index).trim();
    explicitType = true;
  }

  const filename = path.split("/").pop();
  const subfolder = path.length > filename.length ? path.slice(0, path.length - filename.length - 1) : "";
  return { filename, subfolder, type, explicitType };
}

function logWarn(message, error) {
  console.warn(`${LOG_PREFIX} ${message}`, error);
}

/* ------------------------------------------------------------------ *
 *  Image Receiver：预览恢复 + 惰性 base64
 * ------------------------------------------------------------------ */

/** 每个接收节点一份状态。挂在节点上而不是模块级，多节点互不干扰。 */
function receiverState(node) {
  if (!node.__xwideReceiver) {
    node.__xwideReceiver = {
      imgs: [],
      restoreAttempted: false,
      liveImage: null,
      liveImageData: null,
      /** 旧草稿里残留的 base64（或用户手填的值），作为最后的回退。 */
      stored: "",
    };
  }
  return node.__xwideReceiver;
}

/** 把一批 Image 放进节点预览。resize 只在收到新图时允许，恢复时不要动用户调好的尺寸。 */
function applyImages(node, images, { resize = false } = {}) {
  const state = receiverState(node);
  const list = (Array.isArray(images) ? images : [images]).filter(Boolean);

  // 就地改写同一个数组：画布或其它代码可能已经持有 node.imgs 的引用，
  // 换成新数组会让它们拿到过期内容。
  if (!Array.isArray(state.imgs)) state.imgs = [];
  state.imgs.length = 0;
  state.imgs.push(...list);
  state.liveImage = state.imgs[0] || null;
  state.liveImageData = null; // 换了图，之前生成的 base64 作废
  node._img = state.imgs;

  if (resize && node?.size && node.size[1] < 200) {
    node.size[1] = 200;
  }

  try {
    // 新版前端用 canvas.setDirty()，老式 LiteGraph 用 node.setDirtyCanvas()，两个都调一次最稳。
    node.setDirtyCanvas?.(true, true);
    app.canvas?.setDirty(true);
  } catch (error) {
    /* 画布还没准备好时忽略 */
  }
}

/**
 * 从 image 控件里记录的路径恢复预览。
 * **只做一次**：`node.imgs` 的 getter 每次重绘都会被调用，如果每次都发请求、
 * 每次都重建 Image，画布就会卡死（这正是 v1 补丁的毛病）。
 */
function restorePreviewOnce(node, state) {
  if (state.restoreAttempted) return;

  const parsed = parseImageValue(findWidget(node, "image")?.value);
  if (!parsed) return; // 还没有收到过图，保持可重试

  state.restoreAttempted = true;

  const candidates = [];
  if (parsed.dataUrl) {
    candidates.push(parsed.dataUrl);
  } else {
    candidates.push(viewUrl(viewParams(parsed.filename, parsed.type, parsed.subfolder)));
    if (!parsed.explicitType) {
      // 控件里只有文件名（没有 [temp] 后缀）时可能是用户手动选的文件，再试 input 目录
      candidates.push(viewUrl(viewParams(parsed.filename, "input", parsed.subfolder)));
    }
  }

  if (state.stored?.startsWith("data:image")) {
    candidates.push(state.stored);
  }

  const tryNext = (index) => {
    if (index >= candidates.length) return;
    const src = candidates[index];
    const image = new Image();
    image.onload = () => applyImages(node, [image], { resize: false });
    image.onerror = () => tryNext(index + 1);
    image.src = src;
  };

  tryNext(0);
}

/** 主要给 Image Sender 的 img-send 用：收到新图后立刻显示。 */
function setReceivedImage(node, image, { resize = true } = {}) {
  applyImages(node, [image], { resize });
}

function patchReceiverWidgets(node) {
  const state = receiverState(node);
  const imageDataWidget = findWidget(node, "image_data");
  const saveWidget = findWidget(node, "save_to_workflow");
  const pathWidget = findWidget(node, "image");

  // 旧草稿（由未修复版本存下的）里 image_data 可能真的是 base64，读出来当回退源。
  const initial = typeof imageDataWidget?.value === "string" ? imageDataWidget.value : "";
  if (initial.startsWith("data:image")) state.stored = initial;
  if (imageDataWidget) imageDataWidget._value = state.stored;

  if (imageDataWidget && !imageDataWidget.__xwidePatched) {
    imageDataWidget.__xwidePatched = true;

    /*
     * value 恒为空：base64 不进 widgets_values → 不进工作流 JSON → 不进草稿。
     * setter 仍然把非哨兵值记进 state.stored，方便兼容旧草稿、以及用户手动粘贴。
     */
    Object.defineProperty(imageDataWidget, "value", {
      configurable: true,
      enumerable: true,
      get() {
        return "";
      },
      set(value) {
        if (typeof value === "string" && value && value !== IMAGE_DATA_SENTINEL) {
          state.stored = value;
          imageDataWidget._value = value;
        }
      },
    });

    /*
     * 排队时才生成 base64。新版前端 graphToPrompt 会 `await widget.serializeValue(...)`，
     * 而且这条路径**只影响 API 提示**，不碰 widgets_values —— 这正是我们想要的：
     * 后端拿得到图，工作流文件里却是空的。
     */
    imageDataWidget.serializeValue = function serializeValue() {
      if (!saveWidget?.value) return "";
      if (state.liveImageData) return state.liveImageData;

      const live = state.liveImage;
      if (live) {
        if (typeof live.src === "string" && live.src.startsWith("data:")) {
          state.liveImageData = live.src;
          return state.liveImageData;
        }
        try {
          const canvas = document.createElement("canvas");
          canvas.width = live.naturalWidth || live.width;
          canvas.height = live.naturalHeight || live.height;
          canvas.getContext("2d").drawImage(live, 0, 0);
          state.liveImageData = canvas.toDataURL("image/png");
          return state.liveImageData;
        } catch (error) {
          logWarn("failed to encode the received image", error);
        }
      }

      return state.stored || "";
    };
  }

  // 收到的临时文件不在下拉列表里，补进去让控件显示得正常些（只影响外观）。
  if (pathWidget && !pathWidget.__xwidePatched) {
    pathWidget.__xwidePatched = true;
    const originalCallback = pathWidget.callback;
    pathWidget.callback = function patchedCallback(...args) {
      state.restoreAttempted = true; // 用户自己选的图，不用再去恢复
      state.imgs.length = 0;
      state.liveImage = null;
      state.liveImageData = null;
      return originalCallback?.apply(this, args);
    };
  }

  // 预览缓存：getter 只读闭包变量，绝不在重绘路径上做重活。
  if (!node.__xwideImgsPatched) {
    node.__xwideImgsPatched = true;
    Object.defineProperty(node, "imgs", {
      configurable: true,
      enumerable: true,
      get() {
        if (!state.imgs.length) restorePreviewOnce(node, state);
        return state.imgs;
      },
      set(value) {
        // 同样就地改写，保证 node.imgs 的引用在整个生命周期里稳定
        const next = Array.isArray(value) ? value.filter(Boolean) : [];
        if (!Array.isArray(state.imgs)) state.imgs = [];
        state.imgs.length = 0;
        state.imgs.push(...next);
      },
    });
  }
}

/* ------------------------------------------------------------------ *
 *  收发：img-send
 * ------------------------------------------------------------------ */

function imgSendHandler(event) {
  const detail = event?.detail || {};
  const images = Array.isArray(detail.images) ? detail.images : [];
  const first = images[0];

  if (!first?.filename) return;

  const nodes = app?.graph?._nodes || [];
  for (const node of nodes) {
    if (node?.type !== RECEIVER_CLASS) continue;

    const linkWidget = findWidget(node, "link_id");
    if (String(linkWidget?.value ?? "") !== String(detail.link_id ?? "")) continue;

    const pathWidget = findWidget(node, "image");
    if (!pathWidget) continue;

    const subfolder = first.subfolder || "";
    const value = `${subfolder ? `${subfolder}/` : ""}${first.filename} [${first.type}]`;

    const values = pathWidget.options?.values;
    if (Array.isArray(values) && !values.includes(value)) values.push(value);
    pathWidget.value = value;

    const state = receiverState(node);
    state.restoreAttempted = true; // 已经拿到新图，不需要走恢复流程

    const image = new Image();
    image.onload = () => setReceivedImage(node, image);
    image.onerror = () => logWarn(`failed to load the received image: ${value}`);
    image.src = viewUrl(viewParams(first.filename, first.type, subfolder));
  }

  try {
    app.canvas?.setDirty(true);
  } catch (error) {
    /* ignore */
  }
}

/* ------------------------------------------------------------------ *
 *  「信息 / About」窗口
 * ------------------------------------------------------------------ */

let aboutDialog = null;

function installInfoStyle() {
  if (document.getElementById("xwide-info-style")) return;
  const style = document.createElement("style");
  style.id = "xwide-info-style";
  style.textContent = `
.xwide-info-backdrop{position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55);}
.xwide-info-box{width:min(760px,92vw);max-height:86vh;display:flex;flex-direction:column;background:#23222a;color:#e8e8ea;border:1px solid #4a4a55;border-radius:12px;box-shadow:0 18px 48px rgba(0,0,0,.55);font-family:system-ui,"Segoe UI","Microsoft YaHei",sans-serif;font-size:15px;}
.xwide-info-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid #3a3a44;}
.xwide-info-title{font-size:17px;font-weight:600;color:#f0c674;}
.xwide-info-body{padding:16px 18px;overflow-y:auto;display:flex;flex-direction:column;gap:14px;line-height:1.65;}
.xwide-info-foot{display:flex;justify-content:flex-end;padding:12px 18px;border-top:1px solid #3a3a44;}
.xwide-close{background:#3a3a46;color:#eee;border:1px solid #55555f;border-radius:8px;padding:6px 20px;cursor:pointer;font-size:15px;}
.xwide-close:hover{background:#4a4a58;}
.xwide-section-title{font-size:15px;font-weight:600;color:#f0c674;margin:0;padding-bottom:6px;border-bottom:1px solid #3a3a44;}
.xwide-card{display:flex;gap:12px;background:#1c1b22;border:1px solid #3a3a44;border-radius:10px;padding:12px 14px;}
.xwide-logo{width:56px;height:56px;border-radius:10px;object-fit:contain;background:#fff;}
.xwide-avatar{width:56px;height:56px;border-radius:10px;background:#2f4a6b;color:#dfe9f5;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;letter-spacing:.5px;}
.xwide-card-title{font-size:15px;font-weight:600;color:#eaeaea;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.xwide-chip{font-size:12px;font-weight:400;color:#9ad4a0;border:1px solid #4d7a52;border-radius:999px;padding:1px 8px;}
.xwide-chip.orig{color:#9db8d8;border-color:#4a6180;}
.xwide-card-desc{margin:6px 0 8px;color:#c2c2c8;font-size:14px;}
.xwide-links{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px;}
.xwide-links a{color:#6fb3ff;text-decoration:none;}
.xwide-links a:hover{text-decoration:underline;}
.xwide-url{color:#6b7079;font-size:13px;word-break:break-all;}
.xwide-list{margin:0;padding-left:20px;color:#c2c2c8;font-size:14px;}
.xwide-list li{margin:4px 0;}
.xwide-note{color:#8f929a;font-size:13px;}
`;
  document.head.appendChild(style);
}

function buildAboutBody() {
  const zh = !isEnglishUi();
  const tr = (cn, en) => (zh ? cn : en);

  return `
  <p class="xwide-card-desc" style="margin:0;">
    ${tr(
      `本版本把原作者 ltdrdata 的 Image Sender / Image Receiver <b>独立重写</b>为 X-WIDE 版：<b>只优化界面显示、修复 BUG，没有新增功能</b>，也不需要安装 Impact Pack。`,
      `This version is an independent X-WIDE rewrite of the original Image Sender / Image Receiver by ltdrdata: it <b>only improves the UI and fixes bugs</b> — no new features, and no Impact Pack installation required.`
    )}
  </p>

  <h3 class="xwide-section-title">${tr("作者 / Authors", "Authors / 作者")}</h3>

  <div class="xwide-card">
    <img class="xwide-logo" src="${EXTENSION_DIR}logo_xwide.png" alt="X-WIDE" />
    <div>
      <div class="xwide-card-title">
        ${AUTHOR_NAME}
        <span class="xwide-chip">${tr("本版本 / This version", "This version / 本版本")}</span>
      </div>
      <p class="xwide-card-desc">
        ${tr(
          "独立封装 + 中英双语界面 + 修复原节点的三个问题（切换工作流后预览失效、保存到工作流撑爆草稿配额、大图卡顿）。遵循 GPL-3.0 继续开源。",
          "Independent packaging, bilingual UI, and fixes for three issues of the original nodes (preview lost after switching workflows, draft quota blown by save-to-workflow, lag with large images). Kept open source under GPL-3.0."
        )}
      </p>
      <div class="xwide-links">
        <a href="${AUTHOR_PAGE_URL}" target="_blank" rel="noopener noreferrer">${tr("打开作者主页 / Author Page", "Author Page / 打开作者主页")} &#8599;</a>
        <a href="${REPO_URL}" target="_blank" rel="noopener noreferrer">${tr("开源项目首页 / GitHub", "GitHub / 开源项目首页")} &#8599;</a>
        <span class="xwide-url">${REPO_URL}</span>
      </div>
    </div>
  </div>

  <div class="xwide-card">
    <div class="xwide-avatar">lt</div>
    <div>
      <div class="xwide-card-title">
        ${ORIGINAL_AUTHOR_NAME}
        <span class="xwide-chip orig">${tr("原作者 / Original author", "Original author / 原作者")}</span>
      </div>
      <p class="xwide-card-desc">
        ${tr(
          "原节点 Image Sender / Image Receiver 由 ltdrdata（Dr.Lt.Data）在 ComfyUI-Impact-Pack 中开发，版权归原作者所有。本项目的收发协议与之一致（img-send 事件），两个包的节点可以混用。",
          "The original Image Sender / Image Receiver nodes were created by ltdrdata (Dr.Lt.Data) in ComfyUI-Impact-Pack; copyright belongs to the original author. This project keeps the same protocol (the img-send event), so nodes from both packs can be mixed."
        )}
      </p>
      <div class="xwide-links">
        <a href="${ORIGINAL_AUTHOR_URL}" target="_blank" rel="noopener noreferrer">${tr("打开原作者主页 / Author Page", "Original author page / 打开原作者主页")} &#8599;</a>
        <a href="${ORIGINAL_PROJECT_URL}" target="_blank" rel="noopener noreferrer">${tr("查看原项目 / View Original", "View Original / 查看原项目")} &#8599;</a>
        <span class="xwide-url">${ORIGINAL_PROJECT_URL}</span>
      </div>
    </div>
  </div>

  <h3 class="xwide-section-title">${tr("本版本的改动 / Changes in this version", "Changes in this version / 本版本的改动")}</h3>
  <ul class="xwide-list">
    <li>${tr(
      "修复：切换工作流再切回来，收到的图不再失效（预览会从临时文件恢复）。",
      "Fix: received images no longer break after switching workflows back and forth (the preview is restored from the temp file)."
    )}</li>
    <li>${tr(
      "修复：勾选「保存到工作流」不再把几 MB 的 base64 写进工作流草稿 —— 不会再弹「保存工作流草稿失败」，画布也不再因此卡顿。",
      "Fix: “save_to_workflow” no longer inlines megabytes of base64 into the workflow draft — no more “failed to save draft” errors, and no more canvas lag caused by it."
    )}</li>
    <li>${tr(
      "界面：控件名与提示中英双语，节点归入 X-WIDE 分类，搜索支持 xwide / sender / receiver / 图像发送 / 图像接收 等别名。",
      "UI: bilingual widget labels and tooltips, an X-WIDE category, and search aliases such as xwide / sender / receiver."
    )}</li>
    <li>${tr(
      "兼容：沿用原版的 img-send 协议，可与 Impact Pack 的收发节点互相配对。",
      "Compatible: reuses the original img-send protocol, so it can pair with Impact Pack's sender/receiver nodes."
    )}</li>
  </ul>
  <p class="xwide-note">
    ${tr(
      "注意：收到的图存放在临时目录，ComfyUI 重启后 temp 会被清空，需要重新发送一次。",
      "Note: received images live in the temp folder. Restarting ComfyUI clears it, so send the image again after a restart."
    )}
  </p>

  <h3 class="xwide-section-title">${tr("许可 / License", "License / 许可")}</h3>
  <p class="xwide-card-desc" style="margin:0;">
    GPL-3.0 &middot;
    ${tr(
      "原项目版权归 ltdrdata 所有；本修改版本的修改部分版权归 X-WIDE 所有，同样以 GPL-3.0 授权。详见 NOTICE 与 CHANGELOG.md。",
      "The original project is copyright ltdrdata; the modifications in this version are copyright X-WIDE and licensed under GPL-3.0 as well. See NOTICE and CHANGELOG.md."
    )}
  </p>
  `;
}

function closeAboutDialog() {
  document.removeEventListener("keydown", onAboutKeyDown);
  try {
    aboutDialog?.remove();
  } catch (error) {
    /* 已经不在文档里了 */
  }
  aboutDialog = null;
}

function onAboutKeyDown(event) {
  if (event.key === "Escape") closeAboutDialog();
}

function showAboutDialog() {
  closeAboutDialog();
  installInfoStyle();

  const zh = !isEnglishUi();
  const tr = (cn, en) => (zh ? cn : en);

  const backdrop = document.createElement("div");
  backdrop.className = "xwide-info-backdrop";
  backdrop.addEventListener("pointerdown", (event) => {
    if (event.target === backdrop) closeAboutDialog();
  });

  backdrop.innerHTML = `
    <div class="xwide-info-box" role="dialog" aria-modal="true">
      <div class="xwide-info-head">
        <div class="xwide-info-title">X-WIDE Image Sender / Receiver &nbsp;v${VERSION}</div>
        <button class="xwide-close" type="button">${tr("关闭 / Close", "Close / 关闭")}</button>
      </div>
      <div class="xwide-info-body">${buildAboutBody()}</div>
      <div class="xwide-info-foot">
        <button class="xwide-close" type="button">${tr("关闭 / Close", "Close / 关闭")}</button>
      </div>
    </div>
  `;

  for (const button of backdrop.querySelectorAll(".xwide-close")) {
    button.addEventListener("click", closeAboutDialog);
  }

  document.body.appendChild(backdrop);
  document.addEventListener("keydown", onAboutKeyDown);
  aboutDialog = backdrop;
}

/* ------------------------------------------------------------------ *
 *  右键菜单
 * ------------------------------------------------------------------ */

function appendAboutItems(options) {
  if (!Array.isArray(options)) return options;
  try {
    options.push(
      { content: "ℹ 信息 / About", callback: () => showAboutDialog() },
      {
        content: "ℹ 打开作者主页 / Author Page",
        callback: () => window.open(AUTHOR_PAGE_URL, "_blank", "noopener,noreferrer"),
      },
      {
        content: "ℹ 开源项目首页 / GitHub",
        callback: () => window.open(REPO_URL, "_blank", "noopener,noreferrer"),
      }
    );
  } catch (error) {
    logWarn("failed to add the about menu items", error);
  }
  return options;
}

/** 画布右键菜单（用户选的入口）。新版前端仍会调用 LGraphCanvas.getCanvasMenuOptions。 */
function patchCanvasMenu() {
  const proto =
    globalThis?.LGraphCanvas?.prototype ||
    globalThis?.LiteGraph?.LGraphCanvas?.prototype ||
    app?.canvas?.constructor?.prototype;

  if (!proto || proto.__xwideAboutMenu || typeof proto.getCanvasMenuOptions !== "function") return;

  const original = proto.getCanvasMenuOptions;
  proto.getCanvasMenuOptions = function xwideCanvasMenuOptions(...args) {
    const options = original.apply(this, args) || [];
    options.push(null); // 分隔线
    appendAboutItems(options);
    return options;
  };
  proto.__xwideAboutMenu = true;
}

/** 节点右键菜单：画布缩放 / 节点被挪出屏幕时也能点得到，作为保底入口。 */
function patchNodeMenu(nodeType) {
  const original = nodeType.prototype.getExtraMenuOptions;
  nodeType.prototype.getExtraMenuOptions = function xwideExtraMenuOptions(...args) {
    const result = original?.apply(this, args);
    appendAboutItems(args?.[1]);
    return result;
  };
}

/* ------------------------------------------------------------------ *
 *  注册
 * ------------------------------------------------------------------ */

app.registerExtension({
  name: EXTENSION_NAME,

  async setup() {
    api.addEventListener("img-send", imgSendHandler);
    patchCanvasMenu();
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const className = nodeData?.name;
    if (className !== SENDER_CLASS && className !== RECEIVER_CLASS) return;

    // 双语控件名（前端渲染时读 widget.label || widget.name）
    const labels = WIDGET_LABELS[className] || {};
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function xwideNodeCreated(...args) {
      const result = onNodeCreated?.apply(this, args);
      try {
        for (const widget of this.widgets || []) {
          const label = labels[widget.name];
          if (label) widget.label = label;
        }
        if (className === RECEIVER_CLASS) patchReceiverWidgets(this);
      } catch (error) {
        logWarn("node setup failed", error);
      }
      return result;
    };

    patchNodeMenu(nodeType);
  },
});

console.log(`${LOG_PREFIX} v${VERSION} loaded`);
