# Making a kit

A **kit** tells Multi Builder everything about one multi:
- the EPROMs on the multi board
- the switch the player uses to pick a game
- which games fit at which position
- how to turn each game's MAME ROMs into the data for each EPROM

Multi Builder itself never changes from one multi to the next. A new multi only needs a new kit.

This guide walks through writing a kit from scratch. [KIT_FORMAT.md](../KIT_FORMAT.md) is the full reference for every key. Three ready-to-copy kits are in [`examples/`](../examples):

| Example | Shows |
|---|---|
| [`01_two_in_one`](../examples/01_two_in_one/asuka2in1.multi.json) | The smallest useful kit: two unmodified games, an OFF/ON switch, ROMs joined and copied as they are. Real games: it builds from real MAME sets. |
| [`02_region_switch`](../examples/02_region_switch/cadash4.multi.json) | Four regions of a ported game: IPS patches applied at build time, a group of games, `expect` CRCs, a rotary switch. Real games. |
| [`03_donors_and_scripts`](../examples/03_donors_and_scripts/example4in1.multi.json) | Every advanced feature: donor PCB choice, an inverted switch, outputs and patches that depend on the donor, a Python script step, `fill` and pad steps. Made-up board and games, for learning only. |

The full TASUKA-M8 kit in [`kits/TASUKA-M8`](../kits/TASUKA-M8) is a real 8-position kit with 27 games.

