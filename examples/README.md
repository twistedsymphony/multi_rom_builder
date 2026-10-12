# Example kits

Ready-to-copy kits for learning the kit format. [docs/KIT_GUIDE.md](../docs/KIT_GUIDE.md) walks through them. Each `_how` key in the kit files explains the lines around it; Multi Builder ignores keys that start with `_`.

| Folder | What it shows | Builds from real ROMs? |
|---|---|---|
| [`01_two_in_one`](01_two_in_one/asuka2in1.multi.json) | The smallest useful kit. Two unmodified games on one Asuka & Asuka board, with an OFF/ON switch. ROM pairs are interleaved; other ROMs are copied as they are. | Yes: `asuka`, `mofflott` |
| [`02_region_switch`](02_region_switch/cadash4.multi.json) | Four regions of Cadash ported to the Asuka board. Each region is patched with its own IPS files at build time. Shows a `groups` list, `expect` CRCs and a rotary switch. | Yes: `cadash`, `cadashu`, `cadashj`, `cadashf` |
| [`03_donors_and_scripts`](03_donors_and_scripts/example4in1.multi.json) | Every advanced feature: a donor-board drop-down, an inverted switch, a sound EPROM that differs by donor, per-donor IPS patches through `{donor}`, `donor_overrides`, a game limited to one donor, a Python script step ([`graft.py`](03_donors_and_scripts/scripts/graft.py)), and `fill` and `-padf` steps. | No: the board, games and CRCs are made up |

To try one, start Multi Builder and use **Open kit...**, or run it from the command line:

```
python multibuilder.py --kit examples/01_two_in_one/asuka2in1.multi.json --list
python multibuilder.py --kit examples/01_two_in_one/asuka2in1.multi.json --roms D:/MAME/roms --out D:/burn/test
```

To start your own kit, copy the example closest to your multi into `kits/<NAME>/` and edit it. `tests/selftest.py` builds every example for every donor with made-up ROMs, so the examples stay correct as Multi Builder changes.

Examples 1 and 2 are for learning the format: their chip layouts are illustrative, not a tested multi board design.
