#!/usr/bin/env python3
"""Apply a reviewed unified code patch after checking it can apply cleanly."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('patch', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip():
        parser.error('Commit or stash existing changes before applying a patch.')
    patch = str(args.patch.resolve())
    subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
    subprocess.run(['git', 'apply', patch], cwd=root, check=True)
    print('Patch applied. Review git diff, run tests, then publish.')


if __name__ == '__main__':
    main()
