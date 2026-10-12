# Multi Builder kit format (format 1, Multi Builder 1.3)

This is the reference for every key. For a step-by-step walk-through with examples, see [docs/KIT_GUIDE.md](docs/KIT_GUIDE.md); ready-to-copy kits are in [examples/](examples).

A kit is a folder holding one `<name>.multi.json` file plus any files its build steps use (IPS patches, scripts). ts_rom_tool is built into Multi Builder, so kits don't need to include it. Multi Builder loads the first `*.multi.json` it finds beside itself; **Open kit...** loads any other. Nothing in the tool is specific to one multi, so a new multi only needs a new kit folder.

Keys starting with `_` are ignored, so you can use them for comments (`"_note": "..."`).

## Top level

| key | meaning |
|---|---|
| `format` | always `1` for now |
| `name` | shown as the window title |
| `board`, `description` | shown under the title |
| `selector` | how the player picks a game: `{"title": "Rotary switch", "order": "position", "note": "..."}`. `title` heads the slot column; `"order": "position"` lists slots by switch position instead of EPROM order |
| `donors` | optional list of donor PCBs, e.g. `[{"id": "pcbA", "title": "Original PCB"}, ...]`. When present, a drop-down appears at the top. Leave it out for kits that only fit one board. |
| `donor_title`, `default_donor` | optional: the drop-down's label (default "Donor PCB") and initial choice (default: the first donor) |
| `ts_rom_tool` | optional: path of a ts_rom_tool.py inside the kit, used instead of the built-in one (only for a kit that needs a newer ts_rom_tool than the program was built with) |
| `outputs` | the EPROM images to build (see below) |
| `slots` | the game slots, in the order they sit in each EPROM |
| `groups` | named lists of game ids, used by the slots' `allow` lists |
| `games` | every game the kit can build |

## outputs

```json
{"id": "prg1", "file": "prg1.bin", "chip": "27C322", "slot_size": "512K", "fill": "00"}
```

- Each image is the slots' data back to back, in slot order.
- `slot_size` can be bytes, `"64K"`, `"4M"` or `"0x80000"`. Here `M` means megabytes; in ts_rom_tool commands `M` means megabits (`"1M"` = 128 KB), so prefer `K` in both. If slots differ in size, use `"slot_sizes": [...]` with one entry per slot.
- `size` is optional. When present, the finished image must be exactly that size.
- `fill` is the byte (hex) used for a slot whose game has no data for this image.
- `chip` is shown in the log and the build report.
- `donors` (optional) builds the image only for those donor PCBs.

## slots

```json
{"id": "4", "position": "4", "label": "100", "allow": ["@asu_map"], "default": "bonzeadv", "note": "Asuka map"}
```

- **Order and position.** Slots are listed in the order their data sits in each EPROM.
  - `position` is what the player selects on the cabinet (switch or dial position) and what the window shows.
  - For a switch wired inverted, give each slot its real position. For example, the slot holding binary 001 data gets `"position": "4"`.
  - `label` is optional and for your own reference; it isn't shown in the window.
- `allow` lists game ids and/or `@group` names. Only these games (minus any not available for the chosen donor PCB) appear in the slot's drop-down, and the build refuses anything else.
- `default` is the recommended game for the slot ("Reset to recommended" restores it).
- `default_by_donor` (optional), e.g. `{"pcbB": "asuka"}`, sets a different recommendation per donor PCB.
- `note` is shown beside the slot.

## games

```json
"asuka": {
  "title": "Asuka & Asuka (World)",
  "sets": ["asuka"],
  "roms": {"b68-13.ic23": ["855efb3e", 131072], "...": ["crc32", size]},
  "steps": [["ts", "-interleave", "rom:b68-13.ic23", "rom:b68-12.ic8", "prg.bin"]],
  "parts": {"prg1": ["prg.bin", "prg.bin"], "fix1": "rom:b68-03.ic30"},
  "expect": {"prg1": "1f071e7e"},
  "notes": "..."
}
```

- **`sets`**: MAME set names to search, clone first, then parent. A set can be a zip (`asuka.zip`) or a folder (`asuka/`) in the user's ROMs folder.
  - Files are matched by CRC32 and size, so split, merged (clones in sub-folders inside the parent zip) and non-merged sets all work.
  - If a file isn't in the listed sets, every zip in the ROMs folder is searched by CRC.
