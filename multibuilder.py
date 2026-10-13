#!/usr/bin/env python3
"""
Multi Builder - builds the EPROM images for an arcade multi-game kit from MAME ROM sets.

Everything about a particular multi lives in its kit folder:
  <name>.multi.json   the kit configuration (slots, games, donor boards, build steps, output EPROMs)
  ips/, scripts/ ...  whatever patches and scripts the kit's games need

ts_rom_tool (https://github.com/twistedsymphony/ts_rom_tool) is built in: it is a git submodule of this
repository and is compiled into the program. A kit may still ship its own ts_rom_tool.py and name it with
"ts_rom_tool" in its configuration; that copy is then used instead.

The tool itself never changes per multi. Run it with no arguments for the GUI, or see --help.
"""
import os, sys, io, json, zlib, zipfile, hashlib, shutil, tempfile, threading, queue, traceback, runpy
import importlib.util, contextlib, subprocess, time, datetime, argparse

sys.dont_write_bytecode = True     # kit scripts and ts_rom_tool load from the kit folder; leave it clean

APP_NAME = 'Multi Builder'
APP_VERSION = '1.4'
FORMAT_VERSION = 1
PROFILE_VERSION = 1


def _bundled_ts_rom_tool():
    """the ts_rom_tool compiled into this program (or, from source, the ts_rom_tool submodule)"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, 'ts_rom_tool'), here):
        if os.path.isfile(os.path.join(d, 'ts_rom_tool.py')) and d not in sys.path:
            sys.path.insert(0, d)
    try:
        import ts_rom_tool
    except ImportError:
        return None
    return ts_rom_tool


def ts_rom_tool_version(mod):
    """the date line at the top of ts_rom_tool.py, recorded at build time for the compiled program"""
    base = getattr(sys, '_MEIPASS', None)
    if base and os.path.isfile(os.path.join(base, 'ts_rom_tool_version.txt')):
        with open(os.path.join(base, 'ts_rom_tool_version.txt'), encoding='utf-8') as f:
            return f.read().strip()
    try:
        with open(mod.__file__, encoding='utf-8') as f:
            return f.readline().lstrip('# ').strip()
    except Exception:
        return 'unknown version'


def _bundle_hints():
    # Standard-library modules kit scripts may use. Importing them here makes PyInstaller include
    # them in the compiled tool, so kit scripts run without a separate Python installation.
    import wave, fractions, struct, binascii, math, re, array, itertools, collections, functools, csv  # noqa: F401
    import decimal, statistics, random, string, textwrap, copy, glob, pathlib, base64, bisect, heapq  # noqa: F401
    import operator, enum, dataclasses, typing, codecs, unicodedata, cmath, numbers, hmac, secrets  # noqa: F401
    import gzip, bz2, lzma, tarfile, configparser, pprint, difflib, fnmatch, shlex, uuid, warnings  # noqa: F401


# --------------------------------------------------------------------------------------------
# sizes, small helpers
# --------------------------------------------------------------------------------------------
def parse_size(v):
    """'512K', '4M', '0x80000', 65536 -> bytes"""
    if isinstance(v, int):
        return v
    s = str(v).strip().upper()
    if s.startswith('0X'):
        return int(s, 16)
    mult = 1
    if s.endswith('K'):
        mult, s = 1024, s[:-1]
    elif s.endswith('M'):
        mult, s = 1024 * 1024, s[:-1]
    return int(float(s) * mult)


def fmt_size(n):
    if n % (1024 * 1024) == 0:
        return '%d MB' % (n // (1024 * 1024))
    if n % 1024 == 0:
        return '%d KB' % (n // 1024)
    return '%d bytes' % n


def crc32_hex(data):
    return '%08x' % (zlib.crc32(data) & 0xffffffff)


class KitError(Exception):
    pass


class BuildError(Exception):
    pass


def app_dir():
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
        if d.endswith(os.path.join('Contents', 'MacOS')):      # macOS .app: use the folder holding the app
            d = os.path.abspath(os.path.join(d, '..', '..', '..'))
        return d
    return os.path.dirname(os.path.abspath(__file__))


def settings_path():
    base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'multibuilder', 'settings.json')


def load_settings():
    try:
        with open(settings_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), 'w', encoding='utf-8') as f:
            json.dump(s, f, indent=1)
    except Exception:
        pass


# --------------------------------------------------------------------------------------------
# kit configuration
# --------------------------------------------------------------------------------------------
class Kit:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            try:
                c = json.load(f)
            except ValueError as e:
                raise KitError('%s is not valid JSON: %s' % (os.path.basename(path), e))
        self.cfg = c
        if c.get('format', 1) > FORMAT_VERSION:
            raise KitError('This kit needs a newer version of %s (kit format %s).' % (APP_NAME, c.get('format')))
        self.name = c.get('name', os.path.basename(path))
        self.board = c.get('board', '')
        self.description = c.get('description', '')
        sel = c.get('selector', {})
        if isinstance(sel, str):
            sel = {'title': sel}
        self.selector = sel.get('title', c.get('slot_selector', 'Slot'))
        self.selector_note = sel.get('note', '')
        self.sort_by_position = sel.get('order', 'slot') == 'position'
        self.ts_tool = c.get('ts_rom_tool')            # optional: the kit's own copy instead of the built-in one
        self.all_outputs = c.get('outputs', [])
        self.slots = c.get('slots', [])
        self.groups = c.get('groups', {})
        self.games = c.get('games', {})
        self.donors = c.get('donors', [])
        self.donor_title = c.get('donor_title', 'Donor PCB')
        self.default_donor = c.get('default_donor') or (self.donors[0]['id'] if self.donors else None)
        self.validate()

    # ---- lookups
    def position(self, i):
        s = self.slots[i]
        return str(s.get('position', s.get('label', s.get('id', i))))

    def display_order(self):
        idx = list(range(len(self.slots)))
        if self.sort_by_position:
            def key(i):
                p = self.position(i)
                return (0, int(p)) if p.isdigit() else (1, p)
            idx.sort(key=key)
        return idx

    def slot_index(self, key):
        """slot by switch position (default), 'id:X' or 'label:X'"""
        key = str(key)
        kind = 'position'
        if key[:3] in ('id:', 'pos') or key.startswith('label:'):
            kind, _, key = key.partition(':')
            kind = {'pos': 'position'}.get(kind, kind)
        for i, s in enumerate(self.slots):
            if kind == 'position' and key == self.position(i):
                return i
            if kind == 'id' and key == str(s.get('id', i)):
                return i
            if kind == 'label' and key == str(s.get('label', '')):
                return i
        return None

    def donor_ids(self):
        return [d['id'] for d in self.donors]

    def donor_name(self, did):
        for d in self.donors:
            if d['id'] == did:
                return d.get('title', did)
        return did or ''

    def game_supports(self, gid, donor):
        ds = self.games[gid].get('donors')
        return not ds or donor is None or donor in ds

    def allowed(self, slot, donor=None):
        out = []
        for a in slot.get('allow', []):
            names = self.groups.get(a[1:], []) if a.startswith('@') else [a]
            for n in names:
                if n not in out and n in self.games and self.game_supports(n, donor):
                    out.append(n)
        return out

    def default_for(self, i, donor=None):
        s = self.slots[i]
        al = self.allowed(s, donor)
        dd = s.get('default_by_donor', {}).get(donor) if donor else None
        for g in (dd, s.get('default')):
            if g in al:
                return g
        return al[0] if al else None

    # ---- shared banks: a slot can take some outputs' data from another slot ("shares")
    def slot_by_id(self, sid):
        for i, s in enumerate(self.slots):
            if str(s.get('id', i)) == str(sid):
                return i
        return None

    def shared_outputs(self, i):
        """output ids slot i takes from its owner slot (empty if it has no shares)"""
        sh = self.slots[i].get('shares')
        if not sh:
            return []
        if 'outputs' in sh:
            return list(sh['outputs'])
        return [o['id'] for o in self.all_outputs if o['id'] not in sh.get('except', [])]

    def owner(self, i, oid):
        """the slot whose data slot i uses for output oid (i itself unless it shares that output)"""
        if oid in self.shared_outputs(i):
            return self.slot_by_id(self.slots[i]['shares']['slot'])
        return i

    def owners(self, i, donor=None):
        """{owner slot index: [output ids]} for the outputs slot i shares (and that are built for this donor)"""
        built = {o['id'] for o in self.outputs(donor)}
        out = {}
        for oid in self.shared_outputs(i):
            if oid in built:
                out.setdefault(self.owner(i, oid), []).append(oid)
        return out

    def family(self, gid, donor=None):
        """games of one family can share banks: by default, the same MAME parent set"""
        g = self.game(gid, donor)
        return g.get('family') or (g.get('sets') or [gid])[-1]

    def choices(self, i, donor, selection):
        """the games slot i can take, given the games chosen for the slots it shares banks with"""
        al = self.allowed(self.slots[i], donor)
        own = self.owners(i, donor)
        if not own:
            return al
        fams = {self.family(selection[j], donor) for j in own if selection[j]}
        if len(fams) != 1 or any(not selection[j] for j in own):
            return []
        return [g for g in al if self.family(g, donor) in fams]

    def resolve_selection(self, selection, donor=None, fixed=()):
        """make a selection valid: games allowed in their slots, and slots that share banks holding games of
        the owner's family. Slots in `fixed` (indexes) are left as they are, so the build can report them."""
        n = len(self.slots)
        sel = list(selection) if selection else [None] * n
        order = [i for i in range(n) if not self.slots[i].get('shares')] + \
                [i for i in range(n) if self.slots[i].get('shares')]
        for i in order:
            if i in fixed:
                continue
            ch = self.choices(i, donor, sel)
            if sel[i] in ch:
                continue
            pick = None
            for g in [self.default_for(i, donor)] + [sel[j] for j in self.owners(i, donor)]:
                if g in ch:
                    pick = g
                    break
            sel[i] = pick or (ch[0] if ch else None)
        return sel

    def share_note(self, i):
        sh = self.slots[i].get('shares')
        if not sh:
            return ''
        j = self.slot_by_id(sh['slot'])
        return 'shares %s with %s' % (', '.join(self.shared_outputs(i)), self.position(j) if j is not None else '?')

    def outputs(self, donor=None):
        return [o for o in self.all_outputs if not o.get('donors') or donor is None or donor in o['donors']]

    def game(self, gid, donor=None):
        """the game's definition with its donor-specific overrides applied"""
        g = dict(self.games[gid])
        if donor:
            ov = g.get('donor_overrides', {}).get(donor, {})
            for k, v in ov.items():
                g[k] = v
        return g

    def output_slot_sizes(self, out):
        if 'slot_sizes' in out:
            return [parse_size(x) for x in out['slot_sizes']]
        return [parse_size(out['slot_size'])] * len(self.slots)

    def kit_file(self, rel):
        return os.path.normpath(os.path.join(self.dir, rel))

    def validate(self):
        errs = []
        oids = set()
        dids = set(self.donor_ids())
        for d in self.donors:
            if 'id' not in d:
                errs.append('a donor entry has no id')
        if self.default_donor and dids and self.default_donor not in dids:
            errs.append('default_donor %s is not in donors' % self.default_donor)
        for o in self.all_outputs:
            for k in ('id', 'file'):
                if k not in o:
                    errs.append('output %r has no %r' % (o, k))
            oids.add(o.get('id'))
            if 'slot_size' not in o and 'slot_sizes' not in o:
                errs.append('output %s has no slot_size' % o.get('id'))
            elif 'slot_sizes' in o and len(o['slot_sizes']) != len(self.slots):
                errs.append('output %s: slot_sizes needs one entry per slot' % o.get('id'))
            for d in o.get('donors', []):
                if d not in dids:
                    errs.append('output %s: unknown donor %s' % (o.get('id'), d))
        for g, n in self.groups.items():
            for x in n:
                if x not in self.games:
                    errs.append('group %s lists unknown game %s' % (g, x))
        positions = []
        for i, s in enumerate(self.slots):
            positions.append(self.position(i))
            for a in s.get('allow', []):
                if a.startswith('@') and a[1:] not in self.groups:
                    errs.append('slot %s: unknown group %s' % (s.get('id'), a))
                elif not a.startswith('@') and a not in self.games:
                    errs.append('slot %s allows unknown game %s' % (s.get('id'), a))
            if s.get('default') and s['default'] not in self.allowed(s):
                errs.append('slot %s: default %s is not in its allowed list' % (s.get('id'), s['default']))
        oid_list = [o.get('id') for o in self.all_outputs]
        for i, s in enumerate(self.slots):
            sh = s.get('shares')
            if not sh:
                continue
            j = self.slot_by_id(sh.get('slot'))
            if j is None:
                errs.append('slot %s shares with unknown slot %s' % (s.get('id'), sh.get('slot')))
                continue
            if j == i:
                errs.append('slot %s shares with itself' % s.get('id'))
            if self.slots[j].get('shares'):
                errs.append('slot %s shares with slot %s, which itself shares; share with the slot that owns the data'
                            % (s.get('id'), sh.get('slot')))
            for x in list(sh.get('outputs', [])) + list(sh.get('except', [])):
                if x not in oid_list:
                    errs.append('slot %s shares unknown output %s' % (s.get('id'), x))
            if 'outputs' in sh and 'except' in sh:
                errs.append('slot %s: give shares either "outputs" or "except", not both' % s.get('id'))
        if len(set(positions)) != len(positions):
            errs.append('two slots share the same position')
        for gid, g in self.games.items():
            if 'title' not in g:
                errs.append('game %s has no title' % gid)
            for o in g.get('parts', {}):
                if o not in oids:
                    errs.append('game %s: part for unknown output %s' % (gid, o))
            for d in g.get('donors', []):
                if d not in dids:
                    errs.append('game %s: unknown donor %s' % (gid, d))
            for d in g.get('donor_overrides', {}):
                if d not in dids:
                    errs.append('game %s: overrides for unknown donor %s' % (gid, d))
        if not errs:
            # the recommended games must fit together: a slot sharing banks needs a game of its owner's family
            for d in self.donor_ids() or [None]:
                defaults = [self.default_for(i, d) for i in range(len(self.slots))]
                ok = self.resolve_selection(defaults, d)
                for i, (a, b) in enumerate(zip(defaults, ok)):
                    if a != b:
                        errs.append('slot %s: the recommended game %s can\'t share banks with %s%s (different family); '
                                    'recommend a version of the same game' % (self.slots[i].get('id'), a,
                                    ', '.join(str(defaults[j]) for j in self.owners(i, d)), (' for donor %s' % d) if d else ''))
        if errs:
            raise KitError('Kit configuration problems:\n  ' + '\n  '.join(errs))


