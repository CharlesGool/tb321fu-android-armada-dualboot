# raw -> Android sparse. Zero blocks become FILL(0) chunks so the target is really zeroed.
import struct, sys, os
src, dst = sys.argv[1], sys.argv[2]
BS = 4096
total = os.path.getsize(src) // BS
out = open(dst, 'wb'); out.write(b'\0' * 28)
n = 0
def raw(data, blocks):
    global n
    out.write(struct.pack('<HHII', 0xCAC1, 0, blocks, 12 + blocks * BS)); out.write(data); n += 1
def fill0(blocks):
    global n
    out.write(struct.pack('<HHII', 0xCAC2, 0, blocks, 16)); out.write(b'\0\0\0\0'); n += 1
with open(src, 'rb') as f:
    pend = bytearray(); pb = 0; zb = 0
    while True:
        buf = f.read(BS * 256)
        if not buf: break
        for i in range(0, len(buf), BS):
            b = buf[i:i + BS]
            if not any(b):
                if pb: raw(bytes(pend), pb); pend = bytearray(); pb = 0
                zb += 1
            else:
                if zb: fill0(zb); zb = 0
                pend += b; pb += 1
                if pb >= 16384: raw(bytes(pend), pb); pend = bytearray(); pb = 0
    if pb: raw(bytes(pend), pb)
    if zb: fill0(zb)
out.seek(0); out.write(struct.pack('<IHHHHIIII', 0xED26FF3A, 1, 0, 28, 12, BS, total, n, 0)); out.close()
print('chunks', n, 'blocks', total)
