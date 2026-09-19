"""Deterministic packaging from reviewed files; never glob personal outputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from genealogy import __version__
STAMP=(2026,9,19,0,0,0)
EPOCH='1789776000'


def zip_files(path,files):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data,executable in sorted(files):
            info=zipfile.ZipInfo(name,STAMP);info.create_system=3;info.external_attr=(0o100755 if executable else 0o100644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)


def main():
    names=json.loads((ROOT/'release-files.json').read_text())
    if names!=sorted(set(names)):raise ValueError('Release list must be sorted and unique')
    files=[];hashes={}
    for name in names:
        path=ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or not path.is_file():raise ValueError('Unsafe or missing release file: '+name)
        data=path.read_bytes();files.append((name,data,name.endswith('.command')));hashes[name]=hashlib.sha256(data).hexdigest()
    prefix='genealogy-toolkit-'+__version__;destination=ROOT/'artifacts'/'release';destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='genealogy-release-') as directory:
        temp=Path(directory);source=temp/prefix;source.mkdir();out=temp/'output';out.mkdir()
        for name,data,executable in files:
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o755 if executable else 0o644)
        zip_files(out/(prefix+'-source.zip'),[(prefix+'/'+name,data,mode) for name,data,mode in files])
        demo=[('genealogy-toolkit-demo/'+name.removeprefix('examples/demo/'),data,False) for name,data,_ in files if name.startswith('examples/demo/')]
        demo += [('genealogy-toolkit-demo/LICENSE.txt',(ROOT/'LICENSE').read_bytes(),False),('genealogy-toolkit-demo/ASSETS.txt',(ROOT/'ASSETS.md').read_bytes(),False)]
        zip_files(out/(prefix+'-demo.zip'),demo)
        env=dict(os.environ,SOURCE_DATE_EPOCH=EPOCH,PYTHONHASHSEED='0')
        subprocess.run([sys.executable,'-m','build','--wheel','--no-isolation','--outdir',str(out)],cwd=source,env=env,check=True,stdout=subprocess.DEVNULL)
        provenance={'project':'Evidence-first Genealogy','version':__version__,'sourceFiles':hashes,'fixture':'Wholly invented Larkhaven workshop question; no provider data or identifiers in the demo','buildEpoch':EPOCH,'demo':'The checked-in readable snapshot is packaged byte-for-byte. Run genealogy demo to regenerate the workflow with new local UUIDs/timestamps.'}
        (out/'release-provenance.json').write_text(json.dumps(provenance,indent=2,sort_keys=True)+'\n')
        (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(out.iterdir())))
        for path in out.iterdir():shutil.copyfile(path,destination/path.name)
    print('Created release candidates in '+str(destination))

if __name__=='__main__':main()
