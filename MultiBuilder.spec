# PyInstaller spec for Multi Builder.  Build with:  python -m PyInstaller --noconfirm MultiBuilder.spec
# ts_rom_tool comes from the ts_rom_tool git submodule and is compiled into the program.
import os, sys, subprocess

here = os.path.abspath(SPECPATH)
ts_dir = os.path.join(here, 'ts_rom_tool')
if not os.path.isfile(os.path.join(ts_dir, 'ts_rom_tool.py')):
    raise SystemExit('ts_rom_tool is missing: run  git submodule update --init')

# record which ts_rom_tool went into this build (shown by  MultiBuilder --version  and in the log)
with open(os.path.join(ts_dir, 'ts_rom_tool.py'), encoding='utf-8') as f:
    ts_version = f.readline().lstrip('# ').strip()
try:
    commit = subprocess.run(['git', '-C', ts_dir, 'rev-parse', '--short', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
except OSError:
    commit = ''
if commit:
    ts_version += ' (%s)' % commit
os.makedirs(os.path.join(here, 'build'), exist_ok=True)
version_file = os.path.join(here, 'build', 'ts_rom_tool_version.txt')
with open(version_file, 'w', encoding='utf-8') as f:
    f.write(ts_version)

a = Analysis(['multibuilder.py'], pathex=[ts_dir], hiddenimports=['ts_rom_tool'],
             datas=[(version_file, '.')], excludes=['numpy', 'scipy', 'PIL', 'matplotlib'])
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MultiBuilder', console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name='MultiBuilder')
    app = BUNDLE(coll, name='MultiBuilder.app', bundle_identifier='com.twistedsymphony.multibuilder')
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MultiBuilder', console=False, upx=False)
    if sys.platform == 'win32':
        # a windowed .exe has no console, so Windows also gets a command-line twin
        cli = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MultiBuilderCLI', console=True, upx=False)
