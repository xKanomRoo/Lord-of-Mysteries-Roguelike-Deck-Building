#!/usr/bin/env python3
"""Reassemble ordered upload chunks and verify the original SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path


def join_chunks(parts: list[Path], output: Path, expected_sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Expected SHA-256 must contain exactly 64 hexadecimal characters")
    if not parts:
        raise ValueError("At least one chunk is required")
    resolved_parts = [part.resolve() for part in parts]
    if len(set(resolved_parts)) != len(resolved_parts):
        raise ValueError("Duplicate chunk paths are not allowed")
    if any(not part.is_file() for part in resolved_parts):
        raise ValueError("Every chunk must be an existing file")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output already exists; it will not be overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    digest = hashlib.sha256()
    try:
        with partial.open("xb") as destination:
            for part in resolved_parts:
                with part.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        destination.write(block)
            destination.flush()
            os.fsync(destination.fileno())
        result = digest.hexdigest()
        if result != expected_sha256.lower():
            raise ValueError("SHA-256 mismatch: chunks are missing, reordered, or changed")
        # Hard-link installation refuses replacement, including a concurrent writer.
        os.link(partial, output)
        partial.unlink()
        return result
    except BaseException:
        # Never remove a partial file that existed before this invocation.
        if 'destination' in locals():
            partial.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parts", nargs="+", type=Path,
                        help="chunk paths in original numeric order (0000, 0001, …)")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sha256", required=True, help="SHA-256 measured from original archive before splitting")
    args = parser.parse_args(argv)
    try:
        digest = join_chunks(args.parts, args.output, args.sha256)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Verified SHA-256: {digest}")
    print(f"Reassembled: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
