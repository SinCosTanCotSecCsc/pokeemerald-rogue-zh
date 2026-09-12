import json
import os

from PIL import Image, ImageDraw, ImageFont

os.chdir(os.path.dirname(__file__))

with open("../charmap.txt", "r", -1, "utf8") as reader:
  lines = reader.read().splitlines()

char_map = {}
max_code = -1

start = False
for line in lines:
  line = line.split("@")[0].strip()
  if not line:
    continue

  char, code = line.rsplit("=", 1)
  char = char.strip()
  code = int.from_bytes(bytes.fromhex(code), "big")

  if char.startswith("'") and char.endswith("'"):
    char = char[1:-1]
    if char == "\\n":
      char = "\n"
    elif char == "\\'":
      char = "'"
  else:
    char = f"{{{char}}}"

  if ord(char[0]) >= 0x4E00:
    start = True
  if not start:
    continue

  char_map[code] = char
  max_code = max(max_code, code)

height = ((max_code >> 4) - 0x30 + 1) * 16

configurations = [
  {
    "font_size": 12,
    "font_path": "C:/Windows/Fonts/simsun.ttc",
    "output_path": "chinese_normal.png",
    "y_offset": 0,
  },
  {
    "font_size": 10,
    "font_path": "C:/Users/Xzonn/AppData/Local/Microsoft/Windows/Fonts/DinkieBitmap-9px.ttf",
    "output_path": "chinese_small.png",
    "y_offset": 3,
  },
]

colors = (0x90, 0xC8, 0xFF, 0x38, 0x38, 0x38, 0xD8, 0xD8, 0xD8, 0xFF, 0xFF, 0xFF)
palette = Image.new("P", (8, 8))
palette.putpalette(colors)

for config in configurations:
  font_size: int = config["font_size"]
  font_path: str = config["font_path"]
  output_path: str = config["output_path"]
  y_offset: int = config["y_offset"]

  image = Image.new("RGB", (256, height), "#90c8ff")

  image_draw = ImageDraw.Draw(image)
  font = ImageFont.truetype(font_path, font_size)

  for code, char in char_map.items():
    high, low = code >> 8, code & 0xFF
    offset = 1 if high < 0x06 else (2 if high < 0x1B else 3)
    y = (high - offset) * 0x100 + (low >> 4) * 0x10
    x = (low & 0x0F) * 16
    tile = Image.new("RGBA", (font_size, font_size + 2))
    draw = ImageDraw.Draw(tile)
    for y2 in (1, 0):
      for x2 in (1, 0):
        draw.text((x2, y2), f"{char}　　黑鼠龙龟", "#383838" if x2 + y2 == 0 else "#d8d8d8", font, "lt")
    box = tile.getbbox()
    if char in "：；？！，．、。" and box:
      new_tile = Image.new("RGBA", tile.size)
      tile = tile.crop((0, box[1], tile.width, box[3]))
      new_tile.paste(tile, (0, (new_tile.height - tile.height) - 1))
      tile = new_tile

    image_draw.rectangle((x, y + y_offset, x + font_size - 1, y + font_size + y_offset), "#ffffff")
    image.paste(tile, (x, y + y_offset), tile)

  image = image.quantize(palette=palette, dither=Image.Dither.NONE)
  image.save(f"../graphics/fonts/{output_path}")
