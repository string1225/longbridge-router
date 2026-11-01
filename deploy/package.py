"""Package maintained sources with safe POSIX permissions."""

import argparse
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    names = [
        "router",
        "deploy",
        "skills",
        "docs",
        "tests",
        "README.md",
        "requirements.lock",
        "pyproject.toml",
        "LICENSE",
    ]
    with tarfile.open(args.output, "w:gz") as archive:
        for name in names:
            source = root / name
            files = sorted(source.rglob("*")) if source.is_dir() else [source]
            for source_file in files:
                if not source_file.is_file() or "__pycache__" in source_file.parts:
                    continue
                entry = archive.gettarinfo(
                    str(source_file), source_file.relative_to(root).as_posix()
                )
                entry.mode = 0o644
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = "root"
                with source_file.open("rb") as content:
                    archive.addfile(entry, content)
    print("Release archive prepared")


if __name__ == "__main__":
    main()
