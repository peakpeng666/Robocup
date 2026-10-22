#!/usr/bin/env python3
"""下载当前分支清单中的公开 PDF；--list 只列清单，--only KEY 只下载一项。

下载先写临时文件，验证完成后原子替换；失败返回非零，不保留半成品。
PDF 结构检查仅防止常见错误页/截断，不代替来源真实性或版权授权审查。
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "fetch-manifest.json"
OUT = ROOT / "downloads"


def validate_pdf(path):
    """Reject empty/small responses, HTML error pages and common truncation."""
    size = path.stat().st_size
    if size < 10000:
        raise ValueError(f"文件过小({size}B)，疑似错误响应")
    with path.open("rb") as f:
        if not f.read(5) == b"%PDF-":
            raise ValueError("响应不是 PDF（缺少 %PDF- 文件头）")
        f.seek(max(0, size - 1024))
        if b"%%EOF" not in f.read():
            raise ValueError("PDF 缺少结束标记，可能未下载完整")


def download(item, dest):
    """Never replace the final destination until the new response is validated."""
    temp_path = None
    try:
        req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=dest.name + ".", suffix=".part", delete=False) as f:
                temp_path = Path(f.name)
                count = 0
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    count += len(chunk)
                    f.write(chunk)
            length = response.headers.get("Content-Length")
            if length is not None and count != int(length):
                raise ValueError(f"下载长度不符：预期 {length}B，收到 {count}B")
        validate_pdf(temp_path)
        os.replace(temp_path, dest)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="仅列出当前分支的下载清单")
    group.add_argument("--only", metavar="KEY", help="只下载指定 key")
    args = parser.parse_args(argv)
    try:
        items = json.loads(MANIFEST.read_text(encoding="utf-8"))["items"]
        keys, names = set(), set()
        for item in items:
            key, name = item["key"], item["file"]
            if not name or Path(name).name != name or name in (".", "..") or "\\" in name:
                raise ValueError(f"非法输出文件名: {name!r}")
            if key in keys or name in names:
                raise ValueError("清单存在重复 key 或文件名")
            keys.add(key)
            names.add(name)
            if not item["url"].startswith("https://"):
                raise ValueError(f"下载地址必须使用 HTTPS: {key}")
        if args.only is not None:
            items = [it for it in items if it["key"] == args.only]
            if not items:
                parser.error(f"未知 key: {args.only}")
        if args.list:
            for it in items:
                print(f"{it['key']:<28} {it['title']}\n{'':<28} {it['url']}")
            return 0
        OUT.mkdir(parents=True, exist_ok=True)
        gitignore = OUT / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] 清单或输出目录错误: {exc}")
        return 1

    ok, fail = 0, 0
    for it in items:
        dest = OUT / it["file"]
        if dest.exists():
            try:
                validate_pdf(dest)
            except (OSError, ValueError):
                print(f"[redo] {it['key']} 既有文件未通过验证，重新下载")
            else:
                print(f"[skip] {it['key']} 已通过 PDF 基础验证")
                ok += 1
                continue
        try:
            print(f"[get ] {it['key']} <- {it['url']}")
            download(it, dest)
            print(f"[ ok ] {it['key']} -> {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
            ok += 1
        except Exception as exc:  # Network/protocol failures must fail this item, not abort the batch.
            print(f"[FAIL] {it['key']}: {exc}")
            fail += 1
    print(f"\n完成：{ok} 成功，{fail} 失败。失败的按清单 URL 手动核查或重试。")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
