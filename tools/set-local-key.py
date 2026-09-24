#!/usr/bin/env python3
"""Update only this worktree's EvoMap key, using a hidden terminal prompt."""
import getpass
import json
from pathlib import Path
import os
import sys

from dotenv import set_key


def main():
    if not sys.stdin.isatty():
        sys.exit('Run this command in your terminal to enter the key without echo.')
    root = Path(__file__).resolve().parents[1]
    env_file = root / '.env'
    if env_file.is_symlink():
        sys.exit('Refusing to modify a .env symlink outside this worktree.')
    try:
        key = getpass.getpass('New EvoMap API key (hidden): ').strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit('\nCancelled; key unchanged.')
    if not key:
        sys.exit('Empty key; nothing changed.')
    os.umask(0o077)
    if not env_file.exists():
        env_file.write_text((root / '.env.example').read_text())
    env_file.chmod(0o600)
    set_key(str(env_file), 'BEEPLAY_EVOMAP_KEYS', json.dumps([key]), quote_mode='always')
    env_file.chmod(0o600)
    print('Saved the new key to this worktree’s ignored .env. Restart the local app to use it.')


if __name__ == '__main__':
    main()
