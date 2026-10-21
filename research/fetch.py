#!/usr/bin/env python3
"""公开研究资料一键下载脚本（research/downloads/ 自动 git-ignore，幂等）。

用法：
    python3 research/fetch.py            # 下载全部
    python3 research/fetch.py --list     # 只列清单
    python3 research/fetch.py --only key # 只下某一项

只下载公开可获取的 PDF/文档；需要注册的资源（AMASS/ACCAD/Isaac Gym 等）
不在清单内，见 04-数据集与参考动作.md 的链接与说明。
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "fetch-manifest.json"
OUT = ROOT / "downloads"


def main():
    args = sys.argv[1:]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest["items"]

    if "--list" in args:
        for it in items:
            print(f"{it['key']:<28} {it['title']}\n{'':<28} {it['url']}")
        return

    if "--only" in args:
        key = args[args.index("--only") + 1]
        items = [it for it in items if it["key"] == key]
        if not items:
            sys.exit(f"未知 key: {key}")

    OUT.mkdir(exist_ok=True)
    gitignore = OUT / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")

    ok, fail = 0, 0
    for it in items:
        dest = OUT / it["file"]
        if dest.exists() and dest.stat().st_size > 10000:
            print(f"[skip] {it['key']} 已存在 ({dest.stat().st_size} bytes)")
            ok += 1
            continue
        print(f"[get ] {it['key']} <- {it['url']}")
        try:
            req = urllib.request.Request(it["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            size = dest.stat().st_size
            if size < 10000:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"文件过小({size}B)，疑似被拦")
            print(f"[ ok ] {it['key']} -> {dest.name} ({size/1e6:.1f} MB)")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {it['key']}: {e}")
            fail += 1
    print(f"\n完成：{ok} 成功，{fail} 失败。失败的按清单 URL 手动下载。")


if __name__ == "__main__":
    main()
