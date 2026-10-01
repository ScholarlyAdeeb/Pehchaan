"""
Train the document region detector (Faster R-CNN, ResNet-50 FPN) on the
generated ID cards, on the GPU, with a live dashboard.

Labels are exact: the card generator records the box of every value it
prints (``text_regions``) plus the portrait / QR / barcode holders. Ghost
photos are a security feature, not the portrait, so they are not labelled.

The split is by *person*: every card of a held-out person (their Aadhaar, PAN,
DL and passport) is unseen in training, so the scores measure layouts and
faces the model has not memorised.

Usage (from backend/):
    .venv\\Scripts\\python training\\train_region_detector.py [--epochs 14] [--batch 4] [--port 8766]
Outputs:
    models/localization/region_detector.pt      best checkpoint (weights + classes + architecture)
    training/region_detector_metrics.json       per-class AP50 / recall on held-out people
"""
from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DATA = HERE / "data_generated"
OUT_MODEL = BACKEND / "models" / "localization" / "region_detector.pt"
OUT_METRICS = HERE / "region_detector_metrics.json"
PREVIEW = HERE / ".region_preview.jpg"
SEED = 26188

# Index order extends app/modules/localization/detector.py REGION_CLASSES so old ids keep their meaning.
CLASSES = [
    "background", "photo", "name", "surname", "date_of_birth", "date_of_issue", "date_of_expiry",
    "document_number", "nationality", "mrz", "signature", "stamp",
    "address", "guardian_name", "place_of_birth", "gender", "qr_code", "barcode",
]
FIELD_CLASSES = {
    "aadhaar": {"Aadhaar_Name": "name", "Aadhaar_DOB": "date_of_birth", "Aadhaar_Number": "document_number",
                "Aadhaar_Address": "address", "Aadhaar_Gender": "gender"},
    "pan": {"PAN_Name": "name", "PAN_Father_Name": "guardian_name", "PAN_DOB": "date_of_birth",
            "PAN_Number": "document_number"},
    "driving_license": {"Name": "name", "S_D_W": "guardian_name", "DOB": "date_of_birth", "DL_Number": "document_number",
                        "Date_Of_Issue": "date_of_issue", "Validity_NT": "date_of_expiry", "Address": "address"},
    "passport": {"Passport_Surname": "surname", "Passport_Given_Name": "name", "Passport_DOB": "date_of_birth",
                 "Passport_Number": "document_number", "Passport_Date_Of_Issue": "date_of_issue",
                 "Passport_Date_Of_Expiry": "date_of_expiry", "Passport_Place_Of_Birth": "place_of_birth",
                 "Passport_Father_Name": "guardian_name", "Passport_Address": "address",
                 "Passport_Country_Code": "nationality", "Passport_Sex": "gender",
                 "Passport_MRZ_Line_1": "mrz", "Passport_MRZ_Line_2": "mrz"},
}
KIND_CLASSES = {"photo": "photo", "qr": "qr_code", "barcode": "barcode"}

# Text fields are long and thin (MRZ ~40:1); the stock 0.5-2 aspect anchors miss them.
ANCHOR_SIZES = ((32,), (64,), (128,), (256,), (512,))
ANCHOR_RATIOS = (0.1, 0.25, 0.5, 1.0, 2.0)  # height / width
TRAIN_MIN_SIZES = (896, 960, 1024, 1088)
EVAL_MIN_SIZE = 1024
MAX_SIZE = 1600


# --------------------------------------------------------------------------- data
def build_index():
    samples = []
    for ann_path in sorted((DATA / "annotations").glob("*/*.json")):
        ann = json.loads(ann_path.read_text(encoding="utf-8"))
        doc = ann["document_type"]
        img = DATA / ann_path.parent.name / ann["file"]
        if doc not in FIELD_CLASSES or not img.is_file():
            continue
        w, h = ann["image_width"], ann["image_height"]
        boxes, labels = [], []

        def add(bb, cls):
            x0, y0 = max(0, bb["x"] - 2), max(0, bb["y"] - 2)
            x1, y1 = min(w, bb["x"] + bb["w"] + 2), min(h, bb["y"] + bb["h"] + 2)
            if x1 - x0 >= 3 and y1 - y0 >= 3:
                boxes.append([x0, y0, x1, y1])
                labels.append(CLASSES.index(cls))

        for r in ann.get("text_regions", []):
            cls = FIELD_CLASSES[doc].get(r["field"])
            if cls:
                add(r["bbox"], cls)
        for r in ann["regions"]:
            cls = KIND_CLASSES.get(r["kind"])
            if cls:
                add(r["bbox"], cls)
        samples.append({"image": str(img), "doc_type": doc, "person": int(ann["serial_number"]),
                        "boxes": boxes, "labels": labels})
    return samples


