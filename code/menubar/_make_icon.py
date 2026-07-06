"""
生成菜单栏图标：git 分叉树图标。
36×36 黑色 PNG，透明背景；通过 NSImage.setTemplate_(True) 标记后，
macOS 会在浅色模式渲染黑色、深色模式渲染白色。

# 人工编写
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 36          # 36×36 px = 18 pt @2x retina
BG = (0, 0, 0, 0)  # 透明
FG = (0, 0, 0, 255)  # 黑色实线

img = Image.new("RGBA", (SIZE, SIZE), BG)
d = ImageDraw.Draw(img)

# git branch: 左侧主干 + 右上分支
left_x = 11
top_y = 8
mid_y = 18
bottom_y = 27
right_x = 25
dot_r = 3

d.line([(left_x, bottom_y), (left_x, top_y)], fill=FG, width=3)
d.line([(left_x, mid_y), (right_x, top_y)], fill=FG, width=3)

for x, y in ((left_x, bottom_y), (left_x, top_y), (right_x, top_y)):
    d.ellipse(
        [x - dot_r, y - dot_r, x + dot_r, y + dot_r],
        fill=FG,
    )

out = Path(__file__).parent / "icon.png"
img.save(out)
print(f"✓ icon saved: {out}  ({SIZE}×{SIZE})")
