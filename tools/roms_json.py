#!/usr/bin/env python3
"""Make the start of a Multi Builder "games" entry from MAME data, so you don't type CRCs by hand.

From MAME's own ROM list (best: also gives the title, the parent set and each file's ROM region):

    mame -listxml cadash > cadash.xml
    python tools/roms_json.py cadash.xml

    mame -listxml cadash cadashj cadashu > cadash.xml      several sets at once
    python tools/roms_json.py cadash.xml

From the ROM zips or folders you already have (no MAME needed; the title is left for you to fill in):

    python tools/roms_json.py D:/MAME/roms/cadash.zip D:/MAME/roms/cadashj.zip

It prints JSON you can paste into the "games" section of a .multi.json. "steps" and "parts" are left
empty for you to write; the "_regions" list (from -listxml) shows which files belong to which ROM
region, which is usually what decides how they are joined. Keys starting with "_" are ignored by
Multi Builder, so the hints can stay in the kit.

Only the Python standard library is used.
"""
import sys, os, json, zipfile, zlib
import xml.etree.ElementTree as ET


def crc_of(data):
    return '%08x' % (zlib.crc32(data) & 0xffffffff)


def from_listxml(path):
    games = {}
    tree = ET.parse(path)
    for m in tree.getroot().iter('machine'):
        name = m.get('name')
        roms, regions = {}, {}
        for r in m.findall('rom'):
            if r.get('status') == 'nodump' or not r.get('crc'):
                continue
            roms[r.get('name')] = [r.get('crc').lower(), int(r.get('size'))]
            regions.setdefault(r.get('region', '?'), []).append(r.get('name'))
        if not roms:
            continue                     # devices, BIOS-only entries
        sets = [name] + ([m.get('cloneof')] if m.get('cloneof') else [])
        desc = m.findtext('description') or name
        games[name] = {
            'title': desc,
            'sets': sets,
            'roms': roms,
            '_regions': {k: ' '.join(v) for k, v in regions.items()},
            'steps': [],
            'parts': {},
        }
    return games


def from_dump(path):
    name = os.path.splitext(os.path.basename(path.rstrip('/\\')))[0]
    roms = {}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if not i.is_dir():
                    roms[i.filename.split('/')[-1]] = ['%08x' % i.CRC, i.file_size]
    elif os.path.isdir(path):
        for f in sorted(os.listdir(path)):
            p = os.path.join(path, f)
            if os.path.isfile(p):
                with open(p, 'rb') as fh:
                    d = fh.read()
                roms[f] = [crc_of(d), len(d)]
    else:
        raise SystemExit('%s is not a zip, a folder or a -listxml file' % path)
    return {name: {'title': name + ' (fill in the title)', 'sets': [name], 'roms': roms,
                   '_note': 'clone zips hold only the files that differ from the parent: add the parent set to "sets" '
                            'and its files to "roms" if the game needs them',
                   'steps': [], 'parts': {}}}


def dumps(games):
    """JSON with one ROM per line: compact enough to read, easy to edit"""
    lines = ['{']
    gids = list(games)
    for gi, gid in enumerate(gids):
        g = games[gid]
        lines.append('  %s: {' % json.dumps(gid))
        keys = list(g)
        for ki, k in enumerate(keys):
            comma = ',' if ki < len(keys) - 1 else ''
            v = g[k]
            if isinstance(v, dict) and v:
                lines.append('    %s: {' % json.dumps(k))
                items = list(v.items())
                for ii, (a, b) in enumerate(items):
                    lines.append('      %s: %s%s' % (json.dumps(a), json.dumps(b), ',' if ii < len(items) - 1 else ''))
                lines.append('    }' + comma)
            else:
                lines.append('    %s: %s%s' % (json.dumps(k), json.dumps(v), comma))
        lines.append('  }' + (',' if gi < len(gids) - 1 else ''))
    lines.append('}')
    return '\n'.join(lines)


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    games = {}
    for a in argv:
        if a.lower().endswith('.xml'):
            games.update(from_listxml(a))
        else:
            games.update(from_dump(a))
    print(dumps(games))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
