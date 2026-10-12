#!/usr/bin/env python3
"""Self-test for Multi Builder: checks every kit in examples/ (and in a local kits/ folder, if you keep one), runs a small end-to-end build with made-up
ROMs, and builds every example kit for every donor PCB with made-up ROMs forged to the kit's CRCs.

  python tests/selftest.py                      test multibuilder.py from source
  python tests/selftest.py --program PATH       test a compiled program the same way
"""
import os, sys, json, zipfile, tempfile, subprocess, shutil, random, zlib, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import multibuilder as mb   # noqa: E402

fails = []


def check(cond, what):
    print(('  ok    ' if cond else '  FAIL  ') + what)
    if not cond:
        fails.append(what)


def kit_files_exist(kit):
    missing = []
    for gid, g in kit.games.items():
        variants = [g] + list(g.get('donor_overrides', {}).values())
        donors = kit.donor_ids() or [None]
        for v in variants:
            items = [x for st in v.get('steps', []) for x in st[1:]]
            for p in v.get('parts', {}).values():
                items += p if isinstance(p, list) else [p]
            for x in items:
                if isinstance(x, str) and x.startswith('kit:'):
                    for d in donors:
                        rel = x[4:].replace('{donor}', d or '')
                        if not os.path.exists(kit.kit_file(rel)):
                            missing.append('%s: %s' % (gid, rel))
    return sorted(set(missing))


def kit_paths():
    for top in ('kits', 'examples'):
        if not os.path.isdir(os.path.join(ROOT, top)):
            continue
        for d in sorted(os.listdir(os.path.join(ROOT, top))):
            if os.path.isdir(os.path.join(ROOT, top, d)):
                for k in mb.find_kits(os.path.join(ROOT, top, d)):
                    yield k


def test_kits():
    print('Kits in examples/ (and kits/)')
    for k in kit_paths():
        try:
            kit = mb.Kit(k)
        except mb.KitError as e:
            check(False, '%s loads: %s' % (os.path.basename(k), e))
            continue
        check(True, '%s loads (%d slots, %d games)' % (kit.name, len(kit.slots), len(kit.games)))
        m = kit_files_exist(kit)
        if kit.cfg.get('_external_files'):
            # a reference kit whose patches live in a release package, not in this repository
            print('  note  %s: %d kit files not included (%s)' % (kit.name, len(m), kit.cfg['_external_files']))
        else:
            check(not m, '%s: every kit: file exists%s' % (kit.name, (' (missing: %s)' % ', '.join(m[:5])) if m else ''))
        for i in range(len(kit.slots)):
            check(kit.default_for(i, kit.default_donor) is not None, '%s: %s %s has a default' % (kit.name, kit.selector, kit.position(i)))


