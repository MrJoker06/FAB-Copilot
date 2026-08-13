"""Generate the reviewed, deterministic local OCR gold assets (no network)."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pymupdf

ROOT = Path(__file__).resolve().parent.parent / "evaluations" / "ocr_samples"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
NAMES = {
    "chinese.png",
    "english.png",
    "device.png",
    "table.png",
    "formula.png",
    "multi.tiff",
    "scanned.pdf",
    "mixed.pdf",
}
STAGING = {f".staging-{name}" for name in NAMES}
CLEANUP = {
    "english-device.svg", "formula.svg", "table.svg", ".staging-work.tiff",
    ".staging-x.tiff", "work.tiff", "x.tiff",
}


def _safe(name: str) -> Path:
    root = ROOT.resolve()
    target = ROOT / name
    if name not in NAMES | STAGING or target.is_symlink() or root not in target.resolve().parents:
        raise RuntimeError("unsafe OCR asset target")
    return target


def _image(text: str, size=(1000, 260)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((35, 80), text, fill="black", font=ImageFont.truetype(FONT, 58))
    return image


def main() -> None:
    if not FONT.is_file():
        raise RuntimeError(f"required fixed font missing: {FONT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    if ROOT.is_symlink():
        raise RuntimeError("unsafe OCR asset root")
    for name in (*CLEANUP, *STAGING):
        target = ROOT / name
        if target.exists() and not target.is_symlink():
            target.unlink()
    staged = {name: _safe(f".staging-{name}") for name in NAMES}
    chinese = _image("中文 检查 通过")
    english = _image("ETCH EQ-01 PASS")
    device = _image("设备 EQ-01 检查 PASS")
    table = Image.new("RGB", (1000, 360), "white")
    draw = ImageDraw.Draw(table)
    font = ImageFont.truetype(FONT, 54)
    for xy, text in (
        ((40, 50), "项目"),
        ((500, 50), "结果"),
        ((40, 210), "TEMP"),
        ((500, 210), "PASS"),
    ):
        draw.text(xy, text, fill="black", font=font)
    formula = _image("E=mc2")
    for name, image in (
        ("chinese.png", chinese),
        ("english.png", english),
        ("device.png", device),
        ("table.png", table),
        ("formula.png", formula),
    ):
        image.save(staged[name], "PNG")
    # Reopen PNGs so their previous PNG encoder state cannot leak into TIFF.
    with Image.open(staged["chinese.png"]) as source:
        first = source.convert("RGB")
    with Image.open(staged["device.png"]) as source:
        second = source.convert("RGB")
    first.save(staged["multi.tiff"], "TIFF", save_all=True, append_images=[second], compression="raw")
    for name, pages in (("scanned.pdf", [device]), ("mixed.pdf", [device])):
        document = pymupdf.open()
        if name == "mixed.pdf":
            native = document.new_page()
            native.insert_text((72, 72), "Native PDF text page retained for mixed OCR validation.")
        for image in pages:
            page = document.new_page(width=image.width, height=image.height)
            data = io.BytesIO()
            image.save(data, "PNG")
            page.insert_image(page.rect, stream=data.getvalue())
        document.save(staged[name], reproducible=True, no_new_id=True)
        document.close()
    for name in ("chinese.png", "english.png", "device.png", "table.png", "formula.png"):
        with Image.open(staged[name]) as image:
            if image.format != "PNG" or image.size[0] <= 0:
                raise RuntimeError("invalid staged PNG")
    with Image.open(staged["multi.tiff"]) as image:
        if image.format != "TIFF" or image.n_frames != 2:
            raise RuntimeError("invalid staged TIFF")
    for name, expected_pages in (("scanned.pdf", 1), ("mixed.pdf", 2)):
        document = pymupdf.open(staged[name])
        pages = len(document)
        document.close()
        if pages != expected_pages:
            raise RuntimeError("invalid staged PDF")
    for name in NAMES:
        staged[name].replace(_safe(name))
    if not all(_safe(name).is_file() for name in NAMES):
        raise RuntimeError("missing generated asset")
    print("\n".join(f"{name} {hashlib.sha256(_safe(name).read_bytes()).hexdigest()}" for name in sorted(NAMES)))


if __name__ == "__main__":
    main()
