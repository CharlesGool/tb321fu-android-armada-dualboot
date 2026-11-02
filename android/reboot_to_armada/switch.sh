#!/system/bin/sh
# Switch to slot 1 (_b, Armada) and reboot, through the Qualcomm boot control HAL.
# 通过高通启动控制 HAL 切到 slot 1（_b，Armada）并重启。
# A GSI may ship a bootctl that only talks to the HIDL HAL while the vendor only has the AIDL
# one: then the AIDL HAL is called directly (1 = getActiveBootSlot, 9 = setActiveBootSlot).
# GSI 自带的 bootctl 可能只认 HIDL HAL，而 vendor 只有 AIDL 版：这时直接调用 AIDL HAL。
HAL=android.hardware.boot.IBootControl/default

aidl() { # transaction [args...]: prints the reply's first word, nothing on an exception
  service call "$HAL" "$@" 2>/dev/null | awk '$3 == "00000000" { print $4; exit }'
}

if bootctl set-active-boot-slot 1 2>/dev/null; then
  next=$(bootctl get-active-boot-slot 2>/dev/null)
else
  [ -n "$(aidl 9 i32 1)" ] || { echo "Failed: boot HAL error / 切换失败：启动控制 HAL 返回错误"; exit 1; }
  v=$(aidl 1)
  [ -n "$v" ] && next=$((0x$v))
fi
[ "$next" = 1 ] || { echo "Failed: next slot is not 1 / 切换失败：下次启动槽不是 1"; exit 1; }
echo "Switched to Armada, rebooting... / 已切换到 Armada，正在重启…"
sync
sleep 1
svc power reboot || reboot
