# X-WIDE Image / Latent Sender & Receiver

**English** | [中文](README.md)

Send things from one place on the canvas to another — four nodes:

- **Images**: **`X-WIDE Image Sender`** sends → **`X-WIDE Image Receiver`** receives, outputting `IMAGE` / `MASK`;
- **Latents**: **`X-WIDE Latent Sender`** sends → **`X-WIDE Latent Receiver`** receives, outputting `LATENT` (the latent itself travels, saving a decode-then-re-encode round trip).

This package is an independent repackaging of the `Image Sender` / `Image Receiver` / `Latent Sender` / `Latent Receiver` nodes from [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) by **ltdrdata (Dr.Lt.Data)**, maintained by **X-WIDE**:

> It **only improves the UI (bilingual) and fixes bugs — no new features**, and it does **not** require Impact Pack to be installed.

Current version: **1.1.0** (adds the latent pair) — see [CHANGELOG.md](CHANGELOG.md).

The transfer protocol is identical to the original (`img-send` / `latent-send` events, `name.png [temp]` widget format), so it can be mixed with Impact Pack's sender/receiver nodes, and existing workflows can be migrated the same way.

---

## What was fixed

| # | Problem (original) | Cause | Current behaviour |
| --- | --- | --- | --- |
| 1 | **The received image stopped working after switching workflows and back** | The front-end `node.imgs` getter used `api.fetchApi(...).then(r => r)` — an identity mapping — so `res.status` was always `undefined` and `image.src` was never rewritten to `/view?...` | `image.src` is built synchronously as `/view?filename=…&type=temp&subfolder=…`, with ordered fallbacks (temp file → input folder → base64 left in older drafts) |
| 2 | **"Failed to save workflow draft" toast spam when `save_to_workflow` was enabled** | The received image was `canvas.toDataURL()`-ed into the `image_data` widget, so megabytes of base64 went into `widgets_values` → the workflow and the localStorage draft → `QuotaExceededError` | `image_data`'s value is always an empty string; base64 never reaches the workflow or the draft. It is generated on demand by `widget.serializeValue` at queue time and injected only into the API prompt |
| 3 | **Large images made the whole canvas lag** | Widget values are drawn on the canvas and fed into the text-measurement cache, and the `node.imgs` getter runs on every repaint | Widget values no longer carry base64; `node.imgs` reads a single cache and preview restoration is attempted **only once** |
| 4 | **A missing image file crashed the node** | `doit` called `LoadImage().load_image()` directly, which raises once the temp file is gone | A fallback reader is used: on failure it logs a warning and returns a 64×64 placeholder instead of breaking the workflow |
| 5 | **A missing latent file (temp cleared by a restart) turned the node red** | The original `LatentReceiver` rejected non-existent files in `VALIDATE_INPUTS` | Only absolute paths and `..` are rejected; a missing file logs a warning and falls back to an empty latent (`1×4×8×8`) |
| 6 | **The original `LatentReceiver` returned a bare tensor when its input was missing** | It returned `torch.zeros([1,4,8,8])` instead of `{"samples": …}`, so downstream got the wrong type | Always returns a valid `LATENT` |

![The error before the fix](docs/images/draft-save-error.png)

---

## Installation

**Option 1 — ComfyUI Manager (recommended)**

1. Open Manager → **Install via Git URL**;
2. Enter `https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver`;
3. Restart ComfyUI and refresh the page (`Ctrl` + `F5`).

