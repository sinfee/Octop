"""Assemble an Octop portable ZIP with a prepared Windows 7 runtime."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import tomllib
import zipfile
from pathlib import Path


def overlay(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if relative.parts[0] == "bin" or "__pycache__" in relative.parts:
            # uv --target generates launchers bound to the build interpreter.
            continue
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Input contains a link: {path}")
        dest = target / relative
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif dest.exists():
            raise FileExistsError(f"Package inputs overlap: {dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--additional", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    templates = Path(__file__).resolve().parent / "templates"
    version = tomllib.loads((templates.parents[2] / "pyproject.toml").read_text("utf-8"))[
        "project"
    ]["version"]
    for path in (args.runtime / "python.exe", args.packages / "pywin32.pth", args.wheel):
        if not path.is_file():
            parser.error(f"Missing input: {path}")
    if not args.additional.is_dir():
        parser.error(f"Missing additional package directory: {args.additional}")
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f"Octop-portable-win7-x64-{version}.zip"
    with tempfile.TemporaryDirectory(dir=args.output) as temp:
        work = Path(temp)
        root = work / "Octop-win7-x64"
        runtime = root / "runtime"
        site_packages = runtime / "Lib" / "site-packages"
        overlay(args.runtime, runtime)
        overlay(args.packages, site_packages)
        overlay(args.additional, site_packages)
        packages = root / "packages"
        packages.mkdir()
        with zipfile.ZipFile(args.wheel) as wheel:
            wheel.extractall(packages)
        if not (packages / "octop" / "dashboard" / "index.html").is_file():
            raise ValueError("Octop wheel does not contain a built Dashboard")
        for filename in ("launch.py", "start.bat", "README.txt"):
            shutil.copyfile(templates / filename, root / filename)
        candidate = work / archive.name
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for path in sorted(root.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    out.write(path, path.relative_to(work).as_posix())
        candidate.replace(archive)
    print(archive)


if __name__ == "__main__":
    main()
