# Multi Builder

Builds the EPROM images for an arcade multi-game kit from your MAME ROM sets.

**Users** get a *build-tools* zip for their multi:
- the Multi Builder program
- the kit configuration (`*.multi.json`)
- the IPS patches and scripts its games need

**Kit makers:**
- Multi Builder is the same program for every multi; everything specific to one multi lives in its kit folder ([KIT_FORMAT.md](KIT_FORMAT.md)).
- [ts_rom_tool](https://github.com/twistedsymphony/ts_rom_tool) is built in, as a git submodule compiled into the program.

## Using it

1. Unzip the build tools and run Multi Builder. It loads the kit beside it.
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
  2. It produces one `<KIT>_build_tools_<OS>.zip` per kit folder (the kit plus the program), under the run's artifacts.
  3. Pushing a tag such as `v1.2` also attaches those zips to a GitHub release.
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
| `kits/<name>/` | one folder per multi; each becomes a build-tools zip |
| `tests/selftest.py` | kit checks and an end-to-end build with made-up ROMs |
| `MultiBuilder.spec` | PyInstaller build definition |
| `KIT_FORMAT.md` | how to write a kit |

## License

GNU General Public License v3.0 (see [LICENSE](LICENSE)).
