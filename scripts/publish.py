#!/usr/bin/env python3
"""Commit project changes and push using your existing Git authentication."""
import argparse
from pathlib import Path
import subprocess


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip()
    if not branch:
        parser.error('Check out a branch before publishing.')
    print('Review changes carefully; never commit credentials or inventory data:')
    run('git', 'status', '--short', cwd=root)
    if input(f'Commit all non-ignored changes and push {branch} to origin? Type yes: ') != 'yes':
        raise SystemExit('Cancelled.')
    run('git', 'add', '--all', cwd=root)
    run('git', 'commit', '-m', args.message, cwd=root)
    run('git', 'push', '-u', 'origin', branch, cwd=root)


if __name__ == '__main__':
    main()
