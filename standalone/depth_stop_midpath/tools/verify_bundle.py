"""Verify relative, immutable distribution files without importing vendor modules."""
from pathlib import Path
import hashlib,json,sys
root=Path(__file__).resolve().parents[1]
try:
    count=0
    for line in (root/'FILES.sha256').read_text().splitlines():
        expected,name=line.split('  ',1);p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file():raise ValueError('Missing or invalid bundle file: '+name)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('Bundle checksum mismatch: '+name)
        count+=1
    print(json.dumps(dict(status='BUNDLE_CHECKSUMS_PASS',files=count,GPU_SIM_started=False)))
except Exception as exc:
    print(str(exc),file=sys.stderr);sys.exit(2)