def find_kits(folder):
    try:
        return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.multi.json'))
    except OSError:
        return []


# --------------------------------------------------------------------------------------------
# build profiles: the user's choices, saved so a build can be repeated or edited later
# --------------------------------------------------------------------------------------------
def make_profile(kit, donor, selection, roms, out, base_dir=None):
    def rel(p):
        if not p:
            return p
        if base_dir:
            try:
                r = os.path.relpath(p, base_dir)
                if not r.startswith('..' + os.sep + '..'):
                    return r.replace(os.sep, '/')
            except ValueError:          # different drive on Windows
                pass
        return p
    return {
        'multibuilder_profile': PROFILE_VERSION,
        'kit': rel(kit.path),
        'kit_name': kit.name,
        'donor': donor,
        'roms': roms,
        'output': out,
        'slots': [{'slot': str(kit.slots[i].get('id', i)), 'position': kit.position(i), 'game': selection[i],
                   'title': kit.games[selection[i]]['title'] if selection[i] in kit.games else ''}
                  for i in kit.display_order()],
    }


def save_profile(path, prof):
    # one line per slot, so the file is easy to read and hand-edit
    lines = ['{']
    keys = [k for k in prof if k != 'slots']
    for k in keys:
        lines.append('  %s: %s,' % (json.dumps(k), json.dumps(prof[k])))
    lines.append('  "slots": [')
    lines.append(',\n'.join('    ' + json.dumps(s) for s in prof.get('slots', [])))
    lines.append('  ]')
    lines.append('}')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def read_profile(path):
    with open(path, 'r', encoding='utf-8') as f:
        try:
            p = json.load(f)
        except ValueError as e:
            raise KitError('%s is not valid JSON: %s' % (os.path.basename(path), e))
    if 'multibuilder_profile' not in p:
        raise KitError('%s is not a %s settings file' % (os.path.basename(path), APP_NAME))
    return p


