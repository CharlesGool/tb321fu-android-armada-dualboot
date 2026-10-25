#!/usr/bin/env python3
"""
Collect what Kubuntu needs from Armada into one tar for install-to-rootfs.sh.

Reads Armada's userdata.simg (btrfs inside an Android sparse image) directly,
without expanding it, and packs, with root ownership:
  - usr/lib/modules/<kver>/    the modules that match the kernel in super.img
  - usr/lib/firmware/qcom/sm8650/lenovo/tb321fu/{novatek_ts_boe_fw.bin,battmgr.jsn,vpu33_p4.mbn}
  - everything under kubuntu/rootfs/ in this repository

从 Armada 的 userdata.simg 里直接读取（不展开），打包 Kubuntu 需要的内核模块、固件
和本仓库 kubuntu/rootfs/ 下的文件，交给 install-to-rootfs.sh 安装。

Usage:
    python3 make_bundle.py userdata.simg super.img kubuntu-bundle.tar
"""
import argparse, hashlib, io, os, sys, tarfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from btrfs_sparse import Btrfs, Sparse
from make_esp import Fat32

FW_DIR = 'usr/lib/firmware/qcom/sm8650/lenovo/tb321fu'
FIRMWARE = ['novatek_ts_boe_fw.bin', 'battmgr.jsn', 'vpu33_p4.mbn']
SKIP = {'vmlinuz', 'initramfs.img'}
EXEC = {'usr/local/sbin/y700-slotctl', 'usr/local/bin/y700-reboot-to-android'}
ROOTFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rootfs')


def find_deploy(fs):
    base = '/root/ostree/deploy'
    for osname in fs.listdir(*fs.resolve(base)[:2]):
        dep = f'{base}/{osname}/deploy'
        for name, (t2, i2, ty2) in fs.listdir(*fs.resolve(dep)[:2]).items():
            if ty2 == 2:
                return f'{dep}/{name}'
    raise SystemExit('no ostree deployment found')


def esp_kernel_sha(path):
    fat = Fat32(path)
    entry, first = fat.find(fat.root, 'Image')
    fat.f.seek(entry + 28)
    size = int.from_bytes(fat.f.read(4), 'little')
    h = hashlib.sha256()
    left = size
    for c in fat.chain(first):
        fat.f.seek(fat.off(c))
        chunk = fat.f.read(min(fat.cs, left))
        h.update(chunk)
        left -= len(chunk)
        if left <= 0:
            break
    fat.f.close()
    return h.hexdigest()


def add_bytes(tf, name, data, mode):
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), mode, 0, 0, 'root', 'root'
    tf.addfile(ti, io.BytesIO(data))


def walk(fs, tree, ino, prefix, out):
    for name, (t, i, ty) in sorted(fs.listdir(tree, ino).items()):
        if ty == 2:
            walk(fs, t, i, f'{prefix}/{name}', out)
        elif ty == 1:
            out.append((f'{prefix}/{name}', t, i))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('userdata_simg')
    ap.add_argument('super_img')
    ap.add_argument('out_tar')
    a = ap.parse_args()

    fs = Btrfs(Sparse(a.userdata_simg))
    dep = find_deploy(fs)
    mods = fs.listdir(*fs.resolve(f'{dep}/usr/lib/modules')[:2])
    kvers = [k for k, v in mods.items() if v[2] == 2]
    if len(kvers) != 1:
        raise SystemExit(f'expected one kernel in usr/lib/modules, found {kvers}')
    kver = kvers[0]

    t, i, _ = fs.resolve(f'{dep}/usr/lib/modules/{kver}/vmlinuz')
    if hashlib.sha256(fs.readfile(t, i)).hexdigest() != esp_kernel_sha(a.super_img):
        raise SystemExit('kernel in super.img does not match the modules in userdata.simg; use images from the same release')
    print(f'deployment {dep.rsplit("/", 1)[-1][:12]}…, kernel {kver} matches super.img')

    files = []
    t, i, _ = fs.resolve(f'{dep}/usr/lib/modules/{kver}')
    walk(fs, t, i, f'usr/lib/modules/{kver}', files)
    with tarfile.open(a.out_tar, 'w', format=tarfile.GNU_FORMAT) as tf:
        n = 0
        for path, t, i in files:
            if path.rsplit('/', 1)[-1] in SKIP:
                continue
            add_bytes(tf, path, fs.readfile(t, i), 0o644)
            n += 1
        print(f'modules: {n} files')
        for fw in FIRMWARE:
            t, i, _ = fs.resolve(f'{dep}/{FW_DIR}/{fw}')
            add_bytes(tf, f'{FW_DIR}/{fw}', fs.readfile(t, i), 0o644)
        print(f'firmware: {", ".join(FIRMWARE)}')
        for root, _, names in os.walk(ROOTFS):
            for fn in names:
                p = os.path.join(root, fn)
                rel = os.path.relpath(p, ROOTFS).replace(os.sep, '/')
                mode = 0o755 if rel in EXEC else 0o440 if rel.startswith('etc/sudoers.d/') else 0o644
                add_bytes(tf, rel, open(p, 'rb').read(), mode)
                print(f'rootfs: {rel}')
    print(f'wrote {a.out_tar}')


if __name__ == '__main__':
    main()
