# Multi Builder

Builds the EPROM images for an arcade multi-game kit from your MAME ROM sets.

This repository holds the program only. Each multi's **kit** (its `*.multi.json` configuration plus any IPS patches and scripts its games need) is published separately by the multi's maker, usually as a *build-tools* zip that has the kit and the program together.

**Documentation:**
- [User guide](docs/USER_GUIDE.md): every part of the window, what a build produces, settings files, the command line and troubleshooting.
- [Making a kit](docs/KIT_GUIDE.md): a step-by-step guide to writing a kit for a new multi, with [example kits](examples) to copy.
- [Kit format reference](KIT_FORMAT.md): every key in a `.multi.json` file.

**Kit makers:**
- Multi Builder is the same program for every multi; everything specific to one multi lives in its kit folder.
- Download the program for each OS from this repository's [releases](https://github.com/twistedsymphony/multi_rom_builder/releases) (or a workflow run's artifacts), put it beside your kit, and zip them up for your users.
- [ts_rom_tool](https://github.com/twistedsymphony/ts_rom_tool) is built in, as a git submodule compiled into the program.

## Using it

The [user guide](docs/USER_GUIDE.md) explains each part of the window in detail.

1. Unzip the build tools for your multi and run Multi Builder. It loads the kit beside it. (With the program on its own, use **Open kit...** to load a kit.)
2. If the kit supports more than one donor PCB, choose yours from the drop-down at the top.
3. **ROMs folder**: choose the folder holding your MAME ROM sets.
   - Zips and unzipped set folders both work.
   - Split, merged and non-merged sets all work.
   - .7z is not supported.
4. Each switch position shows its recommended game and whether all of that game's ROMs were found.
   - Use the drop-down to pick another game or region. A position only offers games the hardware (and your donor PCB) supports there.
   - "Reset to recommended" restores the kit's defaults.
5. **Output folder**: where the images go.
6. **Build**. Multi Builder:
   - checks every input ROM by CRC
   - runs each game's build steps
   - checks every slot and image size
   - writes the EPROM images, `build_report.txt` (slot list, sizes, CRC32 and SHA1 of every image) and `build_settings.json`

**Save settings... / Load settings...** store your choices (kit, donor PCB, folders, games) in a file. Load it later to make changes, share it, or repeat the build from the command line. Every build also leaves its own `build_settings.json` in the output folder.

### Command line

On Windows use `MultiBuilderCLI.exe`, because `MultiBuilder.exe` has no console window.

```
MultiBuilder --profile build_settings.json                     repeat a saved build
MultiBuilder --roms ROMDIR --out OUTDIR [--donor ID] [--slot 4=jigkmgri ...]
             [--profile FILE] [--save-profile FILE [--build]] [--check] [--list] [--kit KIT.multi.json]
MultiBuilder --version                                         program and built-in ts_rom_tool versions
```

`--slot POSITION=GAME` uses the switch position (`id:SLOT` and `label:SLOT` also work). Options on the command line override the profile's.

## Getting the source

```
git clone --recursive https://github.com/twistedsymphony/multi_rom_builder
```

If you cloned without `--recursive`, run `git submodule update --init` to fetch ts_rom_tool.

`multibuilder.py` uses only the Python standard library and runs from source with Python 3.10+ (with Tk): `python multibuilder.py`.

## Building the program

Each operating system needs its own build, and every build works with every kit. Compiled, the program is about 12 MB.

- **GitHub:** every push to `main` runs the "Build Multi Builder" workflow on Windows, macOS and Linux.
  1. It runs `tests/selftest.py` against the source and the compiled program.
  2. It produces `MultiBuilder_<OS>.zip` (the program) under the run's artifacts.
  3. Pushing a tag such as `v1.3` also attaches those zips to a GitHub release.
- **Locally:** `build.bat` (Windows) or `./build.sh` (Linux / macOS). The program lands in `dist/`.
- **macOS:** the build is unsigned, so the first launch needs right-click > Open.

### Updating ts_rom_tool

ts_rom_tool is pinned to a specific commit. Dependabot opens a pull request when ts_rom_tool has new commits; merging it rebuilds the programs with the new version.

To update by hand:

```
git -C ts_rom_tool pull origin main
git add ts_rom_tool && git commit -m "Update ts_rom_tool"
```

`MultiBuilder --version` and every build log show which ts_rom_tool version is built in.

## Repository layout

| path | |
|---|---|
| `multibuilder.py` | the program (GUI and command line) |
| `ts_rom_tool/` | submodule: twistedsymphony/ts_rom_tool |
| `docs/` | user guide, kit-making guide, and the TASUKA-M8 kit file as a reference |
| `examples/` | example kits to learn from and copy |
| `tools/roms_json.py` | writes a game's ROM list from `mame -listxml` output or ROM zips |
| `tests/selftest.py` | kit checks, an end-to-end build, and builds of every example kit with made-up ROMs |
| `MultiBuilder.spec` | PyInstaller build definition |
| `KIT_FORMAT.md` | kit format reference |

## License

GNU General Public License v3.0 (see [LICENSE](LICENSE)).
