"""Copy a block of bytes from one file into another.

    graft.py SOURCE SOURCE_OFFSET LENGTH TARGET TARGET_OFFSET OUTPUT

Offsets and length take decimal or 0x hex. OUTPUT is TARGET with LENGTH bytes at TARGET_OFFSET
replaced by the bytes at SOURCE_OFFSET in SOURCE. Typical use: move a table (high scores, a font,
a protection chip's data) out of one of the user's ROMs into a patched program, so the kit itself
never has to carry the copyrighted bytes.

A Multi Builder "py" step runs this inside the program, in the game's work folder.
Errors are reported with SystemExit("message"), which stops the build and shows the message.
"""
import sys


def num(s):
    return int(s, 0)


def main(argv):
    if len(argv) != 6:
        raise SystemExit(__doc__)
    src, so, n, dst, do, out = argv[0], num(argv[1]), num(argv[2]), argv[3], num(argv[4]), argv[5]
    with open(src, 'rb') as f:
        s = f.read()
    with open(dst, 'rb') as f:
        d = bytearray(f.read())
    if so + n > len(s):
        raise SystemExit('graft: %s is only %d bytes, cannot read %d bytes at 0x%X' % (src, len(s), n, so))
    if do + n > len(d):
        raise SystemExit('graft: %s is only %d bytes, cannot write %d bytes at 0x%X' % (dst, len(d), n, do))
    d[do:do + n] = s[so:so + n]
    with open(out, 'wb') as f:
        f.write(d)
    print('graft: %d bytes from %s @0x%X -> %s @0x%X' % (n, src, so, out, do))


if __name__ == '__main__':
    main(sys.argv[1:])
