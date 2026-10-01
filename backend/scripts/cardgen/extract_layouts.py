"""Extract the exact text layout of a dataset card PDF (page 1).

The dataset PDFs under ``sample-data`` are a single background JPEG with a text
overlay.  Page 1 looks like::

    0.75 0 0 -0.75 0 792 cm          <- outer: scale + vertical flip
    q <clip> W* n q <W 0 0 -H x0 ytop> cm /Image1 Do Q Q
    q <clip> W* n 0 0 0 rg
    BT 0 Tr /F1 <size> Tf 1 0 0 -1 <x> <y> Tm [<cid> <kern> ...] TJ ET
    Q ...

The important detail: the text ``Tm`` coordinates are expressed in the *same*
space as the image ``cm`` (the space the outer ``cm`` then maps onto the page).
So image pixels follow directly::

    px = (x - x0) / W * image_width
    py = (y - (ytop - H)) / H * image_height
    size_px = size * image_width / W

The font is a single CID font per card, so glyph codes in ``TJ`` are run
through that font's ``/ToUnicode`` CMap.  Passports embed several fonts, so the
map is resolved per font resource rather than merged.

The result is a list of positioned text runs which the generator re-typesets
with a real font, one per spreadsheet row.
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path

# ``sample-data`` sits next to ``backend``; never depend on the caller's cwd.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA = BACKEND_ROOT.parent / "sample-data"
LAYOUT_DIR = Path(__file__).resolve().parent / "layouts"


# --------------------------------------------------------------------------- #
# low level PDF access
# --------------------------------------------------------------------------- #
def _objects(raw: bytes) -> dict[int, bytes]:
    """All indirect objects, including those packed inside /ObjStm.

    The smaller cards are Microsoft Print-to-PDF output with plain objects, but
    the 37 MB passport PDF uses compressed object streams, so both layouts have
    to be supported to read all four cards.
    """
    out: dict[int, bytes] = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", raw, re.S):
        out[int(m.group(1))] = m.group(2)

    for _, body in list(out.items()):
        if b"/ObjStm" not in body:
            continue
        n = re.search(rb"/N\s+(\d+)", body)
        first = re.search(rb"/First\s+(\d+)", body)
        if not n or not first:
            continue
        data = _stream_of(body)
        if not data:
            continue
        header = data[: int(first.group(1))].split()
        pairs = [
            (int(header[i]), int(header[i + 1]))
            for i in range(0, min(len(header), int(n.group(1)) * 2), 2)
        ]
        for i, (objnum, off) in enumerate(pairs):
            end = pairs[i + 1][1] + int(first.group(1)) if i + 1 < len(pairs) else len(data)
            out.setdefault(objnum, data[int(first.group(1)) + off:end])
    return out


def _stream_of(body: bytes) -> bytes | None:
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    data = body[m.end():]
    if b"endstream" in data:
        data = data[: data.rfind(b"endstream")]
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data


def _parse_tounicode(data: bytes | None) -> dict[int, str]:
    """Parse a ``/ToUnicode`` CMap into ``{cid: character}``."""
    cmap: dict[int, str] = {}
    if not data:
        return cmap
    text = data.decode("latin-1")
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            cmap[int(src, 16)] = chr(int(dst[:4], 16))
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, start in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            lo_i, hi_i, st_i = int(lo, 16), int(hi, 16), int(start, 16)
            for i in range(lo_i, hi_i + 1):
                cmap[i] = chr(st_i + i - lo_i)
    return cmap


def _resolve(objs: dict[int, bytes], blob: bytes | None) -> int | None:
    """Follow a single indirect reference inside a dict fragment."""
    if not blob:
        return None
    m = re.search(rb"(\d+)\s+0\s+R", blob)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass
class TextRun:
    """One positioned string on the card, in background-image pixels."""

    x: float
    y: float          # baseline, px, y grows downward
    size: float       # px
    text: str
    color: tuple[int, int, int]
    font: str
    flipped: bool     # True when Tm had a negative d component

    def to_dict(self) -> dict:
        d = asdict(self)
        d["color"] = list(self.color)
        return d


# --------------------------------------------------------------------------- #
# affine matrix helpers, in PDF order [a b c d e f]
# --------------------------------------------------------------------------- #
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m: tuple[float, ...], n: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
    """Compose two affine matrices in PDF order, applying ``n`` first then ``m``.

    A point ``p`` maps as ``(x', y') = (a*x + c*y + e, b*x + d*y + f)``, so
    ``_mul(m, n)`` is the matrix of ``m(n(p))``.
    """
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _translate(tx: float, ty: float) -> tuple[float, ...]:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def _scale_of(m: tuple[float, ...]) -> float:
    """Uniform scale factor of an affine matrix (geometric mean of the axes)."""
    det = abs(m[0] * m[3] - m[1] * m[2])
    return det ** 0.5 or 1.0


_TOKEN = re.compile(
    r"(?P<q>\bq\b)"
    r"|(?P<Q>\bQ\b)"
    r"|(?P<cm>(?P<m1>[-\d\.]+)\s+(?P<m2>[-\d\.]+)\s+(?P<m3>[-\d\.]+)\s+(?P<m4>[-\d\.]+)"
    r"\s+(?P<m5>[-\d\.]+)\s+(?P<m6>[-\d\.]+)\s+cm)"
    r"|(?P<BT>\bBT\b)"
    r"|(?P<Tm>(?P<t1>[-\d\.]+)\s+(?P<t2>[-\d\.]+)\s+(?P<t3>[-\d\.]+)\s+(?P<t4>[-\d\.]+)"
    r"\s+(?P<t5>[-\d\.]+)\s+(?P<t6>[-\d\.]+)\s+Tm)"
    r"|(?P<Td>(?P<d1>[-\d\.]+)\s+(?P<d2>[-\d\.]+)\s+T[dD])"
    r"|(?P<Tstar>\bT\*)"
    r"|(?P<TL>(?P<lead>[-\d\.]+)\s+TL)"
    r"|(?P<Tf>/(?P<fname>\w+)\s+(?P<fsize>[\d\.]+)\s+Tf)"
    r"|(?P<rg>(?P<r>[\d\.]+)\s+(?P<g>[\d\.]+)\s+(?P<b>[\d\.]+)\s+rg)"
    r"|(?P<tj>\[(?P<tjbody>.*?)\]\s*TJ)"
    r"|(?P<th>(?P<top>(?:\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>))\s*Tj)"
    r"|(?P<do>/(?P<xname>\w+)\s+Do)"
)


def _decode_tj(body: str, cmap: dict[int, str]) -> str:
    """Decode a ``TJ`` array of ``<cid><kern>`` pairs.

    Numeric kerning entries are dropped: they only encode inter-glyph spacing
    from the original typesetter, and the generator re-lays the string out with
    a real font.
    """
    chars: list[str] = []
    for m in re.finditer(r"<([0-9A-Fa-f]+)>|(-?[\d\.]+)", body):
        hexes = m.group(1)
        if hexes is None:
            continue
        for i in range(0, len(hexes), 4):
            chars.append(cmap.get(int(hexes[i:i + 4], 16), ""))
    return "".join(chars)


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
            "(": "(", ")": ")", "\\": "\\"}


def _decode_str(operand: str, cmap: dict[int, str]) -> str:
    """Decode a show-text operand: either ``<hex>`` or a literal ``(string)``."""
    if operand.startswith("<"):
        h = operand[1:-1].replace(" ", "")
        return "".join(cmap.get(int(h[i:i + 4], 16), "") for i in range(0, len(h), 4))
    body, out, i = operand[1:-1], [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(cmap.get(ord(c), c) for c in "".join(out))


def extract_layout(pdf_path: Path, page: int = 1) -> dict:
    """Return image size, image placement and positioned text runs."""
    raw = pdf_path.read_bytes()
    objs = _objects(raw)

    # ---- page object -> content stream.  Following /Type /Page matters: the
    # embedded CFF font program also contains BT/Tf opcodes and would otherwise
    # be mistaken for a page.
    page_objs = [
        (num, body)
        for num, body in sorted(objs.items())
        if re.search(rb"/Type\s*/Page(?![s])", body)
    ]
    if not page_objs:
        raise ValueError(f"no /Type /Page objects in {pdf_path}")
    _, page_body = page_objs[page - 1]

    cm = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", page_body)
    if not cm:
        raise ValueError(f"page {page} of {pdf_path} has no resolvable /Contents")
    refs = [int(n) for n in re.findall(rb"(\d+)\s+0\s+R", cm.group(1))]
    content = b"".join(_stream_of(objs[r]) or b"" for r in refs).decode("latin-1")

    # ---- per font resource name -> ToUnicode
    res_ref = re.search(rb"/Resources\s+(\d+)\s+0\s+R", page_body)
    res = objs.get(int(res_ref.group(1)), b"") if res_ref else page_body
    font_dir = re.search(rb"/Font\s*<<(.*?)>>", res, re.S)
    if not font_dir:
        font_ref = re.search(rb"/Font\s+(\d+)\s+0\s+R", res)
        if font_ref:
            font_dir = re.search(rb"<<(.*?)>>", objs.get(int(font_ref.group(1)), b""), re.S)
    font_cmaps: dict[str, dict[int, str]] = {}
    if font_dir:
        for name, num in re.findall(rb"/(\w+)\s+(\d+)\s+0\s+R", font_dir.group(1)):
            fobj = objs.get(int(num), b"")
            tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", fobj)
            cmap_data = _stream_of(objs[int(tu.group(1))]) if tu and int(tu.group(1)) in objs else None
            font_cmaps[name.decode()] = _parse_tounicode(cmap_data)

    # ---- image placement.  The XObject is called /Image1 on the three small
    # cards and /Im0 on the passport, so match any name.  The image's *device*
    # transform is recorded from the CTM in force at the Do, which is what later
    # converts a text position back into background-image pixels.
    ctm: tuple[float, ...] = IDENTITY
    stack: list[tuple[float, ...]] = []
    image_ctm: tuple[float, ...] | None = None
    for m in _TOKEN.finditer(content):
        if m.group("q"):
            stack.append(ctm)
        elif m.group("Q"):
            ctm = stack.pop() if stack else IDENTITY
        elif m.group("cm"):
            ctm = _mul(ctm, tuple(float(m.group(f"m{i}")) for i in range(1, 7)))
        elif m.group("do"):
            image_ctm = ctm
            break
    if image_ctm is None:
        raise ValueError(f"could not locate the image placement in {pdf_path}")
    ia, ib, ic, id_, ie, if_ = image_ctm

    img_w = img_h = 0
    for _, body in objs.items():
        if b"/Subtype" in body and b"/Image" in body:
            mw = re.search(rb"/Width\s+(\d+)", body)
            mh = re.search(rb"/Height\s+(\d+)", body)
            if mw and mh:
                img_w, img_h = int(mw.group(1)), int(mh.group(1))
                break

    # Device (page) units are points, so this converts a length measured in
    # device space into background-image pixels.  Font sizes come out of the
    # text state in device space, so they need the same factor - reporting them
    # raw makes every string render about 1.5x too small.
    px_per_device = img_w / abs(ia) if ia else 1.0

    def to_pixels(dev_x: float, dev_y: float) -> tuple[float, float]:
        """Map a device (page) point into background-image pixel coordinates.

        ``v`` is the image's own unit-square coordinate, whose zero row lands at
        the *larger* device y on these cards: the producer wrote the image with
        an inverted row order, so it is flipped back here.  Verified against
        all four cards - see ``tests/test_photo_regions.py`` for the assertions
        that pin the resulting field order (PAN number above name above father's
        name above date of birth, and so on).
        """
        det = ia * id_ - ib * ic
        u = ((dev_x - ie) * id_ - (dev_y - if_) * ic) / det
        v = (ia * (dev_y - if_) - ib * (dev_x - ie)) / det
        return u * img_w, (1.0 - v) * img_h

    # ---- walk the content stream, tracking CTM and the full text state
    runs: list[TextRun] = []
    dropped = 0
    ctm = IDENTITY
    stack = []
    tm = tlm = IDENTITY
    leading = 0.0
    size = 0.0
    font = ""
    cmap: dict[int, str] = {}
    color: tuple[int, int, int] = (0, 0, 0)
    pending: str | None = None

    for m in _TOKEN.finditer(content):
        if m.group("q"):
            stack.append(ctm)
        elif m.group("Q"):
            ctm = stack.pop() if stack else IDENTITY
        elif m.group("cm"):
            ctm = _mul(ctm, tuple(float(m.group(f"m{i}")) for i in range(1, 7)))
        elif m.group("BT"):
            tm = tlm = IDENTITY
        elif m.group("Tm"):
            tm = tlm = tuple(float(m.group(f"t{i}")) for i in range(1, 7))
        elif m.group("Td"):
            tx, ty = float(m.group("d1")), float(m.group("d2"))
            if m.group(0).rstrip().endswith("TD"):
                leading = -ty
            tlm = _mul(_translate(tx, ty), tlm)
            tm = tlm
        elif m.group("Tstar"):
            tlm = _mul(_translate(0.0, -leading), tlm)
            tm = tlm
        elif m.group("TL"):
            leading = float(m.group("lead"))
        elif m.group("Tf"):
            font = m.group("fname")
            size = float(m.group("fsize"))
            cmap = font_cmaps.get(font, {})
        elif m.group("rg"):
            color = (
                int(round(float(m.group("r")) * 255)),
                int(round(float(m.group("g")) * 255)),
                int(round(float(m.group("b")) * 255)),
            )
        elif m.group("tj"):
            pending = _decode_tj(m.group("tjbody"), cmap)
        elif m.group("th"):
            pending = _decode_str(m.group("top"), cmap)
        else:
            continue

        if pending is not None:
            text = pending
            pending = None
            if not text.strip():
                continue
            trm = _mul(ctm, tm)
            px, py = to_pixels(trm[4], trm[5])
            # The page can carry text outside the card - the DL writes a stray
            # "RTO Delhi" in the white space above it.  Those runs would render
            # off-image, so they are page furniture rather than card content.
            if not (-4 <= px <= img_w + 4 and -4 <= py <= img_h + 4):
                dropped += 1
                continue
            size_px = size * _scale_of(trm) * px_per_device
            runs.append(
                TextRun(
                    x=px,
                    y=py,
                    size=size_px,
                    text=text,
                    color=color,
                    font=font,
                    flipped=trm[3] < 0,
                )
            )

    return {
        "source_pdf": str(pdf_path),
        "image_size": [img_w, img_h],
        "placement": list(image_ctm),
        "off_card_runs_dropped": dropped,
        "runs": [r.to_dict() for r in runs],
    }


TARGETS = {
    "pan": SAMPLE_DATA / "PAN" / "PAN1.pdf",
    "aadhaar": SAMPLE_DATA / "AADHAR" / "AADHAR.pdf",
    "driving_license": SAMPLE_DATA / "DL" / "DL.pdf",
    "passport": SAMPLE_DATA / "passport" / "passport_final_database.pdf",
}


def main() -> None:
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, pdf in TARGETS.items():
        layout = extract_layout(pdf)
        (LAYOUT_DIR / f"{name}.json").write_text(
            json.dumps(layout, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print(f"{name:16s} {layout['image_size']}  {len(layout['runs']):3d} runs")


if __name__ == "__main__":
    main()