**Contents**
1. [The kit folder](#1-the-kit-folder)
2. [Plan the multi](#2-plan-the-multi)
3. [The top of the file](#3-the-top-of-the-file)
4. [Outputs: one per EPROM](#4-outputs-one-per-eprom)
5. [Slots: one per switch position](#5-slots-one-per-switch-position)
6. [Games](#6-games)
7. [Patched games](#7-patched-games)
8. [Script steps](#8-script-steps)
9. [Donor PCBs](#9-donor-pcbs)
10. [Test the kit](#10-test-the-kit)
11. [Publish the kit](#11-publish-the-kit)
12. [Step and argument reference](#12-step-and-argument-reference)

## 1. The kit folder

```
MYMULTI/
  MYMULTI.multi.json      the kit file (exactly one *.multi.json per folder)
  README.txt              optional: notes for the people building the multi
  ips/                    optional: IPS patches your games need
  scripts/                optional: Python scripts your games need
```

You can name the sub-folders however you like; the kit file refers to its files by path. ts_rom_tool is built into Multi Builder, so don't put a copy in the kit.

The kit file is JSON. Any key starting with `_` is ignored, so you can leave comments anywhere:

```json
"_note": "Position 3 uses the Eto address map, so only Eto sets are allowed there"
```

## 2. Plan the multi

Before writing anything, have these answers for your multi board:

- **The EPROMs.** For each chip: what it replaces on the original board (program, graphics, sound...), its type (27C322, 27C800, ...), and how much of it each game gets (the *slot size*). Usually the chip is divided evenly: an 8-game multi with a 4 MB 27C322 gives each game 512 KB.
- **The switch.** How many positions it has, what they're called on the cabinet (0-7, OFF/ON, 000-111), and which position selects which part of each EPROM. Some boards wire the switch in reverse bit order, so the second slot in the EPROM is reached at a different position (see [inverted switches](#inverted-or-reordered-switches)).
- **Which games can go where.** Slots wired differently (a different address map, a different PLD equation) can only run some games. Note which games each position can take.
- **Each game's ROM files** and how they map onto your chips. MAME's driver source (the `ROM_START` blocks) shows which file loads into which ROM region and how (`ROM_LOAD16_BYTE` = one byte of each 16-bit word, so a pair needs interleaving).

## 3. The top of the file

```json
{
  "format": 1,
  "name": "MYMULTI v1.0",
  "board": "Taito Asuka & Asuka PCB (K1100388A)",
  "description": "8-game multi; needs U2 rev 1.3",
  "selector": {"title": "Rotary switch", "order": "position", "note": "Shown under the game list"},
  "outputs": [],
  "slots": [],
  "groups": {},
  "games": {}
}
```

- `name` is the window's title. Put a version in it; it's also recorded in every settings file and build report.
- `board` and `description` appear under the title. Use them for anything the builder must check on their hardware.
- `selector.title` heads the position column ("Rotary switch", "DIP switch", "Switch").
- `"order": "position"` lists the slots in the window by position (0, 1, 2...) rather than in EPROM order. Use it when the two differ.
- `selector.note` is an optional line under the game list.

## 4. Outputs: one per EPROM

Each output is one image file Multi Builder writes, for one chip on the multi board.

```json
"outputs": [
  {"id": "prg", "file": "prg.bin", "chip": "27C800", "slot_size": "512K", "fill": "FF"},
  {"id": "snd", "file": "snd.bin", "chip": "27C010", "slot_size": "64K",  "fill": "FF"}
]
```

- `id` is how games refer to this chip. `file` is the image's file name.
- `slot_size` is how much of the chip each slot gets. The image is every slot's data back to back, in slot order, so its size is `slot_size` × the number of slots.
  - Sizes can be written as `"512K"` (KB), `"4M"` (MB), `"0x80000"` or a plain number of bytes.
  - If the slots aren't all the same size, use `"slot_sizes": ["512K", "512K", "1M", ...]` with one entry per slot.
- `fill` is the byte (hex) written into a slot whose game doesn't use this chip. `FF` (erased EPROM) is usual.
- `chip` is only for display, in the log and the report.
- `size` (optional) is the exact size the finished image must be, as a cross-check.

## 5. Slots: one per switch position

List the slots **in the order their data sits in the EPROMs**: the first slot is at the start of every chip.

```json
"slots": [
  {"id": "0", "position": "0", "allow": ["@asu_map"], "default": "asuka",    "note": "Asuka map"},
  {"id": "1", "position": "1", "allow": ["@asu_map"], "default": "earthjkr", "note": "Asuka map"},
  {"id": "3", "position": "3", "allow": ["@eto_map"], "default": "eto",      "note": "Eto map"}
]
```

- `id` is the slot's permanent name, used in settings files. Don't change it once people have saved settings.
- `position` is what the window shows and what the player selects on the cabinet.
- `label` (optional) is for your own reference, for example the binary value `"011"`. It isn't shown in the window, but `--slot label:011=...` can use it.
- `allow` lists the games this slot accepts: game ids, and/or `@group` names from `groups`.
- `default` is the recommended game. **Reset to recommended** restores it.
- `note` (optional) is shown beside the slot.

`groups` saves repeating the same list in many slots:

```json
"groups": {
  "asu_map": ["asuka", "asukaj", "earthjkr", "galmedes", "mofflott", "bonzeadv"],
  "eto_map": ["eto", "etoa"]
}
```

### Inverted or reordered switches

If the switch is wired so that positions don't select slots in EPROM order, keep the slots in EPROM order and give each one the position that actually selects it. For a 3-bit rotary switch wired in reverse bit order:

| EPROM slot (binary) | 000 | 001 | 010 | 011 | 100 | 101 | 110 | 111 |
|---|---|---|---|---|---|---|---|---|
| `position` | 0 | 4 | 2 | 6 | 1 | 5 | 3 | 7 |

```json
{"id": "s1", "label": "001", "position": "4", "allow": ["@all"], "default": "game1"}
```

With `"order": "position"`, the window lists them 0-7 and Multi Builder puts each game's data at the right place in the chips. Example 3 has a 2-bit version of this.

## 6. Games

Each game is keyed by its id, which should be its MAME set name. A game has five main parts:

```json
"asuka": {
  "title": "Asuka & Asuka (World)",
  "sets": ["asuka"],
  "roms": {
    "b68-13.ic23": ["855efb3e", 131072],
    "b68-12.ic8":  ["271eeee9", 131072],
    "b68-03.ic30": ["d3a59b10", 524288],
    "b68-11.ic27": ["c378b508", 65536]
  },
  "steps": [
    ["ts", "-interleave", "rom:b68-13.ic23", "rom:b68-12.ic8", "prg.bin"]
  ],
  "parts": {"prg": ["prg.bin", "prg.bin"], "fix": "rom:b68-03.ic30", "snd": "rom:b68-11.ic27"}
}
```

### `title`, `sets` and `roms`

- `title` is the name shown in the drop-downs. Mark modified games, for example `[ported]`, so builders know.
- `sets` are the MAME set names to look in, **clone first, then its parent**. A clone's unchanged files are only in the parent's zip in split sets.
- `roms` lists every file the game needs, as `"name": ["crc32", size in bytes]`. The file is found by CRC and size, so it doesn't matter whether the user's sets are split, merged or non-merged.

**Don't type CRCs by hand.** `tools/roms_json.py` writes this part for you:

```
mame -listxml cadashj > cadashj.xml
python tools/roms_json.py cadashj.xml
```

prints

```json
"cadashj": {
  "title": "Cadash (Japan, version 2)",
  "sets": ["cadashj", "cadash"],
  "roms": {
    "c21_04-2.ic11": ["7a9c1828", 131072],
    "c21-02.9": ["205883b9", 524288]
  },
  "_regions": {
    "maincpu": "c21_04-2.ic11",
    "tc0100scn": "c21-02.9"
  },
  "steps": [],
  "parts": {}
}
```

`_regions` (ignored by Multi Builder) shows which MAME ROM region each file loads into, which tells you which of your chips it belongs in. Without MAME, `python tools/roms_json.py path/to/cadashj.zip` reads the CRCs from the zip instead, but then you add the title and the parent's files yourself. Delete any file the game doesn't need on your board (PLDs, protection MCU dumps you replace, and so on).

### `steps`

Steps turn the ROM files into the data for each chip. They run in order, in a private work folder for this game. Most steps are [ts_rom_tool](https://github.com/twistedsymphony/ts_rom_tool) commands, written exactly as on its command line:

```json
["ts", "-interleave", "rom:b68-13.ic23", "rom:b68-12.ic8", "prg.bin"]
```

- `rom:NAME` is one of the game's input files.
- `kit:PATH` is a file in the kit folder.
- Any other argument is passed as it is. File names without a prefix are files in the work folder.

Common jobs:

| Job | Step |
|---|---|
| Join an even/odd pair of 8-bit ROMs into a 16-bit image | `["ts", "-interleave", "rom:even", "rom:odd", "prg.bin"]` |
| Split a 16-bit image into even/odd bytes | `["ts", "-deinterleave", "prg.bin", "even.bin", "odd.bin"]` |
| Swap the bytes of each 16-bit word | `["ts", "-byteswap", "rom:gfx", "gfx.bin"]` |
| Join files end to end | `["ts", "-multiconcat", "all.bin", "a.bin", "b.bin", "c.bin"]` |
| Pad to a size with FF | `["ts", "-padf", "rom:small", "128K", "padded.bin"]` |
| Apply an IPS patch | `["ts", "-ipsapply", "kit:ips/game_ic11.ips", "rom:ic11", "ic11.bin"]` |
| Make a file of one repeated byte | `["fill", "blank.bin", "32K", "FF"]` |
| Run a kit script | `["py", "kit:scripts/fix.py", "rom:ic11", "out.bin"]` |

> **Size units differ.** In ts_rom_tool, `K` is kilobytes but `M` is **megabits** (`"1M"` = 128 KB, as in "27C010 = 1 Mbit"). In the kit file's own sizes (`slot_size`, the `fill` step), `M` is megabytes. Use `K` everywhere and you can't get it wrong.

### `parts`

`parts` says what goes into this game's slot of each chip, by output id. A part is one file, or a list of files joined end to end:

```json
"parts": {"prg": ["prg.bin", "prg.bin"], "fix": "rom:b68-03.ic30", "snd": "rom:b68-11.ic27"}
```

- Each part must come out **exactly** the slot size. Multi Builder stops with a clear message if it doesn't.
- When a game's data is smaller than the slot, either repeat it (`["prg.bin", "prg.bin"]` puts the 256 KB program twice in a 512 KB slot, which is right when the game ignores the extra address line) or pad it (`-padf`).
- A chip the game doesn't use can be left out of `parts`; its slot is filled with the output's `fill` byte.

### `notes`

`notes` (optional) is free text for the people reading the kit, for example what hardware change a game needs.

## 7. Patched games

Games that need code changes to run on the multi's board ship as **IPS patches** in the kit. IPS files only hold the bytes that change, so the kit doesn't contain the games' copyrighted code; each builder supplies their own ROMs.

**Making the patches.** Patch the original ROM file however you like, then make the IPS from the original and your modified copy:

```
python ts_rom_tool.py -ipscreate c21_14.ic11 c21_14_patched.ic11 ips/cadash_asuka_ic11.ips
```

(`ts_rom_tool.py` is in the [ts_rom_tool repository](https://github.com/twistedsymphony/ts_rom_tool), and in this repository's `ts_rom_tool` folder.) Patch each original ROM file, not the joined image, so the patch depends on only one input file.

**Applying them** is a step, and the patched file is then used like any other:

```json
"steps": [
  ["ts", "-ipsapply", "kit:ips/cadash_asuka_ic11.ips", "rom:c21_14.ic11", "ic11.bin"],
  ["ts", "-ipsapply", "kit:ips/cadash_asuka_ic15.ips", "rom:c21_16.ic15", "ic15.bin"],
  ["ts", "-interleave", "ic11.bin", "ic15.bin", "prg1.bin"]
]
```

**Locking the result with `expect`.** A patched part should always come out the same, so give its CRC32:

```json
"expect": {"prg1": "1f071e7e"}
```

If the patches and the kit file ever get out of step, the build stops instead of producing a bad chip. To find the value:
1. Put any placeholder in, such as `"00000000"`.
2. Build. The build fails with "the prg1 data came out with CRC 1f071e7e, expected 00000000".
3. Test that build in MAME or on hardware.
4. Once it works, paste the real CRC in.

Example 2 is a complete kit built this way.

## 8. Script steps

When ts_rom_tool and IPS can't do the job, write a Python script and run it as a step.

```json
["py", "kit:scripts/graft.py", "rom:er.tbl", "0", "0x800", "rom:er.prg", "0x7000", "prg_tbl.bin"]
```

The rules for a `py` script:

- It runs inside Multi Builder, so the person building doesn't need Python installed.
- The current folder is the game's work folder. `sys.argv[1:]` holds the step's arguments. `rom:` and `kit:` arguments arrive as full paths; everything else arrives exactly as written.
- It can use the Python standard library only. numpy, scipy and other packages aren't included in the program.
- To fail the build, use `raise SystemExit("what went wrong")` or `sys.exit(1)`. Anything it prints goes into the log.
- It can import other `.py` files in its own folder.

[`examples/03_donors_and_scripts/scripts/graft.py`](../examples/03_donors_and_scripts/scripts/graft.py) is a small, complete script. It copies a block of bytes from one ROM into another. That's useful for moving data (a table, a font, a protection chip's contents) from the builder's own ROMs into a patched program, so the kit never carries those bytes. The TASUKA-M8 kit's `scripts/bonze_asuka.py` is a large real one: it rebuilds Bonze Adventure's protection data and re-encodes its sound samples for a different sound chip.

If a script really needs a package outside the standard library, use `"pyext"` instead of `"py"`. It runs the script with the builder's own Python installation (`py` or `python3` on their PATH). Builders then need Python and those packages, so avoid it when you can, and list the packages in `python_modules` so a missing one gives a clear message:

```json
"python_modules": ["numpy"]
```

## 9. Donor PCBs

Some multis fit more than one donor board: two revisions of a PCB, or two games' boards that differ in a few chips. List them, and a drop-down appears at the top of the window:

```json
"donors": [
  {"id": "boardA", "title": "Example Board rev A (27C256 sound ROM)"},
  {"id": "boardB", "title": "Example Board rev B (27C512 sound ROM)"}
],
"donor_title": "Donor board",
"default_donor": "boardA"
```

Then, wherever something depends on the board:

| Need | How |
|---|---|
| A game only works on some boards | `"donors": ["boardB"]` on the game. It's hidden from the drop-downs for other boards. |
| A chip is different on some boards | One output per variant, each with `"donors": [...]`. Only the chosen board's outputs are built. Two outputs can share a `file` name when only one is ever built. |
| A different recommended game per board | `"default_by_donor": {"boardB": "expuzzle"}` on the slot. |
| A different patch per board | Put `{donor}` in the path: `"kit:ips/{donor}/exracer.ips"` uses `ips/boardA/...` or `ips/boardB/...`. |
| Different steps, ROMs or parts per board | `"donor_overrides": {"boardB": {"roms": {...}, "parts": {...}}}` on the game. Each key given replaces that key entirely for that board, so give the whole value. |

Example 3 uses every one of these.

## 10. Test the kit

1. **Load it.** Run Multi Builder with `--kit` and `--list`, or open the kit with **Open kit...**. Any mistake in the file (an unknown game in a slot, a missing slot size, a default that isn't allowed in its slot...) is reported with what and where.

   ```
   python multibuilder.py --kit MYMULTI/MYMULTI.multi.json --list
   ```

2. **Check the ROMs** against your own sets with `--check` or the window's ROMs column. A game showing "wrong version" usually means a CRC in the kit is wrong.
3. **Build every game at least once.** Use `--slot` to put each game in a slot that allows it. Add `--keep-work` to keep each game's work folder, so you can inspect intermediate files.
4. **Test the images.** Run them in MAME if your multi's board can be described there, then on hardware.
5. **Run the self-test** if the kit is in this repository: `python tests/selftest.py`. It loads every kit under `kits/` and `examples/` and checks that every `kit:` file exists for every donor. For example kits, it also forges ROMs with the right CRCs and builds every game for every donor.

## 11. Publish the kit

Put the kit folder in this repository under `kits/<NAME>/` and push. The GitHub workflow builds Multi Builder for Windows, macOS and Linux and makes a `<NAME>_build_tools_<OS>.zip` for each OS, holding your kit and the program. Builders unzip it and run it, with nothing else to install. Pushing a version tag (`v1.3`) also attaches the zips to a GitHub release.

To hand a kit out yourself instead, zip the kit folder together with the program for each OS.

When you change a published kit, change the version in its `name`. Settings files record it, so builders can tell which kit version a build came from. Keep slot `id`s and game ids the same, so people's saved settings still load.

## 12. Step and argument reference

| Step | Does |
|---|---|
| `["ts", COMMAND, args...]` | A ts_rom_tool command, run by the copy built into Multi Builder. |
| `["py", SCRIPT, args...]` | A Python script, run inside Multi Builder ([section 8](#8-script-steps)). |
| `["pyext", SCRIPT, args...]` | A Python script, run by the builder's own Python installation. |
| `["fill", FILE, SIZE, BYTE]` | Makes FILE: SIZE bytes of BYTE (hex; default `00`). SIZE uses the kit's units (`"32K"`). |
| `["copy", FROM, TO]` | Copies a file. |

| Argument | Means |
|---|---|
| `rom:NAME` | The game's input file NAME (from `roms`), as a full path. |
| `kit:PATH` | The file at PATH inside the kit folder, as a full path. |
| `{donor}` | Replaced by the chosen donor PCB's id, anywhere in an argument or part. |
| anything else | Passed as written. Steps run in the game's work folder, so a plain file name is a file there; in `parts`, `fill` and `copy`, a plain name is always a work-folder file. |

See [KIT_FORMAT.md](../KIT_FORMAT.md) for every key, and the build checks Multi Builder makes.
