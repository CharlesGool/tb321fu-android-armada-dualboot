#!/system/bin/sh
# Switch to slot 1 (_b, Armada) and reboot, using Android's own bootctl (Qualcomm boot HAL).
# 用 Android 自带的 bootctl（高通启动控制 HAL）切到 slot 1（_b，Armada）并重启。
bootctl set-active-boot-slot 1 || { echo "Failed: bootctl error / 切换失败：bootctl 返回错误"; exit 1; }
[ "$(bootctl get-active-boot-slot)" = 1 ] || { echo "Failed: next slot is not 1 / 切换失败：下次启动槽不是 1"; exit 1; }
echo "Switched to Armada, rebooting... / 已切换到 Armada，正在重启…"
sync
sleep 1
svc power reboot || reboot
