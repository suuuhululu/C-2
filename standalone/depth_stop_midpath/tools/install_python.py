"""Install the hash-locked wheels into this standalone, never the shared app."""
from pathlib import Path
import os,subprocess,sys,tempfile
from portable_runtime import PKG,python_site

def main():
    if sys.version_info[:2]!=(3,12):raise ValueError('Run setup.sh with Ubuntu 24.04 Python 3.12.')
    site,lock=python_site();marker=site/'installed-lock.sha256'
    if marker.is_file() and marker.read_text().strip()==lock:
        print('ISOLATED_PYTHON_LOCK_ALREADY_INSTALLED');return
    if site.exists():raise ValueError('Incomplete dependency directory: '+str(site))
    site.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='install-',dir=site.parent))
    result=subprocess.run([sys.executable,'-m','pip','install','--require-hashes','--only-binary=:all:',
                           '--no-compile','--target',str(staging),'-r',str(PKG/'requirements.lock')])
    if result.returncode:raise ValueError('Dependency install failed; original output above; partial files: '+str(staging))
    (staging/'installed-lock.sha256').write_text(lock+'\n')
    os.rename(staging,site)
    print('ISOLATED_PYTHON_LOCK_INSTALLED: '+str(site))

if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(2)
