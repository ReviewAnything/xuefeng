#!/usr/bin/env python3
"""生成 tabBar 图标 PNG（P3-A）。

为什么用脚本生成而不是找现成图标包：
  - uni-app 的 tabBar 只吃**本地图片路径**，不接受 SVG/data URI（小程序端尤其严格），
    所以页面内用的 SVG 图标系统不能直接复用到 tabBar，必须落成 PNG 资产。
  - 自己画 = 与页面内图标同一套几何（24×24 网格、1.7 线宽、圆头描边），视觉才一致，
    也不引入第三方素材的授权问题。

做法：在 4 倍画布上用「线段 + 端点圆点」模拟圆头描边，再 LANCZOS 下采样到 81×81，
边缘即为抗锯齿结果。

用法：
    /path/to/python frontend/scripts/gen_tabbar_icons.py
产物：
    frontend/src/static/tabbar/<name>.png        常态（灰）
    frontend/src/static/tabbar/<name>-on.png     选中（金）
"""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "static", "tabbar")
FINAL = 81           # uni-app 推荐 81×81（3 倍图 27px）
SS = 4               # 超采样倍数
CANVAS = FINAL * SS
GRID = CANVAS / 24.0  # 24×24 坐标系 -> 画布像素
LW = 1.7 * GRID       # 线宽（与 icons.js 的 stroke-width 一致）

NORMAL = (0x8a, 0x90, 0x9c, 255)
ACTIVE = (0xff, 0xd2, 0x4d, 255)


def P(x, y):
    return (x * GRID, y * GRID)


def stroke(d, pts, color, width=LW, closed=False):
    """圆头折线：线段 + 每个顶点画圆点，避免 PIL 默认方头端点。"""
    seq = list(pts) + ([pts[0]] if closed else [])
    d.line(seq, fill=color, width=int(round(width)), joint="curve")
    r = width / 2.0
    for (x, y) in seq:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def circle(d, cx, cy, r, color, width=LW):
    box = [cx * GRID - r * GRID, cy * GRID - r * GRID, cx * GRID + r * GRID, cy * GRID + r * GRID]
    d.ellipse(box, outline=color, width=int(round(width)))


def dot(d, cx, cy, r, color):
    box = [cx * GRID - r * GRID, cy * GRID - r * GRID, cx * GRID + r * GRID, cy * GRID + r * GRID]
    d.ellipse(box, fill=color)


def icon_target(d, c):
    circle(d, 12, 12, 8.2, c)
    circle(d, 12, 12, 3.6, c)
    dot(d, 12, 12, 0.9, c)


def icon_school(d, c):
    stroke(d, [P(12, 3.2), P(20.5, 8), P(3.5, 8)], c, closed=True)
    for x in (6, 10, 14, 18):
        stroke(d, [P(x, 10.6), P(x, 16.6)], c)
    stroke(d, [P(3.8, 20.4), P(20.2, 20.4)], c)


def icon_list(d, c):
    for y in (6.6, 12.0, 17.4):
        stroke(d, [P(8.6, y), P(19.6, y)], c)
        dot(d, 4.7, y, 0.85, c)


def icon_search(d, c):
    circle(d, 10.8, 10.8, 6.4, c)
    stroke(d, [P(15.6, 15.6), P(20.4, 20.4)], c)


def icon_user(d, c):
    circle(d, 12, 8.2, 3.7, c)
    # 肩部弧线：椭圆上半圈
    d.arc([4.8 * GRID, 14.8 * GRID, 19.2 * GRID, 25.6 * GRID], 180, 360, fill=c,
          width=int(round(LW)))


ICONS = {
    "verdict": icon_target,
    "recommend": icon_school,
    "plan": icon_list,
    "verify": icon_search,
    "me": icon_user,
}


def render(fn, color):
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    fn(ImageDraw.Draw(img), color)
    return img.resize((FINAL, FINAL), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in ICONS.items():
        render(fn, NORMAL).save(os.path.join(OUT, name + ".png"))
        render(fn, ACTIVE).save(os.path.join(OUT, name + "-on.png"))
        print("wrote", name, "→", OUT)


if __name__ == "__main__":
    main()
