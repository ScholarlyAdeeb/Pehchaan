"""Live progress dashboard for the dataset generator.

A tiny stdlib HTTP server that the generator pokes as it works, so there is a
browser window showing what is happening, how far along it is and how long is
left.  No framework and no extra dependency - the generator already runs on the
standard library plus Pillow and OpenCV.

Endpoints
---------
``GET /``                  the dark-theme dashboard (polls, so no websocket needed)
``GET /api/state``         JSON snapshot of the run
``GET /api/preview/<name>``  a generated sample, for the thumbnail strip

Usage from the generator::

    from progress_server import Progress

    progress = Progress(total=1200, port=8765)
    progress.open_browser()
    progress.stage("aadhaar", "Rendering 300 Aadhaar cards")
    for i, row in enumerate(rows):
        ...
        progress.tick("aadhaar")
    progress.finish()
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
PREVIEW_DIR = HERE / "preview" / "live"

#: How many thumbnails the dashboard keeps *per document type*. Two of each of
#: the four cards fills three rows of three, and - unlike a single global cap -
#: it means a long run never scrolls one card type off the panel entirely.
PREVIEW_PER_TYPE = 2


@dataclass
class Track:
    """One document type's progress."""

    name: str
    total: int
    done: int = 0
    started: float = 0.0
    elapsed: float = 0.0

    @property
    def fraction(self) -> float:
        return (self.done / self.total) if self.total else 0.0

    @property
    def rate(self) -> float:
        return self.done / self.elapsed if self.elapsed > 0.05 else 0.0

    @property
    def eta(self) -> float:
        if self.rate <= 0:
            return 0.0
        return max(0.0, (self.total - self.done) / self.rate)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total": self.total,
            "done": self.done,
            "percent": round(self.fraction * 100, 1),
            "elapsed": round(self.elapsed, 1),
            "eta": round(self.eta, 1),
            "rate": round(self.rate, 2),
            "started": self.started > 0,
        }


class Progress:
    """Thread-safe run state plus the dashboard server."""

    def __init__(self, total: int, port: int = 8765, host: str = "127.0.0.1") -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.total = total
        self._stage = "starting"
        self._detail = "booting"
        self.done = 0
        self.errors = 0
        self.finished = False
        self.log: list[str] = []
        self.previews: list[dict] = []
        self._written: set[str] = set()
        self._tracks: dict[str, Track] = {}
        self.port = port
        self.host = host
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # ---- state ---------------------------------------------------------- #
    def add_track(self, name: str, total: int) -> None:
        with self._lock:
            self._tracks[name] = Track(name=name, total=total)

    def stage(self, stage: str, detail: str = "") -> None:
        with self._lock:
            self._stage = stage
            if detail:
                self._detail = detail
            self._append_locked(f"{stage}: {detail}" if detail else stage)

    def note(self, message: str) -> None:
        with self._lock:
            self._append_locked(message)

    def error(self, message: str) -> None:
        with self._lock:
            self.errors += 1
            self._append_locked(f"ERROR {message}")

    def tick(self, track: str | None = None, n: int = 1) -> None:
        with self._lock:
            self.done += n
            if track and track in self._tracks:
                t = self._tracks[track]
                if not t.started:
                    t.started = time.time()
                t.done += n
                t.elapsed = time.time() - t.started

    def add_preview(self, document_type: str, index: int, image_path: Path) -> None:
        """Publish a generated sample for the dashboard's thumbnail strip.

        Copies rather than moves: these are real dataset members and the
        manifest counts them.  Files that drop out of the strip are deleted so
        a long run does not leave a copy of every sampled card behind.
        """
        name = f"{document_type}_{index:04d}.jpg"
        try:
            target = PREVIEW_DIR / name
            if target.exists():
                target.unlink()
            shutil.copyfile(image_path, target)
        except OSError:
            return
        with self._lock:
            # remember only what this class wrote, so cleanup can never delete
            # an unrelated file that happens to sit in the preview directory
            self._written.add(name)
            self.previews.append({"document_type": document_type, "file": name})
            # keep only the newest few of each type, so all four card types stay
            # on the panel for the whole run instead of the last one crowding
            # out the rest
            seen: dict[str, int] = {}
            keep: list[dict] = []
            for item in reversed(self.previews):
                count = seen.get(item["document_type"], 0)
                if count < PREVIEW_PER_TYPE:
                    seen[item["document_type"]] = count + 1
                    keep.append(item)
            self.previews = list(reversed(keep))
            live = {p["file"] for p in self.previews}
            stale = self._written - live
            self._written = live
        for name_to_drop in stale:
            try:
                (PREVIEW_DIR / name_to_drop).unlink()
            except OSError:
                pass

    def finish(self) -> None:
        with self._lock:
            self.finished = True
            self._stage = "done"
            self._detail = "complete"
            self._append_locked("generation complete")

    def _append_locked(self, message: str) -> None:
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        del self.log[:-40]

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = time.time() - self.started
            rate = self.done / elapsed if elapsed > 0.05 else 0.0
            remaining = (self.total - self.done) / rate if rate > 0 else 0.0
            return {
                "stage": self._stage,
                "detail": self._detail,
                "done": self.done,
                "total": self.total,
                "percent": round(100 * self.done / self.total, 2) if self.total else 0.0,
                "errors": self.errors,
                "elapsed": round(elapsed, 1),
                "remaining": round(remaining, 1),
                "rate": round(rate, 2),
                "finished": self.finished,
                "tracks": [t.to_dict() for t in self._tracks.values()],
                "log": list(self.log[-14:]),
                "previews": list(self.previews),
            }

    # ---- server --------------------------------------------------------- #
    def start(self) -> None:
        progress = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                """Silence the default stderr access log."""

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path in ("/", "/index.html"):
                    self._send(200, DASHBOARD.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._send(
                        200,
                        json.dumps(progress.snapshot()).encode("utf-8"),
                        "application/json",
                    )
                elif path.startswith("/api/preview/"):
                    name = Path(unquote(path[len("/api/preview/"):])).name
                    f = PREVIEW_DIR / name
                    if f.is_file():
                        self._send(200, f.read_bytes(), "image/jpeg")
                    else:
                        self._send(404, b"not found", "text/plain")
                else:
                    self._send(404, b"not found", "text/plain")

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def open_browser(self) -> str:
        url = f"http://{self.host}:{self.port}/"
        self.start()
        try:
            webbrowser.open(url)
        except Exception:  # headless box: the URL is still printed
            pass
        self.note(f"dashboard at {url}")
        return url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    def hold(self, seconds: float) -> None:
        """Keep serving after the run so the finished state stays on screen.

        A full 1200-card run takes well under a minute; without this the tab
        would 404 before anyone had time to read the totals.
        """
        if seconds <= 0:
            return
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(0.5)


def human(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60):02d}m"