def split_by_person(samples, val_fraction=0.2):
    people = sorted({s["person"] for s in samples})
    random.Random(SEED).shuffle(people)
    val_people = set(people[: round(len(people) * val_fraction)])
    return ([s for s in samples if s["person"] not in val_people],
            [s for s in samples if s["person"] in val_people], sorted(val_people))


def place_on_background(img, boxes, rng):
    """Simulate a photographed card: scale, shift, slight tilt and perspective
    skew onto a random desk-like background. Box corners go through the same
    homography, and the new box is their axis-aligned hull (tilt is kept small
    so hulls of long text lines stay tight)."""
    h, w = img.shape[:2]
    pad = rng.uniform(0.05, 0.3)
    W, H = int(w * (1 + pad)), int(h * (1 + pad))
    k = rng.uniform(0.75, 1.0)                                  # card size within the frame
    cw, ch = w * k, h * k
    ox, oy = rng.uniform(0, W - cw), rng.uniform(0, H - ch)
    dst = np.array([[ox, oy], [ox + cw, oy], [ox + cw, oy + ch], [ox, oy + ch]], np.float32)
    dst += rng.uniform(-0.035, 0.035, dst.shape).astype(np.float32) * np.array([cw, ch], np.float32)  # perspective
    ang = np.deg2rad(rng.uniform(-4, 4))
    c = dst.mean(axis=0)
    rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]], np.float32)
    dst = (dst - c) @ rot.T + c
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    M = cv2.getPerspectiveTransform(src, dst)

    bg = np.empty((H, W, 3), np.float32)
    bg[:] = rng.uniform(30, 225, 3)
    gy, gx = np.mgrid[0:H, 0:W].astype(np.float32)
    bg += (gx / W * rng.uniform(-40, 40) + gy / H * rng.uniform(-40, 40))[..., None]  # uneven lighting
    bg += rng.normal(0, rng.uniform(3, 12), (H, W, 1))
    bg = np.clip(bg, 0, 255).astype(np.uint8)
    card = cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    out = np.where(mask[..., None] > 127, card, bg)

    new = []
    for x0, y0, x1, y1 in boxes:
        pts = cv2.perspectiveTransform(np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], np.float32), M)[0]
        new.append([max(0.0, float(pts[:, 0].min())), max(0.0, float(pts[:, 1].min())),
                    min(float(W), float(pts[:, 0].max())), min(float(H), float(pts[:, 1].max()))])
    return out, new