- **`roms`**: every input file, as `name: [crc32, size]`. `tools/roms_json.py` writes this from `mame -listxml` output or from ROM zips. A file named right but with a different CRC is reported as "wrong version".
- **`steps`**: run in order, in a private work folder for the game (which is the current folder while a step runs). Arguments are:
  - `rom:NAME`: an input file from `roms`, passed as a full path
  - `kit:PATH`: a file inside the kit folder, passed as a full path
  - anything else: passed as written, so a plain file name is a file in the work folder and sizes, offsets and flags (`"128K"`, `"0x7000"`) stay as they are. In `fill` and `copy` steps, a plain name is always a work-folder file.
- **`parts`**: for each output id, the file (or list of files, joined in order) that goes in the slot. The result must be exactly the slot size.
- **`expect`** (optional): CRC32 a part must come out with. Use it for deterministic patched data, so a build with mismatched kit files fails instead of producing a bad EPROM.
- **`python_modules`** (optional): modules a `py` step needs. The build stops with a clear message if they're unavailable.
- **`donors`** (optional): the donor PCBs this game can be built for. It is hidden in the drop-downs for other donors.
- **`donor_overrides`** (optional): per donor PCB, replacement values for any of the game's keys (`steps`, `parts`, `roms`, `expect`, ...). For example:
  `"donor_overrides": {"pcbB": {"steps": [["ts", "-ipsapply", "kit:ips/pcbB/game_ic11.ips", "rom:ic11", "ic11.bin"], ...]}}`
- **`{donor}`** in any step argument or part is replaced by the chosen donor id, so `"kit:ips/{donor}/game_ic11.ips"` picks a per-donor patch without repeating the steps.

### step types

| step | does |
|---|---|
| `["ts", "-interleave", a, b, out]` | any ts_rom_tool command, same arguments as on the command line (`-interleave`, `-deinterleave`, `-concat`, `-multiconcat`, `-byteswap`, `-wordswap`, `-nibbleswap`, `-split`, `-half`, `-trunc`, `-padz`, `-padf`, `-fillz`, `-fillf`, `-ipsapply`, ...), run by the ts_rom_tool built into Multi Builder. |
| `["py", "kit:scripts/x.py", args...]` | runs a kit script inside Multi Builder, with the work folder as the current folder and `sys.argv` set to the arguments. The script reports failure with `raise SystemExit("message")` or `sys.exit(1)`. |
| `["pyext", "kit:scripts/x.py", args...]` | runs the script with the user's own Python installation (py / python3 on the PATH), for scripts needing modules the compiled tool doesn't include. |
| `["fill", "out.bin", "128K", "FF"]` | writes a file of one repeated byte |
| `["copy", a, b]` | copies a file |

### What `py` scripts can import in the compiled tool

`py` scripts can import the Python standard library. Multi Builder doesn't include numpy or scipy, which keeps it small. A script needing other packages must use `pyext`, which needs the user to have Python and those packages installed.

## Checks the build makes

- Every input ROM is present with the right CRC and size before anything is built.
- Every step must succeed: ts_rom_tool errors and script exits stop the build.
- Each part must be exactly its slot's size, and match `expect` when given.
- Each image must have the slots' total size (or `size`).
- Each image is read back after writing.
- `build_report.txt` lists the slot assignments and each image's size, CRC32 and SHA1.
- `build_settings.json` records the choices made (see below).

## Settings files (build profiles)

A settings file records one user's choices:
- the kit
- the donor PCB
- the ROMs and output folders
- the game at each switch position

It comes from **Save settings...** in the window, `--save-profile` on the command line, or automatically as `build_settings.json` beside every build's output.

**Load settings...** brings a file back into the window to edit. `MultiBuilder --profile FILE` (`MultiBuilderCLI.exe` on Windows) repeats the build from the command line.

```json
{
  "multibuilder_profile": 1,
  "kit": "TASUKA-M8.multi.json",
  "kit_name": "TASUKA-M8 v1.1",
  "donor": null,
  "roms": "D:/MAME/roms",
  "output": "D:/burn/tasuka",
  "slots": [
    {"slot": "4", "position": "4", "game": "jigkmgri", "title": "Jigoku Meguri (Japan, rev 1) [ported]"}
  ]
}
```

- Slots are matched by `slot` (the slot id). Any slot left out keeps its recommended game.
- `title` and `position` are only there to make the file readable.
- The `kit` path is relative to the settings file when they're near each other.
