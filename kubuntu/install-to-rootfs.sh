#!/system/bin/sh
# Run on Android as root, after flashing the Kubuntu rootfs to armada_root:
#   adb push kubuntu-bundle.tar install-to-rootfs.sh /data/local/tmp/
#   adb shell su -c "sh /data/local/tmp/install-to-rootfs.sh /data/local/tmp/kubuntu-bundle.tar"
#
# Grows the ext4 filesystem to the whole partition, then installs the Armada
# kernel modules, the BOE firmware and the slot helpers from make_bundle.py.
#
# 在 Android 上以 root 运行：把 ext4 扩到整个分区，再装入 make_bundle.py 打好的
# Armada 内核模块、BOE 固件和切槽工具。
set -e

BUNDLE=${1:?usage: install-to-rootfs.sh kubuntu-bundle.tar}
DEV=/dev/block/by-name/armada_root
MNT=/data/local/tmp/kubuntu-root

[ -f "$BUNDLE" ] || { echo "no such file: $BUNDLE"; exit 1; }
[ -b "$DEV" ] || { echo "$DEV not found; is the dual-boot partition table in place?"; exit 1; }
if grep -q " $MNT " /proc/mounts; then echo "$MNT is already mounted"; exit 1; fi

echo "== checking and growing the filesystem"
e2fsck -f -y "$DEV" | tail -1
resize2fs "$DEV" | tail -1

mkdir -p "$MNT"
mount -t ext4 -o rw "$DEV" "$MNT"
trap 'cd /; sync; umount "$MNT" 2>/dev/null; rmdir "$MNT" 2>/dev/null' EXIT

[ -x "$MNT/usr/bin/python3" ] || { echo "armada_root does not look like the Kubuntu rootfs"; exit 1; }

echo "== installing bundle"
kver=$(tar -tf "$BUNDLE" | sed -n 's#^usr/lib/modules/\([^/]*\)/.*#\1#p' | head -1)
rm -rf "$MNT/usr/lib/modules/$kver"
tar -xf "$BUNDLE" -C "$MNT"
ln -sf /etc/systemd/system/y700-mark-boot-successful.service \
    "$MNT/etc/systemd/system/multi-user.target.wants/y700-mark-boot-successful.service"

for u in "$MNT"/home/*; do
    [ -d "$u" ] || continue
    d="$u/Desktop"; [ -d "$u/桌面" ] && d="$u/桌面"
    owner=$(stat -c %u:%g "$u")
    mkdir -p "$d"
    cp "$MNT/usr/share/applications/y700-reboot-to-android.desktop" "$d/"
    chmod 755 "$d/y700-reboot-to-android.desktop"
    chown "$owner" "$d" "$d/y700-reboot-to-android.desktop"
done

echo "== checks"
for d in proc sys dev; do mount --bind /$d "$MNT/$d"; done
chroot "$MNT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin sh -c '
    visudo -cf /etc/sudoers.d/y700-slotctl &&
    python3 -c "print(\"python ok\")"'
for d in proc sys dev; do umount "$MNT/$d"; done
echo "modules: $kver ($(du -sh "$MNT/usr/lib/modules/$kver" | cut -f1)); $(df -h "$MNT" | tail -1 | awk '{print $2 " filesystem"}')"
echo "done. Next: adb reboot bootloader && fastboot set_active b && fastboot reboot"
