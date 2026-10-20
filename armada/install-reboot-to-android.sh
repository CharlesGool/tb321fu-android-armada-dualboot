#!/bin/bash
# Install qbootctl and a "Reboot to Android" desktop shortcut on Armada (run with sudo).
# 在 Armada 上安装 qbootctl 和"重启到 Android"桌面快捷方式（用 sudo 运行）。
#
# /usr/local is read-only on the TB321FU Armada image, so files go to /var/lib/dualboot.
# 此镜像的 /usr/local 只读，所以装到 /var/lib/dualboot。
set -e
[ "$(id -u)" = 0 ] || { echo "Run with sudo / 请用 sudo 运行"; exit 1; }
D=$(dirname "$(readlink -f "$0")")
[ -x "$D/qbootctl" ] || { echo "Run ./build-qbootctl.sh first / 请先运行 ./build-qbootctl.sh"; exit 1; }
U="${SUDO_USER:-armada}"; H=$(getent passwd "$U" | cut -d: -f6)
mkdir -p /var/lib/dualboot
install -m 755 -o root -g root "$D/qbootctl" /var/lib/dualboot/qbootctl
cat > /var/lib/dualboot/reboot-to-android <<'S'
#!/bin/sh
# Switch to slot A (Android) and reboot. Run as root (via pkexec).
# 切到 A 槽（Android）并重启。由 pkexec 以 root 运行。
set -e
/var/lib/dualboot/qbootctl -s a
sync
systemctl reboot
S
chmod 755 /var/lib/dualboot/reboot-to-android
mkdir -p "$H/Desktop"
cat > "$H/Desktop/reboot-to-android.desktop" <<'S'
[Desktop Entry]
Type=Application
Name=Reboot to Android
Name[zh_CN]=重启到 Android
Comment=Switch to slot A and reboot into Android
Comment[zh_CN]=切换到 A 槽并重启进入 Android
Icon=system-reboot
Exec=sh -c 'kdialog --yesno "Reboot to Android? / 确定要重启到 Android 吗？" && { pkexec /var/lib/dualboot/reboot-to-android || kdialog --error "Switch failed, not rebooting. / 切换失败，系统未重启。"; }'
Terminal=false
S
chown "$U:$U" "$H/Desktop/reboot-to-android.desktop"
chmod 755 "$H/Desktop/reboot-to-android.desktop"
echo "== Installed / 已安装. Slot info / 槽位信息:"
/var/lib/dualboot/qbootctl
