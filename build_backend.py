"""Build the frozen backend with relay dependencies and runtime CA resources."""
from pathlib import Path
import runpy
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'build/deps'))
args=['pyinstaller','--noconfirm','--onefile','--console','--name','comic-backend',
      '--distpath',str(ROOT/'build/backend'),'--workpath',str(ROOT/'build/pyinstaller'),
      '--specpath',str(ROOT/'build'),'--paths',str(ROOT/'build/deps'),
      '--paths',str(ROOT/'backend/vendor'),'--icon',str(ROOT/'assets/icon.ico')]
# This Python distribution loads this resource from ssl.SSLContext.__new__.
# Preserve the runtime certificate policy when frozen rather than bypassing it.
runtime_ca=Path(sys.base_prefix)/'Lib/codex-rejected-cas.pem'
if runtime_ca.is_file():args.extend(['--add-data',str(runtime_ca)+':.'])
args.append(str(ROOT/'backend/server.py'));sys.argv=args
runpy.run_module('PyInstaller',run_name='__main__')
