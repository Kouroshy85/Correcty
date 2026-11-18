"""Generate the Correcty C monogram for the Windows installer (requires Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def main():
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 1023, 1023), radius=256, fill="#e11d48")
    font_path = Path("C:/Windows/Fonts/segoeuib.ttf")
    font = ImageFont.truetype(str(font_path), 800) if font_path.exists() else ImageFont.load_default(size=800)
    draw.text((512, 480), "C", anchor="mm", font=font, fill="white")
    image.save(Path(__file__).with_name("correcty.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

if __name__ == "__main__":
    main()
