#!/usr/bin/env python3
"""Package the supported tools/configuration OTA subset, not a kernel upgrade."""
from pathlib import Path
import hashlib
import importlib.util
import tarfile

root = Path(__file__).resolve().parent
source = root / 'config/includes.chroot'
spec = importlib.util.spec_from_file_location('navin_logic', source / 'usr/local/lib/navin/navin_logic.py')
logic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logic)
archive = root / 'navin-update.tar.gz'
with tarfile.open(archive, 'w:gz') as output:
    for path in sorted(source.rglob('*')):
        name = path.relative_to(source).as_posix()
        if path.is_file() and not path.is_symlink() and logic.safe_patch_path(name):
            output.add(path, arcname=name, recursive=False)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n')
print('Packaged configuration/tools OTA; kernel and package upgrades require APT/new ISO.')