DASHBOARD = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dataset generation</title>
<style>
  :root {
    --bg:#0a0c10; --panel:#12161d; --panel2:#171d26; --line:#232b36;
    --fg:#e6edf5; --dim:#8b98a9; --accent:#4da3ff; --ok:#3ddc84;
    --warn:#ffb020; --err:#ff5c5c;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--fg); min-height:100vh;
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  .wrap { max-width:1080px; margin:0 auto; padding:28px 20px 48px; }
  header { display:flex; align-items:baseline; gap:14px; margin-bottom:22px; }
  h1 { font-size:19px; margin:0; letter-spacing:-.01em; }
  .sub { color:var(--dim); font-size:13px; }
  .pill {
    margin-left:auto; font-size:12px; padding:4px 11px; border-radius:999px;
    background:var(--panel2); border:1px solid var(--line); color:var(--dim);
  }
  .pill.live { color:var(--accent); border-color:#274a6d; }
  .pill.done { color:var(--ok); border-color:#1d4a33; }

  .hero {
    background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:20px 22px; margin-bottom:18px;
  }
  .stage { font-size:16px; font-weight:600; }
  .detail { color:var(--dim); margin-top:3px; min-height:20px; }
  .bar {
    position:relative; height:12px; margin:16px 0 10px; border-radius:999px;
    background:#1b222c; overflow:hidden;
  }
  .bar > i {
    display:block; height:100%; width:0%; border-radius:999px;
    background:linear-gradient(90deg,#2f7fd4,var(--accent));
    transition:width .35s ease;
  }
  .bar.done > i { background:linear-gradient(90deg,#2f9e5f,var(--ok)); }
  .counts { display:flex; justify-content:space-between; color:var(--dim); font-size:13px; }
  .counts b { color:var(--fg); font-variant-numeric:tabular-nums; }

  .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .stat span { display:block; color:var(--dim); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
  .stat b { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; }

  .cols { display:grid; grid-template-columns:1.35fr 1fr; gap:16px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.07em;
             color:var(--dim); margin:0 0 12px; font-weight:600; }

  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
       color:var(--dim); font-weight:600; padding:0 0 8px; }
  td { padding:7px 0; border-top:1px solid var(--line); font-size:13px; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; color:var(--dim); }
  .mini { height:5px; border-radius:999px; background:#1b222c; margin-top:5px; overflow:hidden; }
  .mini > i { display:block; height:100%; width:0; background:var(--accent); transition:width .35s ease; }
  .mini.done > i { background:var(--ok); }

  .shots { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
  .shots figure { margin:0; }
  .shots img { width:100%; border-radius:8px; border:1px solid var(--line); display:block;
               background:#0e1218; aspect-ratio:3/2; object-fit:contain; padding:2px; }
  .shots figcaption { color:var(--dim); font-size:10px; margin-top:4px;
                      text-align:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .shots .empty { grid-column:1/-1; color:var(--dim); font-size:12px; text-align:center;
                  padding:22px 0; border:1px dashed var(--line); border-radius:8px; }

  pre {
    margin:0; font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    color:var(--dim); white-space:pre-wrap; word-break:break-word; max-height:280px; overflow:auto;
  }
  .err { color:var(--err); }
  @media (max-width:860px) {
    .grid { grid-template-columns:repeat(2,1fr); }
    .cols { grid-template-columns:1fr; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>PEHCHAAN &middot; identity dataset generation</h1>
    <span class="sub">mock_government_ids_300.xlsx &rarr; cards with photo &amp; QR holders</span>
    <span class="pill" id="pill">connecting</span>
  </header>

  <section class="hero">
    <div class="stage" id="stage">&hellip;</div>
    <div class="detail" id="detail">&nbsp;</div>
    <div class="bar" id="bar"><i></i></div>
    <div class="counts">
      <span><b id="done">0</b> / <span id="total">0</span> documents</span>
      <span><b id="pct">0</b>%</span>
    </div>
  </section>

  <section class="grid">
    <div class="stat"><span>Elapsed</span><b id="elapsed">0s</b></div>
    <div class="stat"><span>Remaining</span><b id="remaining">&mdash;</b></div>
    <div class="stat"><span>Throughput</span><b id="rate">0/s</b></div>
    <div class="stat"><span>Errors</span><b id="errors">0</b></div>
  </section>

  <div class="cols">
    <section class="card">
      <h2>Per document type</h2>
      <table>
        <thead><tr><th>Type</th><th style="text-align:right">Done</th><th style="text-align:right">ETA</th></tr></thead>
        <tbody id="tracks"><tr><td colspan="3" style="color:var(--dim)">&hellip;</td></tr></tbody>
      </table>
    </section>
    <section class="card">
      <h2>Latest output</h2>
      <div class="shots" id="shots"></div>
    </section>
  </div>

  <section class="card" style="margin-top:16px">
    <h2>Activity</h2>
    <pre id="log">&nbsp;</pre>
  </section>
</div>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (s) => {
  if (s === null || s === undefined) return "-";
  s = Math.max(0, Math.round(s));
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s/60) + "m " + String(s%60).padStart(2,"0") + "s";
  return Math.floor(s/3600) + "h " + String(Math.floor((s%3600)/60)).padStart(2,"0") + "m";
};
let lastTrackKey = "";

function render(s) {
  $("stage").textContent = s.stage;
  $("detail").textContent = s.detail || " ";
  $("done").textContent = s.done;
  $("total").textContent = s.total;
  $("pct").textContent = s.percent;
  $("bar").classList.toggle("done", s.finished);
  $("bar").firstElementChild.style.width = Math.min(100, s.percent) + "%";
  $("elapsed").textContent = fmt(s.elapsed);
  $("remaining").textContent = s.finished ? "0s" : fmt(s.remaining);
  $("rate").textContent = s.rate + "/s";
  $("errors").textContent = s.errors;
  $("errors").style.color = s.errors ? "var(--err)" : "";

  const pill = $("pill");
  pill.textContent = s.finished ? "complete" : (s.stage === "starting" ? "connecting" : "running");
  pill.className = "pill " + (s.finished ? "done" : "live");

  const key = JSON.stringify(s.tracks);
  if (key !== lastTrackKey) {
    lastTrackKey = key;
    $("tracks").innerHTML = s.tracks.map((t) => `
      <tr>
        <td>
          <div>${t.name}</div>
          <div class="mini ${t.percent >= 100 ? "done" : ""}"><i style="width:${Math.min(100,t.percent)}%"></i></div>
        </td>
        <td class="num">${t.done} / ${t.total}</td>
        <td class="num">${t.percent >= 100 ? "-" : fmt(t.eta)}</td>
      </tr>`).join("") || '<tr><td colspan="3" style="color:var(--dim)">no tracks</td></tr>';
  }

  $("shots").innerHTML = s.previews.length
    ? s.previews.slice().reverse().map((p) => `
    <figure>
      <img src="/api/preview/${p.file}?t=${Date.now()}" alt="${p.document_type} sample card"
           onerror="this.closest('figure').querySelector('figcaption').textContent='failed to load'">
      <figcaption>${p.document_type}</figcaption>
    </figure>`).join("")
    : '<div class="empty">first card in a moment...</div>';

  $("log").innerHTML = s.log.map((l) =>
    l.startsWith("[") && l.includes("ERROR")
      ? '<span class="err">' + l.replace(/&/g,"&amp;").replace(/</g,"&lt;") + "</span>"
      : l.replace(/&/g,"&amp;").replace(/</g,"&lt;")).join("\n");
}

async function poll() {
  try {
    const r = await fetch("/api/state", {cache:"no-store"});
    render(await r.json());
  } catch (e) { /* server restarting */ }
}
poll();
setInterval(poll, 700);
</script>
</body>
</html>
"""
