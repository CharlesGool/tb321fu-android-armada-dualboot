#!/usr/bin/env python3
"""
Split the TB321FU "userdata" partition (LUN 0 / sda) into
    userdata (Android, --android-gib) + armada_esp (256 MiB) + armada_root (rest)
by editing a GPT dump offline. Nothing is written to the device.

把 TB321FU 的 userdata（LUN 0 / sda）拆成
    userdata（Android，大小由 --android-gib 指定）+ armada_esp（256 MiB）+ armada_root（剩余空间）
只离线修改 GPT 备份文件，不会写入设备。

Inputs (dump them from the device first, see README):
    primary.bin = first 6 blocks of /dev/block/sda (4096-byte blocks)
    backup.bin  = last 5 blocks of /dev/block/sda

Usage:
    python3 gpt_split.py primary.bin backup.bin new_primary.bin new_backup.bin --android-gib 128
"""
import argparse, struct, uuid, zlib

BS = 4096
ESP_TYPE = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'   # EFI System
LINUX_TYPE = '0fc63daf-8483-4772-8e79-3d69d8477de4'  # Linux filesystem


def parse_header(blob, off):
    (sig, rev, hsz, hcrc, _, cur, alt, first, last, guid, elba, n, esz, ecrc) = \
        struct.unpack('<8sIIIIQQQQ16sQIII', blob[off:off + 92])
    return dict(sig=sig, cur=cur, alt=alt, first=first, last=last, elba=elba, n=n, esz=esz, ecrc=ecrc, hcrc=hcrc, hsz=hsz)


def header_crc_ok(blob, off):
    h = bytearray(blob[off:off + 92])
    crc = struct.unpack_from('<I', h, 16)[0]
    struct.pack_into('<I', h, 16, 0)
    return crc == zlib.crc32(bytes(h)) & 0xffffffff


def list_entries(ents, n, esz):
    out = []
    for i in range(n):
        e = ents[i * esz:(i + 1) * esz]
        t, u, f, l, a = struct.unpack('<16s16sQQQ', e[:56])
        if t == b'\0' * 16:
            continue
        out.append((i, e[56:128].decode('utf-16le').rstrip('\0'), f, l))
    return out


def make_entry(type_guid, first, last, name):
    return struct.pack('<16s16sQQQ', uuid.UUID(type_guid).bytes_le, uuid.uuid4().bytes_le, first, last, 0) \
        + name.encode('utf-16le').ljust(72, b'\0')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('primary'); ap.add_argument('backup'); ap.add_argument('out_primary'); ap.add_argument('out_backup')
    ap.add_argument('--android-gib', type=int, default=128, help='size of the new Android userdata in GiB (default 128)')
    ap.add_argument('--esp-mib', type=int, default=256, help='size of armada_esp in MiB (default 256, must hold super.img)')
    ap.add_argument('--min-root-gib', type=int, default=32, help='refuse if armada_root would be smaller (default 32)')
    a = ap.parse_args()

    prim = open(a.primary, 'rb').read()
    bak = open(a.backup, 'rb').read()
    if len(prim) != 6 * BS or len(bak) != 5 * BS:
        raise SystemExit('expected 6-block primary and 5-block backup dumps (4096-byte blocks)')
    h = parse_header(prim, BS)
    if h['sig'] != b'EFI PART' or not header_crc_ok(prim, BS):
        raise SystemExit('primary GPT header invalid')
    if h['elba'] != 2 or h['esz'] != 128 or h['n'] * h['esz'] > 4 * BS:
        raise SystemExit('unexpected GPT geometry')
    ents = prim[2 * BS:2 * BS + h['n'] * h['esz']]
    if zlib.crc32(ents) & 0xffffffff != h['ecrc']:
        raise SystemExit('primary entry CRC mismatch')
    if bak[4 * BS:4 * BS + 8] != b'EFI PART' or bak[:h['n'] * h['esz']] != ents:
        raise SystemExit('backup GPT does not match primary')

    lst = list_entries(ents, h['n'], h['esz'])
    names = [x[1] for x in lst]
    if 'armada_esp' in names or 'armada_root' in names:
        raise SystemExit('already split (armada_esp / armada_root exist)')
    ud = [x for x in lst if x[1] == 'userdata']
    if len(ud) != 1:
        raise SystemExit('userdata not found exactly once')
    idx, _, first, last = ud[0]
    if last != h['last'] or max(x[3] for x in lst) != last:
        raise SystemExit('userdata is not the last partition on the disk')

    ud_end = first + (a.android_gib << 30) // BS - 1
    esp_f = (ud_end + 1 + 255) // 256 * 256           # 1 MiB aligned
    esp_l = esp_f + (a.esp_mib << 20) // BS - 1
    root_f, root_l = esp_l + 1, h['last']
    root_gib = (root_l - root_f + 1) * BS / 2**30
    if root_gib < a.min_root_gib:
        raise SystemExit(f'armada_root would be only {root_gib:.1f} GiB')

    E = bytearray(ents)
    E[idx * 128 + 40:idx * 128 + 48] = struct.pack('<Q', ud_end)   # shrink userdata, keep its GUIDs
    free = [i for i in range(h['n']) if i not in {x[0] for x in lst}]
    if len(free) < 2:
        raise SystemExit('no free GPT entries')
    E[free[0] * 128:(free[0] + 1) * 128] = make_entry(ESP_TYPE, esp_f, esp_l, 'armada_esp')
    E[free[1] * 128:(free[1] + 1) * 128] = make_entry(LINUX_TYPE, root_f, root_l, 'armada_root')
    E = bytes(E)
    ecrc = zlib.crc32(E) & 0xffffffff

    def header(cur, alt, elba):
        hd = bytearray(prim[BS:BS + 92])
        struct.pack_into('<QQ', hd, 24, cur, alt)
        struct.pack_into('<Q', hd, 72, elba)
        struct.pack_into('<I', hd, 88, ecrc)
        struct.pack_into('<I', hd, 16, 0)
        struct.pack_into('<I', hd, 16, zlib.crc32(bytes(hd)) & 0xffffffff)
        return bytes(hd).ljust(BS, b'\0')

    blk = E.ljust(4 * BS, b'\0')
    open(a.out_primary, 'wb').write(prim[:BS] + header(h['cur'], h['alt'], 2) + blk)
    open(a.out_backup, 'wb').write(blk + header(h['alt'], h['cur'], h['alt'] - 4))
    print(f'userdata    {first}..{ud_end}  {(ud_end - first + 1) * BS / 2**30:.3f} GiB')
    print(f'armada_esp  {esp_f}..{esp_l}  {(esp_l - esp_f + 1) * BS / 2**20:.0f} MiB')
    print(f'armada_root {root_f}..{root_l}  {root_gib:.3f} GiB')
    print(f'backup GPT goes to block {h["alt"] - 4} (= disk blocks - 5)')


if __name__ == '__main__':
    main()