def test_build(program):
    print('End-to-end build with made-up ROMs')
    ts = mb._bundled_ts_rom_tool()
    check(ts is not None, 'built-in ts_rom_tool imports (%s)' % (mb.ts_rom_tool_version(ts) if ts else '-'))
    tmp = tempfile.mkdtemp(prefix='mbtest_')
    try:
        rnd = random.Random(1)
        even, odd, snd = rnd.randbytes(4096), rnd.randbytes(4096), rnd.randbytes(2048)
        roms = os.path.join(tmp, 'roms'); os.makedirs(roms)
        with zipfile.ZipFile(os.path.join(roms, 'gamea.zip'), 'w') as z:
            z.writestr('a.even', even); z.writestr('a.odd', odd); z.writestr('a.snd', snd)
        os.makedirs(os.path.join(roms, 'gameb'))                       # unzipped set folder
        open(os.path.join(roms, 'gameb', 'b.bin'), 'wb').write(snd[::-1] * 2)
        kitdir = os.path.join(tmp, 'kit'); os.makedirs(os.path.join(kitdir, 'ips')); os.makedirs(os.path.join(kitdir, 'scripts'))
        patched = bytearray(snd); patched[10:14] = b'\xde\xad\xbe\xef'
        open(os.path.join(kitdir, 'ips', 'pcbB_snd.ips'), 'wb').write(ts.make_ips(snd, bytes(patched)))
        open(os.path.join(kitdir, 'scripts', 'invert.py'), 'w').write(
            'import sys\nd = open(sys.argv[1], "rb").read()\nopen(sys.argv[2], "wb").write(bytes(255 - b for b in d))\n')
        crc = lambda b: '%08x' % (zlib.crc32(b) & 0xffffffff)
        inter = bytes(x for p in zip(even, odd) for x in p)
        cfg = {
            'format': 1, 'name': 'Selftest kit', 'selector': {'title': 'Dial', 'order': 'position'},
            'donors': [{'id': 'pcbA', 'title': 'PCB A'}, {'id': 'pcbB', 'title': 'PCB B'}],
            'outputs': [{'id': 'prg', 'file': 'prg.bin', 'slot_size': '8K', 'fill': 'FF'},
                        {'id': 'snd', 'file': 'snd.bin', 'slot_size': '4K'}],
            'slots': [{'id': '0', 'position': '1', 'allow': ['gamea', 'gameb'], 'default': 'gamea'},
                      {'id': '1', 'position': '0', 'allow': ['gamea', 'gameb'], 'default': 'gameb'}],
            'games': {
                'gamea': {'title': 'Game A', 'sets': ['gamea'],
                          'roms': {'a.even': [crc(even), 4096], 'a.odd': [crc(odd), 4096], 'a.snd': [crc(snd), 2048]},
                          'steps': [['ts', '-interleave', 'rom:a.even', 'rom:a.odd', 'prg.bin'],
                                    ['copy', 'rom:a.snd', 'snd.bin'],
                                    ['py', 'kit:scripts/invert.py', 'snd.bin', 'inv.bin']],
                          'parts': {'prg': 'prg.bin', 'snd': ['snd.bin', 'inv.bin']},
                          'expect': {'prg': crc(inter)},
                          'donor_overrides': {'pcbB': {'steps': [
                              ['ts', '-interleave', 'rom:a.even', 'rom:a.odd', 'prg.bin'],
                              ['ts', '-ipsapply', 'kit:ips/{donor}_snd.ips', 'rom:a.snd', 'snd.bin'],
                              ['py', 'kit:scripts/invert.py', 'snd.bin', 'inv.bin']]}}},
                'gameb': {'title': 'Game B', 'sets': ['gameb'], 'roms': {'b.bin': [crc(snd[::-1] * 2), 4096]},
                          'parts': {'snd': 'rom:b.bin'}, 'donors': ['pcbA', 'pcbB']},
            },
        }
        kp = os.path.join(kitdir, 'selftest.multi.json')
        json.dump(cfg, open(kp, 'w'), indent=1)
        cmd = [program] if program else [sys.executable, os.path.join(ROOT, 'multibuilder.py')]

        def run(*args):
            p = subprocess.run(cmd + list(args), capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr

        for donor, sndA in (('pcbA', snd), ('pcbB', bytes(patched))):
            out = os.path.join(tmp, 'out_' + donor)
            code, text = run('--kit', kp, '--roms', roms, '--out', out, '--donor', donor)
            check(code == 0, 'build with donor %s succeeds' % donor)
            if code:
                print(text)
                continue
            prg = open(os.path.join(out, 'prg.bin'), 'rb').read()
            sndo = open(os.path.join(out, 'snd.bin'), 'rb').read()
            check(prg == inter + b'\xff' * 8192, 'prg.bin = interleaved game A + FF fill (%s)' % donor)
            check(sndo == sndA + bytes(255 - b for b in sndA) + snd[::-1] * 2, 'snd.bin = game A sound + script output + game B (%s)' % donor)
            check(os.path.isfile(os.path.join(out, 'build_settings.json')), 'build_settings.json written (%s)' % donor)
            code, text = run('--profile', os.path.join(out, 'build_settings.json'), '--out', out + '_again')
            check(code == 0 and open(os.path.join(out + '_again', 'snd.bin'), 'rb').read() == sndo,
                  'rebuilding from build_settings.json gives the same result (%s)' % donor)
        code, text = run('--kit', kp, '--roms', roms, '--out', os.path.join(tmp, 'x'), '--slot', '0=nosuchgame')
        check(code != 0, 'a game not allowed in a slot is refused')
        os.remove(os.path.join(roms, 'gameb', 'b.bin'))
        code, text = run('--kit', kp, '--roms', roms, '--check')
        check(code != 0 and 'missing' in text, 'a missing ROM is reported')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def forge(size, crc, rnd):
    """random data of SIZE bytes whose CRC32 is CRC (the last 4 bytes are solved for)"""
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        table.append(c)
    top = {t >> 24: i for i, t in enumerate(table)}
    body = rnd.randbytes(size - 4)
    reg = zlib.crc32(body) ^ 0xffffffff
    f = int(crc, 16) ^ 0xffffffff
    for _ in range(4):
        j = top[f >> 24]
        f = (((f ^ table[j]) << 8) & 0xffffffff) | j
    data = body + (f ^ reg).to_bytes(4, 'little')
    assert zlib.crc32(data) & 0xffffffff == int(crc, 16)
    return data


def test_examples(program):
    print('Example kits, built with made-up ROMs forged to their CRCs')
    cmd = [program] if program else [sys.executable, os.path.join(ROOT, 'multibuilder.py')]
    rnd = random.Random(3)
    for kp in [k for k in kit_paths() if os.sep + 'examples' + os.sep in k]:
        kit = mb.Kit(kp)
        tmp = tempfile.mkdtemp(prefix='mbex_')
        try:
            kitdir = os.path.join(tmp, 'kit')
            shutil.copytree(os.path.dirname(kp), kitdir)
            cfg = json.load(open(kp, encoding='utf-8'))
            for g in cfg['games'].values():          # forged ROMs can't give the real patched CRCs
                g.pop('expect', None)
                for ov in g.get('donor_overrides', {}).values():
                    ov.pop('expect', None)
            for rel in kit_files_exist(kit):              # stand-ins for patches not kept in the repository
                p = os.path.join(kitdir, rel.split(': ', 1)[1])
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as f:
                    f.write(b'PATCHEOF' if p.lower().endswith('.ips') else b'')
            kp2 = os.path.join(kitdir, os.path.basename(kp))
            json.dump(cfg, open(kp2, 'w', encoding='utf-8'))
            roms = os.path.join(tmp, 'roms'); os.makedirs(roms)
            made = {}
            for gid in kit.games:
                for donor in kit.donor_ids() or [None]:
                    g = kit.game(gid, donor)
                    for name, (crc, size) in g['roms'].items():
                        if crc not in made:
                            made[crc] = forge(size, crc, rnd)
                        with zipfile.ZipFile(os.path.join(roms, g['sets'][0] + '.zip'), 'a') as z:
                            if name not in z.namelist():
                                z.writestr(name, made[crc])
            for donor in kit.donor_ids() or [None]:
                # every game a slot can take for this donor, cycling so each game is built at least once
                choices = [kit.allowed(s, donor) for s in kit.slots]
                for r in range(max(len(c) for c in choices)):
                    args = ['--kit', kp2, '--roms', roms, '--out', os.path.join(tmp, 'out')]
                    if donor:
                        args += ['--donor', donor]
                    for i, c in enumerate(choices):
                        args += ['--slot', 'id:%s=%s' % (kit.slots[i]['id'], c[r % len(c)])]
                    p = subprocess.run(cmd + args, capture_output=True, text=True)
                    what = '%s: build %d%s' % (kit.name, r + 1, (' for %s' % donor) if donor else '')
                    check(p.returncode == 0, what)
                    if p.returncode:
                        print(p.stdout + p.stderr)
                        break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--program', help='compiled Multi Builder to test instead of multibuilder.py')
    a = ap.parse_args()
    test_kits()
    test_build(a.program and os.path.abspath(a.program))
    test_examples(a.program and os.path.abspath(a.program))
    print('\n%d check(s) failed' % len(fails) if fails else '\nall checks passed')
    sys.exit(1 if fails else 0)
