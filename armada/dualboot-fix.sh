#!/bin/bash
# TB321FU dual boot fix for Armada (run once on Armada, as root).
# TB321FU 双系统修复（在 Armada 上以 root 运行一次）。
#
# 1. GRUB sync: use the armada_esp partition instead of Android's "super".
#    GRUB 同步：改用 armada_esp，而不是 Android 的 super。
# 2. Boot-successful flag: mark boot_b (Armada's slot) instead of boot_a.
#    启动成功标记：标记 boot_b（Armada 所在槽），而不是 boot_a。
#
# Drop-ins live in /etc, so they survive Armada (bootc) updates.
# 覆盖配置写在 /etc，Armada（bootc）系统更新后保留。
set -e
[ "$(id -u)" = 0 ] || { echo "Run with sudo / 请用 sudo 运行"; exit 1; }
[ -b /dev/disk/by-partlabel/armada_esp ] || { echo "armada_esp not found / 找不到 armada_esp"; exit 1; }
ENV='[Service]
Environment=SUPER=/dev/disk/by-partlabel/armada_esp'
for u in tb321fu-grub-sync.service ostree-finalize-staged.service; do
  mkdir -p /etc/systemd/system/$u.d
  printf '%s\n' "$ENV" > /etc/systemd/system/$u.d/50-dualboot.conf
done
mkdir -p /etc/systemd/system/tb321fu-mark-boot-successful.service.d
cat > /etc/systemd/system/tb321fu-mark-boot-successful.service.d/50-dualboot.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/bin/sh -c 'd=$(lsblk -no PKNAME /dev/disk/by-partlabel/boot_b); n=$(cat /sys/class/block/$(basename $(readlink -f /dev/disk/by-partlabel/boot_b))/partition); /usr/sbin/sgdisk -A $n:set:54 /dev/$d'
UNIT
systemctl daemon-reload
systemctl restart tb321fu-grub-sync.service
systemctl restart tb321fu-mark-boot-successful.service
echo
journalctl -b -u tb321fu-grub-sync --no-pager -o cat | tail -3
echo "== Done / 完成 (expect 'in sync' above / 上面应出现 'in sync')"