def profile_kit_path(prof, prof_path):
    k = prof.get('kit')
    cands = []
    if k:
        cands.append(k if os.path.isabs(k) else os.path.join(os.path.dirname(os.path.abspath(prof_path)), k))
    cands += find_kits(app_dir()) + find_kits(os.getcwd())
    for c in cands:
        if os.path.isfile(c):
            try:
                if Kit(c).name == prof.get('kit_name', Kit(c).name):
                    return c
            except KitError:
                pass
    return cands[0] if cands and os.path.isfile(cands[0]) else None


def apply_profile(kit, prof):
    """-> donor, selection list, list of warnings"""
    warn = []
    donor = prof.get('donor') if kit.donors else None
    if kit.donors and donor not in kit.donor_ids():
        warn.append('donor %s is not in this kit; using %s' % (donor, kit.default_donor))
        donor = kit.default_donor
    sel = [kit.default_for(i, donor) for i in range(len(kit.slots))]
    for e in prof.get('slots', []):
        i = kit.slot_index('id:%s' % e.get('slot'))
        if i is None:
            warn.append('slot %s is not in this kit' % e.get('slot'))
            continue
        g = e.get('game')
        if g in kit.allowed(kit.slots[i], donor):
            sel[i] = g
        else:
            warn.append('%s is not available in %s %s; kept %s' % (g, kit.selector, kit.position(i), sel[i]))
    fixed = kit.resolve_selection(sel, donor)
    for i, (a, b) in enumerate(zip(sel, fixed)):
        if a != b:
            warn.append('%s can\'t share banks with the game at %s %s; using %s' % (a, kit.selector,
                        ', '.join(kit.position(j) for j in kit.owners(i, donor)), b))
    return donor, fixed, warn


# --------------------------------------------------------------------------------------------
# locating ROMs in a MAME ROM folder (split, merged and non-merged sets; zips or folders)
# --------------------------------------------------------------------------------------------
class RomSource:
    def __init__(self, kind, container, member, size, crc):
        self.kind, self.container, self.member, self.size, self.crc = kind, container, member, size, crc

    def where(self, root):
        rel = os.path.relpath(self.container, root) if root else self.container
        return '%s : %s' % (rel, self.member) if self.kind == 'zip' else os.path.join(rel, self.member)

    def read(self):
        if self.kind == 'zip':
            with zipfile.ZipFile(self.container) as z:
                return z.read(self.member)
        with open(os.path.join(self.container, self.member), 'rb') as f:
            return f.read()