**Option 2 — manual**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver
```

No extra dependencies: only ComfyUI's bundled `torch` / `numpy` / `Pillow` and the front-end API are used.

---

## Usage

1. Add an **X-WIDE Image Sender** and connect your image to its `images` input;
2. Add an **X-WIDE Image Receiver** and wire its `image` output downstream;
3. Give both nodes the **same `link_id`** (both default to `0`).

> `link_id` can also be converted to an input and driven by a `Primitive` / `ImpactInt` node
> (same as the original). Once converted it counts as "linked" and the Receiver accepts the image.

| Node | Widget | Description |
| --- | --- | --- |
| X-WIDE Image Sender | `images` | Image(s) to send |
| | `filename_prefix` | Filename prefix used in the temp folder (default `ImgSender`) |
| | `link_id` | Pairing id — only a Receiver with the same id receives the image |
| X-WIDE Image Receiver | `image` | Filled automatically with the received temp filename; you can also pick a file from the input folder |
| | `link_id` | Pairing id |
| | `save_to_workflow` | When enabled the received image is injected into the queued prompt. The **workflow file itself is not inlined with base64** |
| | `image_data` | Image data, generated on demand by the front end; normally empty |
| | `trigger_always` | Always re-execute this node (ignore the cache) |

### Two modes

- **`save_to_workflow` off**: the Receiver loads the **temp file** recorded in the `image` widget, so the image must still exist in `ComfyUI/temp`. The preview is still restored after switching workflows and back.
- **`save_to_workflow` on**: at queue time the front end encodes the received image to base64 and injects it into the prompt's `image_data`, so execution no longer depends on the temp file — while the workflow and the draft stay small.

> ⚠️ In both modes the image itself lives in `ComfyUI/temp`. **Restarting ComfyUI clears that folder**, so send the image again afterwards. If you need an image to be permanently stored in a workflow, use `Load Image` / `Save Image` style nodes.

### The latent pair (since v1.1.0)

Same usage as the image pair, but the `LATENT` itself travels:

1. Add an **X-WIDE Latent Sender** and connect your `LATENT` to its `samples` input;
2. Add an **X-WIDE Latent Receiver** and wire its `latent` output to `KSampler` / `VAEDecode` and so on;
3. Give both nodes the **same `link_id`** (both default to `0`).

| Node | Widget | Description |
| --- | --- | --- |
| X-WIDE Latent Sender | `samples` | The latent to send |
| | `filename_prefix` | Filename prefix used in the temp folder (default `latents/LatentSender`) |
| | `link_id` | Pairing id |
| | `preview_method` | How the preview image is decoded (Latent2RGB-SDXL / SD15 / FLUX.1 … — the first 13 entries are item-for-item identical to the original, plus Qwen-Image / HunyuanImage / Flux.2 / Wan2.1 / Wan2.2 / MingImage; it affects only the preview) |
| X-WIDE Latent Receiver | `latent` | Filled automatically with the received temp filename; you can also pick a `.latent` / `.latent.png` from the input folder |
| | `link_id` | Pairing id |
| | `trigger_always` | Always re-execute this node (ignore the cache) |

- The sender writes `<prefix>_<counter>_.latent.png`: a Latent2RGB preview with the latent packed into its EXIF (exactly like the original), which the receiver reads back unchanged.
- The preview format is **matched automatically to the latent's channel count**: when the selected format and the latent do not fit (typically a 64-channel Qwen-Image latent with the 4-channel SDXL default) it switches to a suitable format and says so in the log, so new models such as Qwen-Image and HunyuanImage get a preview as well. If nothing fits, the thumbnail is a placeholder but the file is still a `.latent.png` and the latent is transferred normally.
- These files also live in `ComfyUI/temp` and **are cleared on restart**, so send again afterwards; the Receiver does not turn red in that case — it outputs an empty latent and logs a warning.
- The preview needs `piexif` and serialisation needs `safetensors` (both usually present in a ComfyUI install). Without `piexif` the sender falls back to a plain `.latent` file: transfer still works, the receiver just has no thumbnail.

### "About" page

Right-click the **empty canvas** or a **node** and choose `ℹ 信息 / About`: it credits the author of this version (X-WIDE) and the original author (ltdrdata), with clickable links to both home pages, and states that this version only improves the UI and fixes bugs.

---

## Bilingual UI

The interface follows the browser language:

- Chinese: `图像 / image`, `保存到工作流 / save_to_workflow`, …
- English: the same "中文 / parameter" pairing, so the original tutorials still apply.

Node display names are `X-WIDE Image Sender 图像发送器`, `X-WIDE Image Receiver 图像接收器`, `X-WIDE Latent Sender 潜空间发送器` and `X-WIDE Latent Receiver 潜空间接收器`; searching for `xwide`, `x-wide`, `sender`, `receiver`, `latent`, `图像发送`, `图像接收`, `潜空间发送` or `潜空间接收` all work. The categories are `X-WIDE/Image` and `X-WIDE/Latent`.

---

## Relationship to Impact Pack

- This package does **not** depend on Impact Pack and can be installed on its own;
- Both packages **can be installed together**: because the protocol matches (`img-send` / `latent-send` and the `name.png [temp]` format), the X-WIDE Sender can feed an original Receiver and vice versa;
- Node type names differ (`ImageSender` ↔ `XWIDE_ImageSender`, `LatentSender` ↔ `XWIDE_LatentSender`), so both can live on the same canvas without overwriting each other.

## License and credits

- Licensed under **GPL-3.0**, see [LICENSE](LICENSE);
- The original `Image Sender` / `Image Receiver` / `Latent Sender` / `Latent Receiver` nodes were created by **ltdrdata (Dr.Lt.Data)** in ComfyUI-Impact-Pack; copyright belongs to the original author;
- The modifications in this version are copyright **X-WIDE**. See [NOTICE](NOTICE) and [CHANGELOG.md](CHANGELOG.md) for the change list and the GPL-3.0 obligations.

Original author: <https://github.com/ltdrdata> · Original project: <https://github.com/ltdrdata/ComfyUI-Impact-Pack>

## Links

- Author page: <https://space.bilibili.com/374064919>
- Issues: <https://github.com/XWIDE/comfyui-x-wide-image-sender-receiver/issues>
