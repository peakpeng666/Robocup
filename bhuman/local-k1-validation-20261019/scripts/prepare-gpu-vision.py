#!/usr/bin/env python3
"""Download the pinned official ORT wheel and extract C++ runtime libraries only.

Explicit maintenance action: does not install into Python or change system files.
The CUDA/cuDNN libraries are reused from the existing Isaac Lab environment.
"""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent / "runtime/onnxruntime-gpu-1.22.0"
URL = "https://files.pythonhosted.org/packages/4a/10/cd3e7e289f7b46eb93e38b5c90139f735bf1ea7f03d4b17ceb0e998e5bb6/onnxruntime_gpu-1.22.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
SHA256 = "d30c1512f22b1f01bacb4f177d49cbefd23e0f4bef56066f1282992d133e6ff8"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    wheel = ROOT / URL.rsplit("/", 1)[1]
    if not wheel.exists():
        partial = wheel.with_suffix(".download")
        with urllib.request.urlopen(URL, timeout=60) as source, partial.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        wheel = partial
    actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if actual != SHA256:
        raise RuntimeError("Downloaded wheel SHA256 mismatch: " + actual)
    final = ROOT / URL.rsplit("/", 1)[1]
    if wheel != final:
        wheel.rename(final)
    library = ROOT / "lib"
    library.mkdir(exist_ok=True)
    with zipfile.ZipFile(final) as archive:
        for name in archive.namelist():
            if name.startswith("onnxruntime/capi/libonnxruntime") or name.endswith(("/LICENSE", "/ThirdPartyNotices.txt")):
                with archive.open(name) as source, (library / Path(name).name).open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    for name in ["libonnxruntime.so", "libonnxruntime.so.1"]:
        link = library / name
        if not link.exists():
            link.symlink_to("libonnxruntime.so.1.22.0")
    print("Verified GPU C++ runtime: " + str(library))


if __name__ == "__main__":
    main()
