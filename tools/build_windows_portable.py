"""Assemble the Windows x64 zip using upstream runtime archives and LLVM."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.14.9"
PYTHON_ABI = "314"
QT_PACKAGES = {
    "shiboken6": "6.12.0",
    "PySide6_Essentials": "6.12.0",
    "PySide6_Addons": "6.12.0",
    "PySide6_WebEngine": "6.12.0.140",
    "PySide6_Pdf": "6.12.0.140",
    "cryptography": "50.0.2",
    "cffi": "2.1.1",
    "pycparser": "3.12",
}


def fetch(url, target):
    with urlopen(url, timeout=120) as source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return target


def wheel_rank(filename):
    """Rank a wheel for the bundled CPython: exact ABI, then the newest compatible abi3, then pure Python."""
    if not filename.endswith(".whl"):
        return None
    python, abi, platform = filename[:-4].split("-")[-3:]
    minor = int(PYTHON_ABI[1:])
    if platform == "win_amd64" and python == abi == f"cp{PYTHON_ABI}":
        return (3, 0)
    if platform == "win_amd64" and abi == "abi3" and python.startswith("cp3") and int(python[3:]) <= minor:
        return (2, int(python[3:]))
    if platform == "any" and abi == "none" and python.startswith("py3"):
        return (1, 0)
    return None


def wheel(work, name, version):
    with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        release = json.load(response)
    item = max((item for item in release["urls"] if wheel_rank(item["filename"])),
               key=lambda item: wheel_rank(item["filename"]))
    path = fetch(item["url"], work / item["filename"])
    with path.open("rb") as data:
        if file_digest(data, "sha256").hexdigest() != item["digests"]["sha256"]:
            raise RuntimeError(f"Checksum mismatch for {path.name}")
    return path


def launcher(work, bundle):
    exports = {
        "kernel32": "GetModuleFileNameW\nGetCommandLineW\nExitProcess",
        f"python{PYTHON_ABI}": "Py_Main",
    }
    imports = []
    for library, functions in exports.items():
        definition = work / f"{library}.def"
        definition.write_text(f"LIBRARY {library}.dll\nEXPORTS\n{functions}\n", encoding="ascii")
        target = work / f"{library}.lib"
        subprocess.run(["llvm-dlltool", "-m", "i386:x86-64", "-d", str(definition), "-l", str(target)], check=True)
        imports.append(str(target))
    compiled = work / "launcher.obj"
    subprocess.run(["clang", "--target=x86_64-pc-windows-msvc", "-ffreestanding", "-fno-stack-protector",
                    "-fno-builtin", "-c", str(ROOT / "tools/windows_launcher.c"), "-o", str(compiled)], check=True)
    shutil.copy2(ROOT / "assets/orbit.ico", work / "orbit.ico")
    (work / "orbit.rc").write_text('1 ICON "orbit.ico"\n', encoding="ascii")
    resource = work / "orbit.res"
    subprocess.run(["llvm-rc", "/fo", str(resource), "orbit.rc"], cwd=work, check=True)
    subprocess.run(["lld-link", "/entry:mainCRTStartup", "/subsystem:windows", "/nodefaultlib", "/machine:x64",
                    f'/out:{bundle / "Orbit Tabs.exe"}', str(compiled), str(resource), *imports], check=True)


def main():
    for command in ("llvm-dlltool", "clang", "llvm-rc", "lld-link"):
        if not shutil.which(command):
            raise SystemExit(f"{command} is required to build the Windows launcher.")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / "Orbit-Tabs-Windows-x64.zip"
    with tempfile.TemporaryDirectory(prefix="orbit-windows-") as temp:
        work = Path(temp)
        bundle = work / "Orbit Tabs"
        bundle.mkdir()
        filename = f"python-{PYTHON_VERSION}-embed-amd64.zip"
        with ThreadPoolExecutor(max_workers=6) as pool:
            runtime = pool.submit(fetch, f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{filename}", work / filename)
            dependencies = [pool.submit(wheel, work, name, version) for name, version in QT_PACKAGES.items()]
            with ZipFile(runtime.result()) as archive:
                archive.extractall(bundle)
            for dependency in dependencies:
                path = dependency.result()
                with ZipFile(path) as archive:
                    archive.extractall(bundle)
                print("Bundled", path.name, flush=True)
        for source in ("orbit_embedded.py", "orbit_wall.py", "orbit_theme.py", "orbit_license.py", "orbit_covers.py", "orbit_secure.py", "orbit_common.py", "orbit-course-qa.user.js", "README.md", "LICENSE.md"):
            shutil.copy2(ROOT / source, bundle)
        (bundle / "assets").mkdir()
        shutil.copy2(ROOT / "assets" / "miso-rainbow.png", bundle / "assets")
        launcher(work, bundle)
        with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=4) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(work))
    print(output)


if __name__ == "__main__":
    main()
