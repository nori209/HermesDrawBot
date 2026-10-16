#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$task_root"
tar --exclude='__pycache__' --exclude='*.pyc' -czf shopen-raffle.tar.gz \
    raffle tests deploy README.md requirements.txt .env.example .gitignore
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

roots = ['raffle', 'tests', 'deploy', 'README.md', 'requirements.txt', '.env.example', '.gitignore']
with ZipFile('shopen-raffle.zip', 'w', compression=ZIP_DEFLATED) as archive:
    for root in roots:
        path = Path(root)
        files = sorted(path.rglob('*')) if path.is_dir() else [path]
        for file in files:
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                archive.write(file, file.as_posix())
PY
printf 'Созданы %s/shopen-raffle.zip и shopen-raffle.tar.gz (без .env и базы)\n' "$task_root"
