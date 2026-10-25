#!/usr/bin/env python3
"""
Build the armada_esp image for Kubuntu from Armada's super.img.

Armada's GRUB FAT already carries a kernel, initramfs and DTBs that work on
BOE-panel units. This only rewrites /boot/grub/grub.cfg so that kernel boots
the Kubuntu rootfs on armada_root. Everything else in the FAT stays byte-identical.

用 Armada 的 super.img 生成给 Kubuntu 用的 armada_esp 镜像：
只改写 /boot/grub/grub.cfg，让 Armada 的内核 + BOE 设备树去启动 armada_root 上的 Kubuntu。

Usage:
    python3 make_esp.py super.img kubuntu_esp.img
"""
import argparse, shutil, struct

GRUB_CFG = """set timeout=5
set default=0
set gfxpayload=keep
set common="root=PARTLABEL=armada_root rootfstype=ext4 rw rootwait console=tty0 loglevel=4 allow_mismatched_32bit_el0 fw_devlink.strict=1 pcie_ports=compat swiotlb=8192 efi=novamap fbcon=map:0 enforcing=0"
menuentry "Kubuntu (Armada kernel, BOE)" {
    devicetree /dtb/sm8650-lenovo-tb321fu.dtb
    linux /Image ${common}
    initrd /initramfs.img
}
menuentry "Kubuntu verbose" {
    devicetree /dtb/sm8650-lenovo-tb321fu.dtb
    linux /Image ${common} ignore_loglevel systemd.show_status=1 printk.time=1
    initrd /initramfs.img
}
"""


class Fat32:
    def __init__(self, path):
        self.f = open(path, 'r+b')
        b = self.f.read(512)
        if b[82:90] != b'FAT32   ':
            raise SystemExit('not a FAT32 image')
        self.bps, self.spc, self.rsv, self.nf = struct.unpack('<HBHB', b[11:17])
        self.fatsz = struct.unpack('<I', b[36:40])[0]
        self.root = struct.unpack('<I', b[44:48])[0]
        self.fat0 = self.rsv * self.bps
        self.data0 = (self.rsv + self.nf * self.fatsz) * self.bps
        self.cs = self.bps * self.spc
        self.f.seek(self.fat0)
        self.fat = self.f.read(self.fatsz * self.bps)

    def chain(self, c):
        out = []
        while c < 0x0FFFFFF8:
            out.append(c)
            c = struct.unpack_from('<I', self.fat, c * 4)[0] & 0x0FFFFFFF
        return out

    def off(self, c):
        return self.data0 + (c - 2) * self.cs

    def find(self, dir_cluster, name):
        """Return (absolute offset of the 8.3 entry, first cluster) for name in a directory."""
        for c in self.chain(dir_cluster):
            self.f.seek(self.off(c))
            blk = self.f.read(self.cs)
            for i in range(0, self.cs, 32):
                e = blk[i:i + 32]
                if e[0] == 0:
                    raise SystemExit(f'{name}: not found')
                if e[0] == 0xE5 or e[11] == 0x0F:
                    continue
                n = e[:8].decode().strip()
                ext = e[8:11].decode().strip()
                if (n + ('.' + ext if ext else '')).upper() == name.upper():
                    first = (struct.unpack_from('<H', e, 20)[0] << 16) | struct.unpack_from('<H', e, 26)[0]
                    return self.off(c) + i, first
        raise SystemExit(f'{name}: not found')

    def replace(self, path, data):
        """Overwrite an existing file in place. The new content must fit in its clusters."""
        cl = self.root
        parts = path.strip('/').split('/')
        for p in parts[:-1]:
            _, cl = self.find(cl, p)
        entry, first = self.find(cl, parts[-1])
        ch = self.chain(first)
        if len(data) > len(ch) * self.cs:
            raise SystemExit(f'{path}: new content ({len(data)} B) does not fit in {len(ch) * self.cs} B')
        for k, c in enumerate(ch):
            self.f.seek(self.off(c))
            self.f.write(data[k * self.cs:(k + 1) * self.cs].ljust(self.cs, b'\0'))
        need = max(1, -(-len(data) // self.cs))
        for fi in range(self.nf):  # shorten the chain and free the rest, in every FAT copy
            base = self.fat0 + fi * self.fatsz * self.bps
            for k, c in enumerate(ch[need - 1:], start=need - 1):
                self.f.seek(base + c * 4)
                self.f.write(struct.pack('<I', 0x0FFFFFFF if k == need - 1 else 0))
        self.f.seek(entry + 28)
        self.f.write(struct.pack('<I', len(data)))
        self.f.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('super_img', help="Armada super.img (GRUB FAT)")
    ap.add_argument('out_img')
    a = ap.parse_args()
    shutil.copyfile(a.super_img, a.out_img)
    Fat32(a.out_img).replace('boot/grub/grub.cfg', GRUB_CFG.encode())
    print(f'wrote {a.out_img}')


if __name__ == '__main__':
    main()
