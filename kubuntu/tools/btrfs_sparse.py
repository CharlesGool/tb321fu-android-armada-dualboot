#!/usr/bin/env python3
"""Read-only btrfs reader working directly on an Android sparse image.

Enough of btrfs to pull files out of Armada's userdata.simg: single device,
chunk tree, subvolumes, inline and regular extents, zlib/zstd compression.

usage: btrfs_sparse.py <userdata.simg> ls  <path>
       btrfs_sparse.py <userdata.simg> cat <path>
       btrfs_sparse.py <userdata.simg> get <path> <out_dir>
Paths start at the top-level subvolume; subvolumes are crossed transparently.
"""
import bisect, os, struct, sys, zlib
import zstandard

# ---------- sparse image ----------
class Sparse:
    def __init__(self, path):
        self.f = open(path, 'rb')
        h = self.f.read(28)
        magic, _, _, fhs, chs, bs, tb, tc, _ = struct.unpack('<IHHHHIIII', h)
        assert magic == 0xED26FF3A
        self.bs = bs
        self.size = tb * bs
        self.f.seek(fhs)
        self.starts, self.chunks = [], []
        out = 0
        for _ in range(tc):
            t, _, csz, tsz = struct.unpack('<HHII', self.f.read(chs))
            pos = self.f.tell()
            n = csz * bs
            if t == 0xCAC1:
                self.chunks.append(('raw', out, n, pos))
            elif t == 0xCAC2:
                self.chunks.append(('fill', out, n, self.f.read(4)))
            elif t == 0xCAC3:
                self.chunks.append(('skip', out, n, None))
            if t != 0xCAC4:  # CRC chunks carry no data
                self.starts.append(out)
                out += n
            self.f.seek(pos + tsz - chs)

    def read(self, off, n):
        res = bytearray()
        i = bisect.bisect_right(self.starts, off) - 1
        while n > 0:
            kind, start, length, extra = self.chunks[i]
            rel = off - start
            take = min(n, length - rel)
            if kind == 'raw':
                self.f.seek(extra + rel)
                res += self.f.read(take)
            elif kind == 'fill':
                res += (extra * ((take // 4) + 2))[rel % 4:rel % 4 + take]
            else:
                res += bytes(take)
            off += take; n -= take; i += 1
        return bytes(res)

# ---------- btrfs ----------
def key(b, o):
    return struct.unpack_from('<QBQ', b, o)

class Btrfs:
    def __init__(self, dev):
        self.dev = dev
        sb = dev.read(0x10000, 4096)
        assert sb[64:72] == b'_BHRfS_M', 'not btrfs'
        self.root, self.chunk_root = struct.unpack_from('<QQ', sb, 80)
        self.nodesize = struct.unpack_from('<I', sb, 148)[0]
        arr_sz = struct.unpack_from('<I', sb, 160)[0]
        self.chunks = []
        arr = sb[811:811 + arr_sz]
        p = 0
        while p < len(arr):
            _, _, logical = key(arr, p); p += 17
            p = self._add_chunk(arr, p, logical)
        for k, d in self.items(self.chunk_root, (256, 228, 0), (256, 228, 2**64 - 1)):
            self._add_chunk(d, 0, k[2])
        self.chunks.sort()
        self.fs_trees = {}
        for k, d in self.items(self.root, (0, 132, 0), (2**64 - 1, 132, 2**64 - 1)):
            if k[1] == 132:
                self.fs_trees[k[0]] = struct.unpack_from('<Q', d, 176)[0]

    def _add_chunk(self, b, p, logical):
        length = struct.unpack_from('<Q', b, p)[0]
        nst = struct.unpack_from('<H', b, p + 44)[0]
        phys = struct.unpack_from('<Q', b, p + 48 + 8)[0]
        if not any(c[0] == logical for c in self.chunks):
            self.chunks.append((logical, length, phys))
        return p + 48 + 32 * nst

    def read(self, logical, n):
        out = bytearray()
        while n > 0:
            for start, length, phys in self.chunks:
                if start <= logical < start + length:
                    take = min(n, start + length - logical)
                    out += self.dev.read(phys + logical - start, take)
                    logical += take; n -= take
                    break
            else:
                raise ValueError('unmapped logical %x' % logical)
        return bytes(out)

    def items(self, bytenr, lo, hi):
        node = self.read(bytenr, self.nodesize)
        nr = struct.unpack_from('<I', node, 96)[0]
        level = node[100]
        if level == 0:
            for i in range(nr):
                o = 101 + i * 25
                k = key(node, o)
                if lo <= k <= hi:
                    doff, dsz = struct.unpack_from('<II', node, o + 17)
                    yield k, node[101 + doff:101 + doff + dsz]
            return
        ptrs = [(key(node, 101 + i * 33), struct.unpack_from('<Q', node, 101 + i * 33 + 17)[0]) for i in range(nr)]
        for i, (k, ptr) in enumerate(ptrs):
            nxt = ptrs[i + 1][0] if i + 1 < nr else None
            if k > hi:
                break
            if nxt is not None and nxt <= lo:
                continue
            yield from self.items(ptr, lo, hi)

    # ----- fs level -----
    def listdir(self, tree, ino):
        res = {}
        for k, d in self.items(self.fs_trees[tree], (ino, 96, 0), (ino, 96, 2**64 - 1)):
            loc = key(d, 0)
            nlen = struct.unpack_from('<H', d, 27)[0]
            name = d[30:30 + nlen].decode('utf-8', 'surrogateescape')
            if loc[1] == 132:  # subvolume
                res[name] = (loc[0], 256, 2)
            else:
                res[name] = (tree, loc[0], d[29])
        return res

    def inode(self, tree, ino):
        for k, d in self.items(self.fs_trees[tree], (ino, 1, 0), (ino, 1, 2**64 - 1)):
            size = struct.unpack_from('<Q', d, 16)[0]
            mode = struct.unpack_from('<I', d, 52)[0]
            return size, mode
        raise KeyError(ino)

    def readfile(self, tree, ino):
        size, _ = self.inode(tree, ino)
        buf = bytearray(size)
        for k, d in self.items(self.fs_trees[tree], (ino, 108, 0), (ino, 108, 2**64 - 1)):
            foff = k[2]
            ram = struct.unpack_from('<Q', d, 8)[0]
            comp, typ = d[16], d[20]
            if typ == 0:
                data = self._decomp(d[21:], comp, ram)
            else:
                dbytenr, dnum, eoff, nbytes = struct.unpack_from('<QQQQ', d, 21)
                if dbytenr == 0:
                    continue  # hole
                if comp:
                    data = self._decomp(self.read(dbytenr, dnum), comp, ram)[eoff:eoff + nbytes]
                else:
                    data = self.read(dbytenr + eoff, nbytes)
            end = min(size, foff + len(data))
            buf[foff:end] = data[:end - foff]
        return bytes(buf)

    @staticmethod
    def _decomp(data, comp, ram):
        if comp == 0:
            return data
        if comp == 1:
            return zlib.decompress(data)
        if comp == 3:
            return zstandard.ZstdDecompressor().decompressobj().decompress(data)[:ram]
        raise ValueError('compression %d' % comp)

    def resolve(self, path):
        tree, ino, typ = 5, 256, 2
        for part in [p for p in path.split('/') if p]:
            ents = self.listdir(tree, ino)
            if part not in ents:
                raise FileNotFoundError(path + ' : ' + part)
            tree, ino, typ = ents[part]
            if typ == 7:  # symlink inside path: follow relative target once
                raise NotImplementedError('symlink in path at ' + part)
        return tree, ino, typ

def extract(fs, tree, ino, typ, out, stats):
    if typ == 2:
        os.makedirs(out, exist_ok=True)
        for name, (t, i, ty) in fs.listdir(tree, ino).items():
            extract(fs, t, i, ty, os.path.join(out, name), stats)
    elif typ == 1:
        with open(out, 'wb') as f:
            f.write(fs.readfile(tree, ino))
        stats[0] += 1
    elif typ == 7:
        with open(out + '.symlink', 'wb') as f:
            f.write(fs.readfile(tree, ino))
        stats[1] += 1

if __name__ == '__main__':
    img, cmd, path = sys.argv[1:4]
    fs = Btrfs(Sparse(img))
    t, i, ty = fs.resolve(path)
    if cmd == 'ls':
        for name, (tt, ii, tyy) in sorted(fs.listdir(t, i).items()):
            print({1: 'f', 2: 'd', 7: 'l'}.get(tyy, '?'), name)
    elif cmd == 'cat':
        sys.stdout.buffer.write(fs.readfile(t, i))
    elif cmd == 'get':
        stats = [0, 0]
        extract(fs, t, i, ty, sys.argv[4], stats)
        print('files', stats[0], 'symlinks', stats[1])