class RomLocator:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.global_index = None

    def _scan_zip(self, path):
        if path in self.cache:
            return self.cache[path]
        out = []
        try:
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if not i.is_dir():
                        out.append(RomSource('zip', path, i.filename, i.file_size, '%08x' % i.CRC))
        except (zipfile.BadZipFile, OSError):
            pass
        self.cache[path] = out
        return out

    def _scan_dir(self, path):
        if path in self.cache:
            return self.cache[path]
        out = []
        for base, _, files in os.walk(path):
            for fn in files:
                full = os.path.join(base, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                out.append(RomSource('dir', path, os.path.relpath(full, path), size, None))
        self.cache[path] = out
        return out

    def _set_sources(self, setname):
        out = []
        z = os.path.join(self.root, setname + '.zip')
        if os.path.isfile(z):
            out += self._scan_zip(z)
        d = os.path.join(self.root, setname)
        if os.path.isdir(d):
            out += self._scan_dir(d)
        return out

    @staticmethod
    def _crc_of(src):
        if src.crc is None:
            try:
                src.crc = crc32_hex(src.read())
            except OSError:
                src.crc = ''
        return src.crc

    def _global(self):
        if self.global_index is None:
            self.global_index = {}
            try:
                names = os.listdir(self.root)
            except OSError:
                names = []
            for n in names:
                if n.lower().endswith('.zip'):
                    for s in self._scan_zip(os.path.join(self.root, n)):
                        self.global_index.setdefault(s.crc, []).append(s)
        return self.global_index

    def find(self, name, crc, size, sets, search_all=True):
        crc = crc.lower()
        named_wrong = None
        for st in sets:
            srcs = self._set_sources(st)
            for s in srcs:
                base = os.path.basename(s.member.replace('\\', '/'))
                if s.kind == 'zip' and s.size == size and s.crc == crc:
                    return s, None
                if base.lower() == name.lower():
                    if s.size == size and self._crc_of(s) == crc:
                        return s, None
                    named_wrong = s
            for s in srcs:
                if s.kind == 'dir' and s.size == size and self._crc_of(s) == crc:
                    return s, None
        if search_all:
            for s in self._global().get(crc, []):
                if s.size == size:
                    return s, None
        if named_wrong is not None:
            return None, 'wrong version (CRC %s, size %d) in %s' % (self._crc_of(named_wrong), named_wrong.size,
                                                                     named_wrong.where(self.root))
        return None, 'missing'


def check_game(kit, gid, locator, donor=None):
    """-> (found dict name->RomSource, problems list of (name, text))"""
    g = kit.game(gid, donor)
    found, problems = {}, []
    sets = g.get('sets', [gid])
    for name, spec in g.get('roms', {}).items():
        src, why = locator.find(name, spec[0], spec[1], sets)
        if src:
            found[name] = src
        else:
            problems.append((name, why))
    return found, problems


# --------------------------------------------------------------------------------------------
# build steps
# --------------------------------------------------------------------------------------------
class Runner:
    def __init__(self, kit, log, donor=None):
        self.kit, self.log, self.donor = kit, log, donor
        self._ts = None

    def ts_module(self):
        if self._ts is None:
            if self.kit.ts_tool:
                p = self.kit.kit_file(self.kit.ts_tool)
                if not os.path.isfile(p):
                    raise BuildError('the kit names %s, but it is not in the kit folder' % self.kit.ts_tool)
                spec = importlib.util.spec_from_file_location('kit_ts_rom_tool', p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.log('    using the kit\'s own ts_rom_tool (%s)' % ts_rom_tool_version(mod))
            else:
                mod = _bundled_ts_rom_tool()
                if mod is None:
                    raise BuildError('ts_rom_tool is missing from this copy of %s' % APP_NAME)
            self._ts = mod
        return self._ts

    @staticmethod
    @contextlib.contextmanager
    def _in_dir(d, argv):
        old_cwd, old_argv, old_path = os.getcwd(), sys.argv, list(sys.path)
        os.chdir(d)
        sys.argv = argv
        sys.path.insert(0, os.path.dirname(argv[0]))      # a script may import modules next to it
        try:
            yield
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
            sys.path[:] = old_path

    @staticmethod
    def _capture(fn):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                fn()
            except SystemExit as e:
                if e.code not in (None, 0):
                    code = e.code if isinstance(e.code, int) else 1
                    if not isinstance(e.code, int):
                        print(e.code)
            except ImportError as e:
                print('%s: %s is not part of %s; this step must use "pyext" (the user\'s own Python)'
                      % (type(e).__name__, getattr(e, 'name', e), APP_NAME))
                code = 1
        return code, out.getvalue()

    def subst(self, s):
        return s.replace('{donor}', self.donor or '') if isinstance(s, str) else s

    def resolve(self, arg, workdir, roms, path=True):
        """rom:NAME and kit:PATH become full paths. Anything else is a work-folder file when path=True;
        for ts/py/pyext steps (path=False) it is passed through unchanged, so sizes, offsets and flags
        stay as written, and work-folder files still resolve because those steps run in the work folder."""
        if not isinstance(arg, str):
            return str(arg)
        arg = self.subst(arg)
        if arg.startswith('rom:'):
            n = arg[4:]
            if n not in roms:
                raise BuildError('step uses %s, which is not in the game\'s rom list' % n)
            return roms[n]
        if arg.startswith('kit:'):
            p = self.kit.kit_file(arg[4:])
            if not os.path.exists(p):
                raise BuildError('kit file %s is missing' % arg[4:])
            return p
        return os.path.join(workdir, arg) if path else arg

    def run_step(self, step, workdir, roms):
        kind = step[0]
        if kind == 'ts':
            cmd = [step[1]] + [self.resolve(a, workdir, roms, path=False) for a in step[2:]]
            mod = self.ts_module()
            argv = [getattr(mod, '__file__', None) or 'ts_rom_tool.py'] + cmd

            def go():
                with self._in_dir(workdir, argv):
                    mod.main(argv)
            code, text = self._capture(go)
            self._log_text(text)
            if code or 'error' in text.lower():
                raise BuildError('ts_rom_tool %s failed' % ' '.join(self.subst(x) for x in step[1:]))
        elif kind == 'py':
            args = [self.resolve(a, workdir, roms, path=False) for a in step[1:]]
            script = os.path.join(workdir, args[0])

            def go():
                with self._in_dir(workdir, [script] + args[1:]):
                    runpy.run_path(script, run_name='__main__')
            code, text = self._capture(go)
            self._log_text(text)
            if code:
                raise BuildError('%s failed' % os.path.basename(script))
        elif kind == 'pyext':
            args = [self.resolve(a, workdir, roms, path=False) for a in step[1:]]
            args[0] = os.path.join(workdir, args[0])
            exe = python_executable()
            if not exe:
                raise BuildError('this step needs a Python installation (py / python3) on the PATH')
            p = subprocess.run([exe] + args, cwd=workdir, capture_output=True, text=True)
            self._log_text(p.stdout + p.stderr)
            if p.returncode:
                raise BuildError('%s failed' % os.path.basename(args[0]))
        elif kind == 'fill':                       # ["fill", "out.bin", "128K", "FF"]
            with open(self.resolve(step[1], workdir, roms), 'wb') as f:
                f.write(bytes([int(step[3], 16) if len(step) > 3 else 0]) * parse_size(step[2]))
        elif kind == 'copy':
            shutil.copyfile(self.resolve(step[1], workdir, roms), self.resolve(step[2], workdir, roms))
        else:
            raise BuildError('unknown step type %r' % kind)

    def _log_text(self, text):
        for line in text.splitlines():
            if line.strip():
                self.log('      ' + line)


def python_executable():
    if not getattr(sys, 'frozen', False):
        return sys.executable
    for n in ('py', 'python3', 'python'):
        p = shutil.which(n)
        if p:
            return p
    return None


def build(kit, roms_dir, out_dir, selection, log, donor=None, keep_work=False, progress=None):
    """selection: list of game ids, one per slot. Returns the files written."""
    t0 = time.time()
    if kit.donors and donor not in kit.donor_ids():
        raise BuildError('choose a %s first' % kit.donor_title.lower())
    locator = RomLocator(roms_dir)
    runner = Runner(kit, log, donor)
    if len(selection) != len(kit.slots):
        raise BuildError('selection has %d entries for %d slots' % (len(selection), len(kit.slots)))
    for i, gid in enumerate(selection):
        if gid is None:
            raise BuildError('no game chosen for %s %s' % (kit.selector, kit.position(i)))
        if gid not in kit.allowed(kit.slots[i], donor):
            raise BuildError('%s is not allowed in %s %s%s' % (gid, kit.selector, kit.position(i),
                             (' with the %s donor' % kit.donor_name(donor)) if donor else ''))
    for i, gid in enumerate(selection):
        for j, oids in kit.owners(i, donor).items():
            if kit.family(gid, donor) != kit.family(selection[j], donor):
                raise BuildError('%s %s shares its %s with %s %s, so it needs a version of %s (%s is not one)'
                                 % (kit.selector, kit.position(i), ', '.join(oids), kit.selector, kit.position(j),
                                    selection[j], gid))
    games = list(dict.fromkeys(selection))
    defs = {gid: kit.game(gid, donor) for gid in games}

    if donor:
        log('%s: %s' % (kit.donor_title, kit.donor_name(donor)))
    log('Checking input ROMs in %s' % roms_dir)
    found_all, bad = {}, False
    for gid in games:
        found, problems = check_game(kit, gid, locator, donor)
        found_all[gid] = found
        if problems:
            bad = True
            log('  %s: %d of %d files not usable' % (defs[gid]['title'], len(problems), len(defs[gid]['roms'])))
            for name, why in problems:
                log('      %s: %s' % (name, why))
        else:
            log('  %s: all %d files found' % (defs[gid]['title'], len(found)))
    if bad:
        raise BuildError('some input ROMs are missing or the wrong version (see above); nothing was built')
    for gid in games:
        for m in defs[gid].get('python_modules', []):
            if importlib.util.find_spec(m) is None:
                raise BuildError('%s needs the Python module %s, which is not available here'
                                 % (defs[gid]['title'], m))

    os.makedirs(out_dir, exist_ok=True)
    work_root = tempfile.mkdtemp(prefix='multibuilder_')
    try:
        parts = {}
        for k, gid in enumerate(games):
            g = defs[gid]
            log('Building %s' % g['title'])
            wd = os.path.join(work_root, gid)
            os.makedirs(os.path.join(wd, '_roms'), exist_ok=True)
            roms = {}
            for name, src in found_all[gid].items():
                p = os.path.join(wd, '_roms', name)
                data = src.read()
                if crc32_hex(data) != g['roms'][name][0].lower():
                    raise BuildError('%s changed CRC while reading (%s)' % (name, src.where(roms_dir)))
                with open(p, 'wb') as f:
                    f.write(data)
                roms[name] = p
            for st in g.get('steps', []):
                log('    ' + ' '.join(runner.subst(str(x)) for x in st))
                runner.run_step(st, wd, roms)
            gp = {}
            for oid, spec in g.get('parts', {}).items():
                pieces = spec if isinstance(spec, list) else [spec]
                data = b''
                for pc in pieces:
                    p = runner.resolve(pc, wd, roms)
                    if not os.path.isfile(p):
                        raise BuildError('%s: %s was not produced' % (g['title'], pc))
                    with open(p, 'rb') as f:
                        data += f.read()
                exp = g.get('expect', {}).get(oid)
                if exp and crc32_hex(data) != exp.lower():
                    raise BuildError('%s: the %s data came out with CRC %s, expected %s. The kit files '
                                     '(patches, scripts or ts_rom_tool) do not match this kit version.'
                                     % (g['title'], oid, crc32_hex(data), exp))
                gp[oid] = data
            parts[gid] = gp
            if progress:
                progress((k + 1) / (len(games) + 1))

        for i, gid in enumerate(selection):
            for j, oids in kit.owners(i, donor).items():
                for oid in oids:
                    mine, theirs = parts[gid].get(oid), parts[selection[j]].get(oid)
                    if mine is not None and mine != theirs:
                        raise BuildError('%s %s shares its %s data with %s %s, but %s\'s %s data differs from %s\'s. '
                                         'Choose versions whose %s data is the same.'
                                         % (kit.selector, kit.position(i), oid, kit.selector, kit.position(j),
                                            defs[gid]['title'], oid, defs[selection[j]]['title'], oid))
            if kit.owners(i, donor):
                log('  %s %s uses the %s data of %s %s' % (kit.selector, kit.position(i),
                    ', '.join(x for v in kit.owners(i, donor).values() for x in v), kit.selector,
                    ', '.join(kit.position(j) for j in kit.owners(i, donor))))

        written, report = [], []
        for o in kit.outputs(donor):
            sizes = kit.output_slot_sizes(o)
            fill = bytes([int(o.get('fill', '00'), 16)])
            img = b''
            for i, gid in enumerate(selection):
                if kit.owner(i, o['id']) != i:
                    continue                      # this slot uses another slot's bank of this chip
                data = parts[gid].get(o['id'])
                if data is None:
                    data = fill * sizes[i]
                if len(data) != sizes[i]:
                    raise BuildError('%s: its %s data is %s, but %s %s of %s holds %s'
                                     % (defs[gid]['title'], o['id'], fmt_size(len(data)), kit.selector,
                                        kit.position(i), o['file'], fmt_size(sizes[i])))
                img += data
            want = parse_size(o['size']) if 'size' in o else sum(sz for i, sz in enumerate(sizes)
                                                                    if kit.owner(i, o['id']) == i)
            if len(img) != want:
                raise BuildError('%s came out %s, but the %s needs %s' % (o['file'], fmt_size(len(img)),
                                                                         o.get('chip', 'EPROM'), fmt_size(want)))
            p = os.path.join(out_dir, o['file'])
            with open(p, 'wb') as f:
                f.write(img)
            with open(p, 'rb') as f:
                if f.read() != img:
                    raise BuildError('%s did not read back correctly from disk' % p)
            written.append(p)
            report.append((o, len(img), crc32_hex(img), hashlib.sha1(img).hexdigest()))
            log('  %-12s %-8s %8s  CRC32 %s' % (o['file'], o.get('chip', ''), fmt_size(len(img)), crc32_hex(img)))

        rp = os.path.join(out_dir, 'build_report.txt')
        with open(rp, 'w', encoding='utf-8', newline='\n') as f:
            f.write('%s %s build report\n' % (APP_NAME, APP_VERSION))
            f.write('Kit:   %s\n' % kit.name)
            if kit.board:
                f.write('Board: %s\n' % kit.board)
            if donor:
                f.write('%s: %s\n' % (kit.donor_title, kit.donor_name(donor)))
            f.write('Date:  %s\n\n' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
            f.write('%s:\n' % kit.selector)
            for i in kit.display_order():
                note = kit.share_note(i)
                f.write('  %-6s %-10s %s%s\n' % (kit.position(i), selection[i], defs[selection[i]]['title'],
                                                 ('   (%s)' % note) if note else ''))
            f.write('\nEPROM images:\n')
            for o, size, crc, sha in report:
                f.write('  %-12s %-8s %10d bytes  CRC32 %s  SHA1 %s\n' % (o['file'], o.get('chip', ''), size, crc, sha))
            f.write('\nTo repeat this build:  MultiBuilder --profile build_settings.json\n'
                    '                       (on Windows: MultiBuilderCLI.exe --profile build_settings.json)\n')
        written.append(rp)
        pp = os.path.join(out_dir, 'build_settings.json')
        save_profile(pp, make_profile(kit, donor, selection, os.path.abspath(roms_dir), os.path.abspath(out_dir)))
        written.append(pp)
        if progress:
            progress(1.0)
        log('Done in %.1f s. %d EPROM images written to %s' % (time.time() - t0, len(report), out_dir))
        return written
    finally:
        if keep_work:
            log('work files kept in %s' % work_root)
        else:
            shutil.rmtree(work_root, ignore_errors=True)


# --------------------------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------------------------
def cli(argv):
    ap = argparse.ArgumentParser(prog='multibuilder', description='%s %s (command line mode)' % (APP_NAME, APP_VERSION))
    ap.add_argument('--profile', help='settings file saved by the GUI or by an earlier build (build_settings.json)')
    ap.add_argument('--kit', help='kit configuration (.multi.json); default: the profile\'s kit, or the one next to the tool')
    ap.add_argument('--roms', help='folder with your MAME ROM sets (zips or folders)')
    ap.add_argument('--out', help='output folder for the EPROM images')
    ap.add_argument('--donor', help='donor PCB id, for kits that have them')
    ap.add_argument('--slot', action='append', default=[], metavar='SLOT=GAME',
                    help='put GAME at a switch position (or id:SLOT / label:SLOT); repeatable')
    ap.add_argument('--save-profile', metavar='FILE', help='write the resulting settings to FILE (no build unless --build)')
    ap.add_argument('--build', action='store_true', help='with --save-profile: build as well')
    ap.add_argument('--check', action='store_true', help='only check the input ROMs')
    ap.add_argument('--list', action='store_true', help='list slots, donors and the games each slot can take')
    ap.add_argument('--keep-work', action='store_true', help='keep the intermediate files')
    ap.add_argument('--version', action='store_true', help='show the program and built-in ts_rom_tool versions')
    a = ap.parse_args(argv)
    if a.version:
        ts = _bundled_ts_rom_tool()
        print('%s %s, ts_rom_tool %s' % (APP_NAME, APP_VERSION, ts_rom_tool_version(ts) if ts else 'missing'))
        return 0

    prof = read_profile(a.profile) if a.profile else None
    kp = a.kit or (profile_kit_path(prof, a.profile) if prof else None) or (find_kits(app_dir()) or find_kits(os.getcwd()) or [None])[0]
    if not kp:
        print('no kit (.multi.json) found; use --kit'); return 2
    kit = Kit(kp)
    if prof:
        donor, sel, warn = apply_profile(kit, prof)
        for w in warn:
            print('warning: ' + w)
    else:
        donor = kit.default_donor if kit.donors else None
        sel = None
    if a.donor:
        if a.donor not in kit.donor_ids():
            print('unknown donor %s (choose from %s)' % (a.donor, ', '.join(kit.donor_ids()) or 'none')); return 2
        donor = a.donor
    if sel is None:
        sel = [kit.default_for(i, donor) for i in range(len(kit.slots))]
    else:   # a donor change can make profile choices unavailable
        sel = [g if g in kit.allowed(kit.slots[i], donor) else kit.default_for(i, donor) for i, g in enumerate(sel)]
    fixed = set()
    for ov in a.slot:
        k, _, g = ov.partition('=')
        i = kit.slot_index(k)
        if i is None:
            print('unknown slot %s' % k); return 2
        sel[i] = g
        fixed.add(i)
    # slots sharing banks follow the games chosen for their owner slots (unless set explicitly)
    sel = kit.resolve_selection(sel, donor, fixed)
    roms = a.roms or (prof or {}).get('roms')
    out = a.out or (prof or {}).get('output')

    if a.list:
        if kit.donors:
            print('%s: %s' % (kit.donor_title, ', '.join('%s%s' % (d['id'], ' (selected)' if d['id'] == donor else '') for d in kit.donors)))
        for i in kit.display_order():
            note = kit.share_note(i)
            print('%s %s: %s   [%s]%s' % (kit.selector, kit.position(i), sel[i], ', '.join(kit.choices(i, donor, sel)),
                                         ('   (%s)' % note) if note else ''))
        return 0
    if a.save_profile:
        save_profile(a.save_profile, make_profile(kit, donor, sel, roms and os.path.abspath(roms), out and os.path.abspath(out),
                                                  os.path.dirname(os.path.abspath(a.save_profile))))
        print('settings saved to %s' % a.save_profile)
        if not a.build:
            return 0
    if not roms:
        print('no ROMs folder: use --roms or a --profile that has one'); return 2
    if a.check:
        loc = RomLocator(roms)
        ok = True
        for gid in dict.fromkeys(g for g in sel if g):
            found, prob = check_game(kit, gid, loc, donor)
            print('%-10s %s' % (gid, 'OK' if not prob else '; '.join('%s %s' % p for p in prob)))
            ok = ok and not prob
        return 0 if ok else 1
    if not out:
        print('no output folder: use --out or a --profile that has one'); return 2
    try:
        build(kit, roms, out, sel, lambda m: print(m, flush=True), donor=donor, keep_work=a.keep_work)
    except BuildError as e:
        print('BUILD FAILED: %s' % e); return 1
    return 0


# --------------------------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------------------------
def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText

    class App:
        def __init__(self, root):
            self.root = root
            self.settings = load_settings()
            self.kit = None
            self.q = queue.Queue()
            self.busy = False
            self.check_gen = 0
            self.slot_rows = []          # (slot index, var, ids, titles, status label, combobox)
            root.title(APP_NAME)
            root.minsize(780, 580)
            self._build_ui()
            kits = find_kits(app_dir()) or find_kits(os.getcwd())
            last = self.settings.get('kit')
            if last and os.path.isfile(last) and not kits:
                kits = [last]
            if kits:
                self.load_kit(kits[0])
            else:
                self.log('No kit found next to the tool. Use "Open kit..." to choose a .multi.json file.')
            self.root.after(100, self._poll)

        # ---- layout
        def _build_ui(self):
            r = self.root
            pad = {'padx': 8, 'pady': 4}
            top = ttk.Frame(r)
            top.pack(fill='x', **pad)
            self.kit_title = ttk.Label(top, text='No kit loaded', font=('TkDefaultFont', 13, 'bold'))
            self.kit_title.grid(row=0, column=0, sticky='w')
            tb = ttk.Frame(top)
            tb.grid(row=0, column=1, sticky='e')
            ttk.Button(tb, text='Load settings...', command=self.load_profile_dialog).pack(side='left', padx=(0, 4))
            ttk.Button(tb, text='Save settings...', command=self.save_profile_dialog).pack(side='left', padx=(0, 4))
            ttk.Button(tb, text='Open kit...', command=self.open_kit).pack(side='left')
            self.kit_sub = ttk.Label(top, text='', foreground='#555')
            self.kit_sub.grid(row=1, column=0, columnspan=2, sticky='w')
            top.columnconfigure(0, weight=1)

            paths = ttk.Frame(r)
            paths.pack(fill='x', **pad)
            self.donor_var = tk.StringVar()
            self.donor_label = ttk.Label(paths, text='Donor PCB')
            self.donor_box = ttk.Combobox(paths, textvariable=self.donor_var, state='readonly', width=40)
            self.donor_box.bind('<<ComboboxSelected>>', lambda ev: self.on_donor())
            self.roms_var = tk.StringVar(value=self.settings.get('roms', ''))
            self.out_var = tk.StringVar(value=self.settings.get('out', ''))
            ttk.Label(paths, text='ROMs folder').grid(row=1, column=0, sticky='w')
            e = ttk.Entry(paths, textvariable=self.roms_var)
            e.grid(row=1, column=1, sticky='ew', padx=6)
            e.bind('<Return>', lambda ev: self.refresh_status())
            e.bind('<FocusOut>', lambda ev: self.refresh_status())
            ttk.Button(paths, text='Browse...', command=self.pick_roms).grid(row=1, column=2)
            ttk.Label(paths, text='Output folder').grid(row=2, column=0, sticky='w', pady=(4, 0))
            ttk.Entry(paths, textvariable=self.out_var).grid(row=2, column=1, sticky='ew', padx=6, pady=(4, 0))
            ttk.Button(paths, text='Browse...', command=self.pick_out).grid(row=2, column=2, pady=(4, 0))
            paths.columnconfigure(1, weight=1)
            self.paths = paths

            self.slots_frame = ttk.LabelFrame(r, text='Games')
            self.slots_frame.pack(fill='x', **pad)

            btns = ttk.Frame(r)
            btns.pack(fill='x', **pad)
            ttk.Button(btns, text='Reset to recommended', command=self.reset_defaults).pack(side='left')
            ttk.Button(btns, text='Check ROMs', command=self.refresh_status).pack(side='left', padx=6)
            self.build_btn = ttk.Button(btns, text='Build', command=self.start_build)
            self.build_btn.pack(side='right')
            self.prog = ttk.Progressbar(btns, mode='determinate', maximum=1.0, length=180)
            self.prog.pack(side='right', padx=8)

            self.logw = ScrolledText(r, height=12, wrap='word', font=('TkFixedFont', 9))
            self.logw.pack(fill='both', expand=True, **pad)
            self.logw.configure(state='disabled')

        def _show_donors(self):
            k = self.kit
            if k and k.donors:
                self.donor_label.configure(text=k.donor_title)
                self.donor_label.grid(row=0, column=0, sticky='w', pady=(0, 4))
                self.donor_box.grid(row=0, column=1, sticky='w', padx=6, pady=(0, 4))
                self.donor_titles = [d.get('title', d['id']) for d in k.donors]
                self.donor_box.configure(values=self.donor_titles)
            else:
                self.donor_label.grid_remove()
                self.donor_box.grid_remove()

        def donor(self):
            if not self.kit or not self.kit.donors:
                return None
            t = self.donor_var.get()
            for d in self.kit.donors:
                if d.get('title', d['id']) == t:
                    return d['id']
            return self.kit.default_donor

        def _rebuild_slots(self, selection=None):
            for w in self.slots_frame.winfo_children():
                w.destroy()
            self.slot_rows = []
            k = self.kit
            donor = self.donor()
            for c, t in enumerate((k.selector, 'Game', 'ROMs')):
                ttk.Label(self.slots_frame, text=t, foreground='#555').grid(row=0, column=c, sticky='w', padx=6, pady=(2, 2))
            sel = k.resolve_selection(selection or [k.default_for(i, donor) for i in range(len(k.slots))], donor)
            for row, i in enumerate(k.display_order()):
                s = k.slots[i]
                ttk.Label(self.slots_frame, text=k.position(i), font=('TkDefaultFont', 11, 'bold')).grid(
                    row=row + 1, column=0, sticky='w', padx=10, pady=2)
                ids = k.choices(i, donor, sel)
                titles = [k.games[g]['title'] for g in ids]
                var = tk.StringVar()
                gid = sel[i]
                if gid:
                    var.set(k.games[gid]['title'])
                cb = ttk.Combobox(self.slots_frame, textvariable=var, values=titles, state='readonly', width=50)
                cb.grid(row=row + 1, column=1, sticky='ew', padx=6, pady=2)
                cb.bind('<<ComboboxSelected>>', lambda ev: self.on_change())
                st = ttk.Label(self.slots_frame, text='', width=30)
                st.grid(row=row + 1, column=2, sticky='w', padx=6)
                note = '; '.join(x for x in (s.get('note', ''), k.share_note(i)) if x)
                if note:
                    ttk.Label(self.slots_frame, text=note, foreground='#777').grid(row=row + 1, column=3, sticky='w', padx=6)
                self.slot_rows.append((i, var, ids, titles, st, cb))
            if k.selector_note:
                ttk.Label(self.slots_frame, text=k.selector_note, foreground='#777').grid(
                    row=len(k.slots) + 1, column=0, columnspan=4, sticky='w', padx=6, pady=(2, 4))
            self.slots_frame.columnconfigure(1, weight=1)

        # ---- helpers
        def log(self, msg):
            self.q.put(('log', msg))

        def _append(self, msg):
            self.logw.configure(state='normal')
            self.logw.insert('end', msg + '\n')
            self.logw.see('end')
            self.logw.configure(state='disabled')

        def _poll(self):
            try:
                while True:
                    kind, a = self.q.get_nowait()
                    if kind == 'log':
                        self._append(a)
                    elif kind == 'prog':
                        self.prog['value'] = a
                    elif kind == 'status':
                        gen, i, text, color = a
                        if gen == self.check_gen:
                            for row in self.slot_rows:
                                if row[0] == i:
                                    row[4].configure(text=text, foreground=color)
                    elif kind == 'done':
                        self.busy = False
                        self.build_btn.configure(state='normal')
                        ok, msg = a
                        (messagebox.showinfo if ok else messagebox.showerror)(APP_NAME, msg)
            except queue.Empty:
                pass
            self.root.after(100, self._poll)

        def selection(self):
            sel = [None] * len(self.kit.slots)
            for i, var, ids, titles, st, cb in self.slot_rows:
                t = var.get()
                sel[i] = ids[titles.index(t)] if t in titles else None
            return sel

        def save(self):
            self.settings['roms'] = self.roms_var.get()
            self.settings['out'] = self.out_var.get()
            if self.kit:
                self.settings['kit'] = self.kit.path
                self.settings.setdefault('profiles', {})[self.kit.name] = make_profile(
                    self.kit, self.donor(), self.selection(), self.roms_var.get(), self.out_var.get())
            save_settings(self.settings)

        def apply(self, donor, selection):
            if self.kit.donors:
                self.donor_var.set(self.kit.donor_name(donor or self.kit.default_donor))
            self._rebuild_slots(selection)

        # ---- actions
        def load_kit(self, path, profile=None):
            try:
                self.kit = Kit(path)
            except (KitError, OSError) as e:
                messagebox.showerror(APP_NAME, str(e))
                return False
            k = self.kit
            self.kit_title.configure(text=k.name)
            self.kit_sub.configure(text=' - '.join(x for x in (k.board, k.description) if x))
            self.root.title('%s - %s' % (APP_NAME, k.name))
            self.slots_frame.configure(text='Games (%d slots)' % len(k.slots))
            if not self.out_var.get():
                self.out_var.set(os.path.join(k.dir, 'output'))
            self._show_donors()
            prof = profile or self.settings.get('profiles', {}).get(k.name)
            if prof:
                donor, sel, warn = apply_profile(k, prof)
                for w in warn if profile else []:
                    self.log('note: ' + w)
            else:
                donor, sel = k.default_donor, None
            self.apply(donor, sel)
            self.log('Loaded kit: %s (%s)' % (k.name, path))
            self.refresh_status()
            return True

        def open_kit(self):
            p = filedialog.askopenfilename(title='Open kit', filetypes=[('Multi kit', '*.multi.json'), ('JSON', '*.json')])
            if p and self.load_kit(p):
                self.save()

        def save_profile_dialog(self):
            if not self.kit:
                return
            p = filedialog.asksaveasfilename(title='Save settings', defaultextension='.json',
                                             initialfile='%s_settings.json' % self.kit.name.split()[0],
                                             filetypes=[('Settings', '*.json')])
            if p:
                save_profile(p, make_profile(self.kit, self.donor(), self.selection(), self.roms_var.get(),
                                             self.out_var.get(), os.path.dirname(os.path.abspath(p))))
                self.log('Settings saved to %s' % p)

        def load_profile_dialog(self):
            p = filedialog.askopenfilename(title='Load settings', filetypes=[('Settings', '*.json')])
            if not p:
                return
            try:
                prof = read_profile(p)
            except (KitError, OSError) as e:
                messagebox.showerror(APP_NAME, str(e))
                return
            kp = profile_kit_path(prof, p)
            if not kp:
                messagebox.showerror(APP_NAME, 'Could not find the kit "%s" these settings were made for.\n'
                                     'Open the kit first, then load the settings again.' % prof.get('kit_name'))
                return
            if prof.get('roms'):
                self.roms_var.set(prof['roms'])
            if prof.get('output'):
                self.out_var.set(prof['output'])
            if self.load_kit(kp, profile=prof):
                self.log('Settings loaded from %s' % p)
                self.save()

        def pick_roms(self):
            d = filedialog.askdirectory(title='Your MAME ROMs folder', initialdir=self.roms_var.get() or None)
            if d:
                self.roms_var.set(d)
                self.save()
                self.refresh_status()

        def pick_out(self):
            d = filedialog.askdirectory(title='Output folder', initialdir=self.out_var.get() or None)
            if d:
                self.out_var.set(d)
                self.save()

        def reset_defaults(self):
            if self.kit:
                self._rebuild_slots(None)
                self.on_change()

        def on_donor(self):
            self._rebuild_slots(self.selection())
            self.on_change()

        def on_change(self):
            self._sync_choices()
            self.save()
            self.refresh_status()

        def _sync_choices(self):
            """slots that share banks only offer games of their owner slot's family; follow the owner's game"""
            k, donor = self.kit, self.donor()
            if not k or not any(s.get('shares') for s in k.slots):
                return
            sel = k.resolve_selection(self.selection(), donor)
            for i, var, ids, titles, st, cb in self.slot_rows:
                ids[:] = k.choices(i, donor, sel)
                titles[:] = [k.games[g]['title'] for g in ids]
                cb.configure(values=titles)
                var.set(k.games[sel[i]]['title'] if sel[i] else '')

        def refresh_status(self):
            if not self.kit:
                return
            self.check_gen += 1
            gen = self.check_gen
            roms = self.roms_var.get().strip()
            sel, donor = self.selection(), self.donor()
            for row in self.slot_rows:
                row[4].configure(text='checking...' if roms else 'choose a ROMs folder', foreground='#777')
            if not roms or not os.path.isdir(roms):
                return
            self.save()

            def work():
                loc = RomLocator(roms)
                cache = {}
                for i, gid in enumerate(sel):
                    if gid is None:
                        self.q.put(('status', (gen, i, 'no game fits (see note)', '#b3261e')))
                        continue
                    if gid not in cache:
                        cache[gid] = check_game(self.kit, gid, loc, donor)
                    found, prob = cache[gid]
                    if not prob:
                        self.q.put(('status', (gen, i, 'all %d files found' % len(found), '#1b7a2e')))
                    else:
                        miss = sum(1 for p in prob if p[1] == 'missing')
                        wrong = len(prob) - miss
                        txt = ', '.join(x for x in (('%d missing' % miss) if miss else '',
                                                     ('%d wrong version' % wrong) if wrong else '') if x)
                        self.q.put(('status', (gen, i, txt, '#b3261e')))
            threading.Thread(target=work, daemon=True).start()

        def start_build(self):
            if self.busy or not self.kit:
                return
            roms, out = self.roms_var.get().strip(), self.out_var.get().strip()
            if not roms or not os.path.isdir(roms):
                messagebox.showerror(APP_NAME, 'Choose the folder that holds your MAME ROM sets first.')
                return
            if not out:
                messagebox.showerror(APP_NAME, 'Choose an output folder first.')
                return
            donor = self.donor()
            existing = [o['file'] for o in self.kit.outputs(donor) if os.path.exists(os.path.join(out, o['file']))]
            if existing and not messagebox.askyesno(APP_NAME, 'The output folder already has %s.\nReplace them?' % ', '.join(existing)):
                return
            self.save()
            sel = self.selection()
            self.busy = True
            self.build_btn.configure(state='disabled')
            self.prog['value'] = 0
            self.log('')

            def work():
                try:
                    files = build(self.kit, roms, out, sel, self.log, donor=donor,
                                  progress=lambda v: self.q.put(('prog', v)))
                    n = sum(1 for f in files if not f.endswith(('.txt', '.json')))
                    self.q.put(('done', (True, 'Build complete.\n\n%d EPROM images, build_report.txt and '
                                         'build_settings.json are in\n%s' % (n, out))))
                except BuildError as e:
                    self.log('BUILD FAILED: %s' % e)
                    self.q.put(('done', (False, 'Build failed:\n\n%s' % e)))
                except Exception as e:
                    self.log(traceback.format_exc())
                    self.q.put(('done', (False, 'Build failed with an unexpected error:\n\n%s' % e)))
            threading.Thread(target=work, daemon=True).start()

    root = tk.Tk()
    if sys.platform.startswith('linux'):
        try:
            ttk.Style().theme_use('clam')
        except Exception:
            pass
    App(root)
    root.mainloop()


def main():
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    gui()


if __name__ == '__main__':
    main()
