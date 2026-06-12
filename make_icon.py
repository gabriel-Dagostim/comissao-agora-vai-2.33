"""
Gera logo1.ico a partir de static/img/logo1.png para usar como ícone do atalho.
Execute uma vez: python make_icon.py
Requer: pip install Pillow
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Instale o Pillow: pip install Pillow")
    raise

BASE = Path(__file__).resolve().parent
SRC = BASE / "static" / "img" / "logo1.png"
OUT = BASE / "logo1.ico"

SIZES = [(256, 256), (48, 48), (32, 32), (16, 16)]

if not SRC.exists():
    print(f"Arquivo não encontrado: {SRC}")
    raise SystemExit(1)

img = Image.open(SRC)
if img.mode in ("RGBA", "P"):
    img = img.convert("RGBA")
else:
    img = img.convert("RGBA")
img.save(OUT, format="ICO", sizes=SIZES)
print(f"Icone criado: {OUT}")
