#!/usr/bin/env python3
"""把 wot-design-uni 的 wd-icons.ttf 重新内嵌成 base64 样式。

为什么要这个脚本
----------------
wot 的 ``components/wd-icon/index.scss`` 用远程 ``@font-face``
（``https://at.alicdn.com/...woff2``）声明 ``wd-icons`` 字体。
但**微信小程序 WXSS 不支持远程 @font-face**，于是在小程序端：

* 渲染层报 ``Failed to load font ... net::ERR_CACHE_MISS``；
* ``wd-icon`` 的 1229 个字形（``\\eXXX`` 私有区码位）全部空白 ——
  wd-search 放大镜、wd-picker 箭头、wd-tag 关闭、wd-toast 图标、
  wd-collapse 箭头在真机/模拟器上都看不见。

因此把 wot 自带的 ``wd-icons.ttf``（与 CDN 版 sha256 一致）转成 base64，
写入 ``src/styles/wd-icons-font.css``，由 ``App.vue`` 全局 ``@import``，
在小程序里以 ``app.wxss`` 一次性生效：不联网、不需要域名白名单。

何时重跑
--------
升级 ``wot-design-uni`` 之后。字形有增删时字体文件会变，
不重跑就会出现「新图标空白」或「缺字形」。

用法
----
    python3 scripts/gen_wd_icons_font.py
"""

from __future__ import annotations

import base64
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TTF = ROOT / "node_modules" / "wot-design-uni" / "components" / "wd-icon" / "wd-icons.ttf"
OUT = ROOT / "src" / "styles" / "wd-icons-font.css"

HEADER = """/* ===========================================================================
   wot-design-uni 图标字体自托管（由 scripts/gen_wd_icons_font.py 生成，勿手改）
   ---------------------------------------------------------------------------
   背景：wot 的 wd-icon/index.scss 里 @font-face 指向 https://at.alicdn.com/...
        但【微信小程序 WXSS 不支持远程 @font-face】，导致：
          · 渲染层报 `Failed to load font ... net::ERR_CACHE_MISS`
          · wd-icon 的全部字形（\\eXXX 私有区码位）空白
            → wd-search 放大镜、wd-picker 箭头、wd-tag 关闭、wd-toast 图标、
              wd-collapse 箭头在真机上都看不见
   做法：把 wot 自带的 wd-icons.ttf 以 base64 内嵌，在 app 级声明同名 font-family。
        小程序支持 wxss 里的 base64 @font-face，因此不联网、不需域名白名单，
        H5 / 小程序同源生效。
   注意：字体只在此处声明【一次】（app.wxss）。不要塞进各组件 scoped style，
        否则每个 wxss 都会重复一份 base64（7 个组件 ≈ 500KB）。
   源文件 sha256: {sha}
   =========================================================================== */
@font-face {{
  font-family: 'wd-icons';
  src: url('data:font/ttf;base64,{b64}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
"""


def main() -> int:
    if not TTF.is_file():
        print(f"[x] 找不到字体文件：{TTF}", file=sys.stderr)
        print("    先执行 npm install（或确认 wot-design-uni 已安装）", file=sys.stderr)
        return 1

    raw = TTF.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEADER.format(sha=sha, b64=b64), encoding="utf-8")

    print(f"[ok] {TTF.name}  {len(raw)} bytes  sha256={sha[:16]}…")
    print(f"[ok] 写入 {OUT.relative_to(ROOT)}  {OUT.stat().st_size} bytes")
    print("     记得 npm run build:mp-weixin 重新编译，并在开发者工具里看图标是否出现。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