class Cards(Dataset):
    """mode: "train" (random photometric + geometric), "clean" (as generated),
    "distorted" (fixed per-card photo-style distortion, the same on every epoch)."""

    def __init__(self, samples, mode: str, geometric_p: float = 0.7):
        self.samples, self.mode, self.geometric_p = samples, mode, geometric_p

    def __len__(self):
        return len(self.samples)

    def _augment(self, img, rng):
        # photometric; text is never mirrored
        alpha, beta = rng.uniform(0.75, 1.25), rng.uniform(-25, 25)
        img = np.clip(img.astype(np.float32) * alpha + beta, 0, 255)
        if rng.random() < 0.3:  # colour cast, like a warm or cold camera
            img *= rng.uniform(0.9, 1.1, size=3)
        if rng.random() < 0.3:
            img += rng.normal(0, rng.uniform(2, 8), img.shape)
        img = np.clip(img, 0, 255).astype(np.uint8)
        if rng.random() < 0.3:
            img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 1.4))
        if rng.random() < 0.4:
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(35, 85))])
            img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
        if rng.random() < 0.15:
            img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        return img

    def __getitem__(self, i):
        s = self.samples[i]
        img = cv2.imread(s["image"], cv2.IMREAD_COLOR)
        boxes = s["boxes"]
        if self.mode != "clean":
            rng = np.random.default_rng() if self.mode == "train" else np.random.default_rng(SEED * 1000 + i)
            if self.mode == "distorted" or rng.random() < self.geometric_p:
                img, boxes = place_on_background(img, boxes, rng)
            img = self._augment(img, rng)
        t = torch.from_numpy(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float() / 255.0
        target = {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
                  "labels": torch.tensor(s["labels"], dtype=torch.int64)}
        return t, target, i


def collate(batch):
    return tuple(zip(*batch))


# --------------------------------------------------------------------------- model
def build_model(pretrained: bool = True):
    from torchvision.models.detection import fasterrcnn_resnet50_fpn
    from torchvision.models.detection.anchor_utils import AnchorGenerator
    from torchvision.models.detection.rpn import RPNHead

    anchors = AnchorGenerator(ANCHOR_SIZES, (ANCHOR_RATIOS,) * len(ANCHOR_SIZES))
    model = fasterrcnn_resnet50_fpn(
        weights=None, weights_backbone=None, num_classes=len(CLASSES),
        rpn_anchor_generator=anchors, rpn_head=RPNHead(256, len(ANCHOR_RATIOS)),
        min_size=TRAIN_MIN_SIZES, max_size=MAX_SIZE, box_detections_per_img=100,
    )
    if pretrained:
        from torchvision.models.detection import FasterRCNN_ResNet50_FPN_Weights

        coco = FasterRCNN_ResNet50_FPN_Weights.COCO_V1.get_state_dict(progress=False)
        own = model.state_dict()
        keep = {k: v for k, v in coco.items() if k in own and own[k].shape == v.shape}
        model.load_state_dict(keep, strict=False)
        return model, len(keep), len(own)
    return model, 0, 0


# --------------------------------------------------------------------------- metrics
def iou_matrix(a, b):
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x0 = np.maximum(a[:, None, 0], b[None, :, 0]); y0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2]); y1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    area = lambda z: (z[:, 2] - z[:, 0]) * (z[:, 3] - z[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def average_precision(dets, n_gt):
    """VOC all-point AP from (score, is_true_positive) pairs."""
    if n_gt == 0:
        return None
    if not dets:
        return 0.0
    dets.sort(key=lambda d: -d[0])
    tp = np.cumsum([d[1] for d in dets]); fp = np.cumsum([1 - d[1] for d in dets])
    rec, prec = tp / n_gt, tp / np.maximum(tp + fp, 1e-9)
    mrec = np.concatenate([[0], rec, [1]]); mpre = np.concatenate([[0], prec, [0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


@torch.no_grad()
def evaluate(model, loader, device, samples, iou_thr=0.5, score_thr=0.5, on_batch=None):
    model.eval()
    model.transform.min_size = (EVAL_MIN_SIZE,)
    dets = defaultdict(list)                      # class -> [(score, tp@0.5)]
    dets75 = defaultdict(list)                    # class -> [(score, tp@0.75)]: tight enough to crop for OCR
    best_iou = defaultdict(list)                  # class -> IoU of the best-scoring box per ground truth
    n_gt = defaultdict(int)
    hit = defaultdict(lambda: [0, 0])             # (doc, class) -> [found at score_thr, total]
    for images, targets, idxs in loader:
        with torch.autocast("cuda", enabled=device.type == "cuda"):
            outs = model([im.to(device, non_blocking=True) for im in images])
        for out, tgt, i in zip(outs, targets, idxs):
            doc = samples[i]["doc_type"]
            pb, ps, pl = out["boxes"].float().cpu().numpy(), out["scores"].float().cpu().numpy(), out["labels"].cpu().numpy()
            gb, gl = tgt["boxes"].numpy(), tgt["labels"].numpy()
            for c in set(gl.tolist()) | set(pl.tolist()):
                g, p = gb[gl == c], pb[pl == c]
                s = ps[pl == c]
                n_gt[c] += len(g)
                ious = iou_matrix(p, g)
                for thr, store in ((iou_thr, dets), (0.75, dets75)):
                    used = np.zeros(len(g), bool)
                    for k in np.argsort(-s):
                        j = int(np.argmax(ious[k])) if len(g) else -1
                        ok = j >= 0 and ious[k, j] >= thr and not used[j]
                        if ok:
                            used[j] = True
                        store[c].append((float(s[k]), int(ok)))
                if len(g):
                    best_iou[c].extend((ious.max(axis=0) if len(p) else np.zeros(len(g))).tolist())
                if len(g):
                    good = iou_matrix(p[s >= score_thr], g).max(axis=0) >= iou_thr if (s >= score_thr).any() else np.zeros(len(g), bool)
                    hit[(doc, CLASSES[c])][0] += int(good.sum())
                    hit[(doc, CLASSES[c])][1] += len(g)
        if on_batch:
            on_batch(len(images))
    model.transform.min_size = TRAIN_MIN_SIZES
    per_class = {}
    for c in sorted(n_gt):
        if n_gt[c]:
            per_class[CLASSES[c]] = {"ap50": round(average_precision(dets[c], n_gt[c]), 4),
                                     "ap75": round(average_precision(dets75[c], n_gt[c]), 4),
                                     "mean_iou": round(float(np.mean(best_iou[c])), 4), "gt": n_gt[c]}
    m = float(np.mean([v["ap50"] for v in per_class.values()])) if per_class else 0.0
    m75 = float(np.mean([v["ap75"] for v in per_class.values()])) if per_class else 0.0
    miou = float(np.mean([v["mean_iou"] for v in per_class.values()])) if per_class else 0.0
    by_doc = defaultdict(dict)
    for (doc, cls), (f, t) in sorted(hit.items()):
        by_doc[doc][cls] = round(f / t, 4) if t else None
    return {"map50": round(m, 4), "map75": round(m75, 4), "mean_iou": round(miou, 4), "per_class": per_class, "recall_at_score_0.5": {k: dict(v) for k, v in by_doc.items()}}


@torch.no_grad()
def render_preview(model, t, device, path):
    """Draw detections on one held-out card (``t``: the dataset's RGB tensor)."""
    model.eval()
    model.transform.min_size = (EVAL_MIN_SIZE,)
    img = cv2.cvtColor((t.permute(1, 2, 0).numpy() * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    with torch.autocast("cuda", enabled=device.type == "cuda"):
        out = model([t.to(device)])[0]
    model.transform.min_size = TRAIN_MIN_SIZES
    for b, s, l in zip(out["boxes"].float().cpu().numpy(), out["scores"].float().cpu().numpy(), out["labels"].cpu().numpy()):
        if s < 0.5:
            continue
        x0, y0, x1, y1 = b.astype(int)
        colour = tuple(int(v) for v in np.random.default_rng(int(l) * 7).integers(40, 230, 3))
        cv2.rectangle(img, (x0, y0), (x1, y1), colour, 2)
        cv2.putText(img, f"{CLASSES[l]} {s:.2f}", (x0, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
    scale = 900 / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])


# --------------------------------------------------------------------------- dashboard
class Board:
    def __init__(self, port):
        self.lock = threading.Lock()
        self.port = port
        self.s = {"stage": "starting", "detail": "", "epoch": 0, "epochs": 0, "iter": 0, "iters": 0,
                  "step": 0, "steps": 0, "started": time.time(), "gpu": "", "mem": 0.0, "mem_total": 0.0,
                  "lr": 0.0, "loss": [], "parts": {}, "epochs_hist": [], "per_class": {}, "recall": {},
                  "best": 0.0, "log": [], "finished": False, "preview": 0, "split": {}}

    def set(self, **kw):
        with self.lock:
            self.s.update(kw)

    def note(self, msg):
        with self.lock:
            self.s["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            del self.s["log"][:-30]
        print(msg, flush=True)

    def snapshot(self):
        with self.lock:
            d = dict(self.s)
            d["elapsed"] = time.time() - d["started"]
            done = d["step"] / d["steps"] if d["steps"] else 0
            d["eta"] = d["elapsed"] * (1 - done) / done if done > 0.01 and not d["finished"] else 0
            d["loss"] = d["loss"][-600:]
            return json.dumps(d)

    def start(self):
        board = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, ctype, code=200):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                p = self.path.split("?")[0]
                if p == "/":
                    self._send(DASHBOARD.encode(), "text/html; charset=utf-8")
                elif p == "/api/state":
                    self._send(board.snapshot().encode(), "application/json")
                elif p == "/preview.jpg" and PREVIEW.is_file():
                    self._send(PREVIEW.read_bytes(), "image/jpeg")
                else:
                    self._send(b"not found", "text/plain", 404)

        srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.port}/"


DASHBOARD = r"""<!doctype html><html><head><meta charset="utf-8"><title>Region detector training</title>
<style>
:root{--bg:#0f1417;--panel:#161d21;--line:#26323a;--ink:#e4ecef;--dim:#8ea1ab;--acc:#4fd1b5;--warn:#f0b35a;--bad:#ef6f6c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Segoe UI",system-ui,sans-serif;padding:20px}
h1{font-size:18px;margin:0}.sub{color:var(--dim);font-size:12.5px;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.k{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.k b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.k span{color:var(--dim);font-size:11px;letter-spacing:.06em;text-transform:uppercase}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:8px}.bar i{display:block;height:100%;background:var(--acc);width:0}
.cols{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin-bottom:14px}
.panel h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:0 0 8px;font-weight:600}
svg{width:100%;height:190px;display:block}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
td,th{padding:3px 6px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--dim);font-weight:500;font-size:11.5px}
td.n{text-align:right}.good{color:var(--acc)}.mid{color:var(--warn)}.low{color:var(--bad)}
pre{margin:0;font:12px/1.5 Consolas,monospace;color:var(--dim);white-space:pre-wrap;max-height:260px;overflow:auto}
img{max-width:100%;border-radius:4px;display:block}.pill{display:inline-block;padding:1px 8px;border-radius:10px;background:var(--line);font-size:12px;margin-left:8px}
</style></head><body>
<h1>PEHCHAAN · region detector training <span class="pill" id="stage">-</span></h1>
<div class="sub" id="gpu">-</div>
<div class="grid">
<div class="k"><span>Epoch</span><b id="ep">-</b><div class="bar"><i id="epb"></i></div></div>
<div class="k"><span>Overall</span><b id="pct">-</b><div class="bar"><i id="allb"></i></div></div>
<div class="k"><span>Elapsed / ETA</span><b id="time">-</b></div>
<div class="k"><span>Loss (avg 50)</span><b id="loss">-</b></div>
<div class="k"><span>Held-out photo-style mAP</span><b id="map">-</b></div>
<div class="k"><span>GPU memory</span><b id="mem">-</b></div>
</div>
<div class="cols"><div>
<div class="panel"><h2>Training loss</h2><svg id="chart" viewBox="0 0 600 190" preserveAspectRatio="none"></svg></div>
<div class="panel"><h2>Latest held-out card, photo-style (score ≥ 0.5)</h2><img id="pv" alt="preview appears after the first evaluation"></div>
</div><div>
<div class="panel"><h2>Per-class AP · held-out people, photo-style</h2><table id="pc"><tr><td style="color:var(--dim)">after first evaluation</td></tr></table></div>
<div class="panel"><h2>Log</h2><pre id="log"></pre></div>
</div></div>
<script>
const $=id=>document.getElementById(id);const fmt=s=>{s=Math.round(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return(h?h+"h ":"")+m+"m "+x+"s"};
const cls=v=>v>=.9?"good":v>=.7?"mid":"low";let pvn=-1;
async function tick(){try{const d=await (await fetch("/api/state")).json();
$("stage").textContent=d.stage+(d.detail?" · "+d.detail:"");$("gpu").textContent=d.gpu+"  ·  split "+JSON.stringify(d.split);
$("ep").textContent=d.epoch+" / "+d.epochs;$("epb").style.width=(d.iters?100*d.iter/d.iters:0)+"%";
const p=d.steps?100*d.step/d.steps:0;$("pct").textContent=p.toFixed(1)+"%";$("allb").style.width=p+"%";
$("time").textContent=fmt(d.elapsed)+" / "+(d.finished?"done":fmt(d.eta));
const L=d.loss;const last=L.slice(-50);$("loss").textContent=last.length?(last.reduce((a,b)=>a+b,0)/last.length).toFixed(3):"-";
$("map").textContent=d.epochs_hist.length?(()=>{const h=d.epochs_hist[d.epochs_hist.length-1];return (100*h.map50).toFixed(1)+"% · @.75 "+(100*h.map75).toFixed(1)+"%"})():"-";
$("mem").textContent=d.mem.toFixed(1)+" / "+d.mem_total.toFixed(1)+" GB";
if(L.length>1){const mx=Math.max(...L.slice(Math.floor(L.length*.05))),mn=Math.min(...L);const sx=600/(L.length-1),y=v=>180-170*(Math.min(v,mx)-mn)/((mx-mn)||1);
let sm=[],a=L[0];for(const v of L){a=.9*a+.1*v;sm.push(a)}
$("chart").innerHTML=`<polyline fill="none" stroke="#26323a" stroke-width="1" points="${L.map((v,i)=>i*sx+","+y(v)).join(" ")}"/><polyline fill="none" stroke="#4fd1b5" stroke-width="2" points="${sm.map((v,i)=>i*sx+","+y(v)).join(" ")}"/><text x="4" y="12" fill="#8ea1ab" font-size="11">${mx.toFixed(2)}</text><text x="4" y="186" fill="#8ea1ab" font-size="11">${mn.toFixed(2)}</text>`}
const pc=Object.entries(d.per_class);if(pc.length){$("pc").innerHTML="<tr><th>class</th><th class=n>AP50</th><th class=n>AP75</th><th class=n>IoU</th><th class=n>boxes</th></tr>"+pc.sort((a,b)=>a[1].ap75-b[1].ap75).map(([k,v])=>`<tr><td>${k}</td><td class="n ${cls(v.ap50)}">${(100*v.ap50).toFixed(1)}</td><td class="n ${cls(v.ap75)}">${(100*v.ap75).toFixed(1)}</td><td class=n>${v.mean_iou.toFixed(3)}</td><td class=n>${v.gt}</td></tr>`).join("")}
$("log").textContent=d.log.join("\n");if(d.preview!==pvn){pvn=d.preview;if(pvn>0)$("pv").src="/preview.jpg?"+pvn}
if(!d.finished)setTimeout(tick,1000)}catch(e){setTimeout(tick,2000)}}tick();
</script></body></html>"""


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=14)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--eval-every", type=int, default=2)
    ap.add_argument("--hold", type=int, default=900, help="keep the dashboard up this many seconds after finishing")
    args = ap.parse_args()

    torch.manual_seed(SEED); random.seed(SEED); np.random.seed(SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    board = Board(args.port)
    url = board.start()
    print(f"dashboard: {url}", flush=True)
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(0)
        board.set(gpu=f"{props.name} · CUDA {torch.version.cuda} · torch {torch.__version__}", mem_total=props.total_memory / 2**30)
        torch.backends.cudnn.benchmark = False  # multi-scale + 4 card sizes = new shape almost every batch; re-tuning each one stalls
    else:
        board.set(gpu="CPU only (no CUDA device found)")
        board.note("WARNING: CUDA not available, training on CPU will be very slow")

    samples = build_index()
    train_s, val_s, val_people = split_by_person(samples)
    split = {"train_cards": len(train_s), "val_cards": len(val_s), "val_people": len(val_people)}
    board.set(split=split, stage="data")
    board.note(f"{len(samples)} cards, {sum(len(s['boxes']) for s in samples)} boxes; split by person {split}")

    train_dl = DataLoader(Cards(train_s, "train"), batch_size=args.batch, shuffle=True, num_workers=args.workers,
                          collate_fn=collate, pin_memory=True, persistent_workers=args.workers > 0, drop_last=True)
    # two held-out views of the same people: the cards as generated, and a fixed
    # photo-style distortion of each (placed on a background, tilted, skewed)
    val_dl = DataLoader(Cards(val_s, "clean"), batch_size=args.batch, shuffle=False, num_workers=args.workers,
                        collate_fn=collate, pin_memory=True, persistent_workers=args.workers > 0)
    dist_ds = Cards(val_s, "distorted")
    dist_dl = DataLoader(dist_ds, batch_size=args.batch, shuffle=False, num_workers=args.workers,
                         collate_fn=collate, pin_memory=True, persistent_workers=args.workers > 0)

    model, loaded, total = build_model()
    model.to(device)
    board.note(f"Faster R-CNN R50-FPN: {loaded}/{total} tensors from COCO (RPN + box heads fresh: wide anchors, {len(CLASSES) - 1} classes)")

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=args.lr, momentum=0.9, weight_decay=1e-4)
    iters = len(train_dl)
    total_steps = iters * args.epochs
    warmup = min(300, iters)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warmup if s < warmup else 0.5 * (1 + math.cos(math.pi * (s - warmup) / max(1, total_steps - warmup))))
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    board.set(epochs=args.epochs, iters=iters, steps=total_steps + 2 * len(val_dl) * math.ceil(args.epochs / args.eval_every))

    best, history, step, progress = -1.0, [], 0, 0
    preview_idx = next(i for i, s in enumerate(val_s) if s["doc_type"] == "passport")
    for epoch in range(1, args.epochs + 1):
        model.train()
        board.set(stage="training", detail=f"epoch {epoch}", epoch=epoch, iter=0)
        t0, running = time.time(), []
        for it, (images, targets, _) in enumerate(train_dl, 1):
            images = [im.to(device, non_blocking=True) for im in images]
            targets = [{k: v.to(device, non_blocking=True) for k, v in t.items()} for t in targets]
            with torch.autocast("cuda", enabled=device.type == "cuda"):
                losses = model(images, targets)
                loss = sum(losses.values())
            if not torch.isfinite(loss):
                board.note(f"non-finite loss at step {step}, batch skipped")
                opt.zero_grad(set_to_none=True)
                continue
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 10.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1; progress += 1
            running.append(loss.item())
            with board.lock:
                board.s["loss"].append(round(loss.item(), 4))
                board.s.update(iter=it, step=progress, lr=opt.param_groups[0]["lr"],
                               parts={k: round(v.item(), 4) for k, v in losses.items()},
                               mem=torch.cuda.max_memory_allocated() / 2**30 if device.type == "cuda" else 0.0)
        board.note(f"epoch {epoch}: loss {np.mean(running):.3f}, {iters / (time.time() - t0):.2f} it/s, lr {opt.param_groups[0]['lr']:.5f}")

        if epoch % args.eval_every == 0 or epoch == args.epochs:
            board.set(stage="evaluating", detail=f"held-out people, epoch {epoch}")

            def on_batch(n):
                nonlocal progress
                progress += 1
                board.set(step=progress)

            m_clean = evaluate(model, val_dl, device, val_s, on_batch=on_batch)
            m = evaluate(model, dist_dl, device, val_s, on_batch=on_batch)   # selection metric
            history.append({"epoch": epoch, "loss": round(float(np.mean(running)), 4),
                            "map50": m["map50"], "map75": m["map75"], "mean_iou": m["mean_iou"],
                            "map50_clean": m_clean["map50"], "map75_clean": m_clean["map75"]})
            render_preview(model, dist_ds[preview_idx][0], device, PREVIEW)
            weakest = sorted(m["per_class"].items(), key=lambda kv: kv[1]["ap75"])[:3]
            board.note(f"epoch {epoch}: held-out photo-style mAP50 {m['map50']:.3f} mAP75 {m['map75']:.3f} IoU {m['mean_iou']:.3f}"
                       f" | clean mAP50 {m_clean['map50']:.3f} mAP75 {m_clean['map75']:.3f}; weakest@0.75 " +
                       ", ".join(f"{k} {v['ap75']:.2f}" for k, v in weakest))
            with board.lock:
                board.s.update(per_class=m["per_class"], recall=m["recall_at_score_0.5"], epochs_hist=list(history))
                board.s["preview"] += 1
            score = (m["map50"], m["map75"], m["mean_iou"])
            if best == -1.0 or score > best:
                best = score
                board.set(best=m["map50"])
                OUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
                torch.save({
                    "model_state": model.state_dict(),
                    "classes": CLASSES,
                    "architecture": {"name": "fasterrcnn_resnet50_fpn", "anchor_sizes": ANCHOR_SIZES,
                                     "anchor_ratios": ANCHOR_RATIOS, "min_size": EVAL_MIN_SIZE, "max_size": MAX_SIZE},
                    "epoch": epoch, "metrics": {"photo_style": m, "clean": m_clean}, "split": split, "val_people": val_people,
                    "trained_on": "training/data_generated (generated Aadhaar, PAN, DL, passport cards)",
                }, OUT_MODEL)
                OUT_METRICS.write_text(json.dumps({"best_epoch": epoch, "split": split, "history": history,
                                                   "iou_threshold": 0.5,
                                                   "selected_on": "photo_style map50",
                                                   "photo_style": m, "clean": m_clean}, indent=2))
                board.note(f"saved best checkpoint -> {OUT_MODEL.relative_to(BACKEND)}")

    board.set(stage="done", detail=f"best held-out photo-style mAP50/75/IoU {best}", finished=True, step=board.s["steps"])
    board.note(f"finished; metrics in {OUT_METRICS.relative_to(BACKEND)}")
    if args.hold > 0:
        time.sleep(args.hold)


if __name__ == "__main__":
    main()
