"""Собирает экшен-анимацию «Кирито: замах мечом» из PNG-кадров в GIF / WebP / MP4."""
import os
import subprocess
import sys

from PIL import Image

FR = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(FR, "frames")
OUT = FR

# тайминг: стойка(3) -> замах(2) -> старт(2) -> середина(2) -> удар(2) -> FLASH(1) -> follow(3) -> отдых(6)
SEQ = (
    ["sword_01"] * 3
    + ["sword_02"] * 2
    + ["sword_03"] * 2
    + ["sword_04"] * 2
    + ["sword_05"] * 2
    + ["flash_01"] * 1
    + ["sword_06"] * 3
    + ["sword_07"] * 6
)
FPS = 10
DURATION_MS = 1000 // FPS
WIDTH = 640


def make_flash():
    """Белый flash-кадр: чёрный силуэт из кадра удара (классика аниме)."""
    im = Image.open(os.path.join(FRAMES, "sword_05.png")).convert("RGB")
    g = im.convert("L")
    sil = g.point(lambda p: 0 if p < 110 else 255)
    path = os.path.join(FRAMES, "flash_01.png")
    sil.save(path)
    print("flash:", path)


def load_frames():
    imgs = []
    for name in SEQ:
        im = Image.open(os.path.join(FRAMES, name + ".png")).convert("RGB")
        h = int(round(im.height * WIDTH / im.width / 2)) * 2
        imgs.append(im.resize((WIDTH, h), Image.LANCZOS))
    return imgs


def shared_palette(imgs):
    unique, seen = [], set()
    for im in imgs:
        key = im.tobytes()
        if key not in seen:
            seen.add(key)
            unique.append(im)
    big = Image.new("RGB", (WIDTH, sum(im.height for im in unique)))
    y = 0
    for im in unique:
        big.paste(im, (0, y))
        y += im.height
    return big.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=0)


def build_gif(imgs, pal):
    frames = [im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for im in imgs]
    path = os.path.join(OUT, "anime_swing.gif")
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=DURATION_MS, loop=0, disposal=2, optimize=True)
    print("GIF:", path, os.path.getsize(path) // 1024, "KB")


def build_webp(imgs):
    path = os.path.join(OUT, "anime_swing.webp")
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=DURATION_MS, loop=0, method=6, quality=85)
    print("WEBP:", path, os.path.getsize(path) // 1024, "KB")


def build_mp4(imgs):
    try:
        import imageio_ffmpeg
    except ImportError:
        print("MP4: imageio-ffmpeg не установлен, пропускаю")
        return
    seqdir = os.path.join(FR, "seq")
    os.makedirs(seqdir, exist_ok=True)
    for i, im in enumerate(imgs):
        im.save(os.path.join(seqdir, f"f_{i + 1:02d}.png"))
    path = os.path.join(OUT, "anime_swing.mp4")
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y", "-framerate", str(FPS),
        "-i", os.path.join(seqdir, "f_%02d.png"),
        "-vf", "scale=720:-2:flags=lanczos",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-movflags", "+faststart",
        path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print("MP4:", path, os.path.getsize(path) // 1024, "KB")
    else:
        print("MP4 error:", r.stderr[-800:])


def main():
    make_flash()
    imgs = load_frames()
    pal = shared_palette(imgs)
    build_gif(imgs, pal)
    build_webp(imgs)
    build_mp4(imgs)
    print("OK, кадров:", len(imgs))


if __name__ == "__main__":
    sys.exit(main())
