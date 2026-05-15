"""
create_icon.py — Generates RDC Explorer app icon
Produces: assets/icon.ico (Windows), assets/icon.icns (Mac), assets/icon.png
Run once before building: python assets/create_icon.py
Requires: pip install pillow
"""
from PIL import Image, ImageDraw, ImageFont
import struct, os, io

SIZES = [16, 32, 48, 64, 128, 256]
OUT = os.path.dirname(os.path.abspath(__file__))


def make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 10)
    r = size // 6
    # Background rounded rect
    d.rounded_rectangle([pad, pad, size - pad, size - pad],
                        radius=r, fill=(30, 80, 140, 255))
    # "R" letter
    fs = int(size * 0.55)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fs)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "R", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    d.text((x, y), "R", fill=(255, 255, 255, 255), font=font)
    return img


def save_ico(path: str):
    frames = [make_frame(s) for s in [16, 32, 48, 64, 128, 256]]
    frames[0].save(path, format="ICO", sizes=[(s, s) for s in [16, 32, 48, 64, 128, 256]],
                   append_images=frames[1:])
    print(f"  Saved: {path}")


def save_icns(path: str):
    """Create a minimal .icns by embedding a 512×512 PNG."""
    img = make_frame(512)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    # ic09 = 512×512 PNG
    icon_type = b'ic09'
    chunk = icon_type + struct.pack('>I', 8 + len(png_data)) + png_data
    header = b'icns' + struct.pack('>I', 8 + len(chunk))
    with open(path, 'wb') as f:
        f.write(header + chunk)
    print(f"  Saved: {path}")


def save_png(path: str, size: int = 256):
    make_frame(size).save(path, format="PNG")
    print(f"  Saved: {path}")


if __name__ == "__main__":
    print("Generating icons...")
    save_ico(os.path.join(OUT, "icon.ico"))
    save_icns(os.path.join(OUT, "icon.icns"))
    save_png(os.path.join(OUT, "icon.png"))
    print("Done.")
