# 联想拯救者平板 Y700（2025）/ Legion Tab Gen 3（TB321FU）Android + Armada 双系统

[English](README.md) | **简体中文**

在同一台平板上保留 Android，同时运行 [Armada TB321FU 移植版](https://github.com/enij90/armada-tb321fu)（类 SteamOS 的 Linux）。Android 在 A/B 的 **A 槽**，Armada 在 **B 槽**，两边各用各的分区，在任意一边都能一键切换到另一边。

官方安装方式会替换掉 Android：把 Armada 的 GRUB FAT 写进 `super`，把系统写进 `userdata`。本教程改为拆分 `userdata`，Android 的 `super` 完全不动。

> [!WARNING]
> 非官方方案，Armada 和 armada-tb321fu 项目都不提供支持。操作会改写分区表，并**清除 Android 数据**。请确认你能通过高通 9008（EDL）和完整原厂线刷包救砖后再动手。已验证环境：BOE 屏、512GB 的一台机器，Armada `v20261015.0544305`，Android 15。

## 原理

```
ABL（联想原厂，已解锁）
 ├─ A 槽 → boot_a ......... Android（super + userdata；userdata 缩小，其余不变）
 └─ B 槽 → boot_b ......... Armada 的 UEFI 加载器
                └─ armada_esp（FAT）  GRUB + 内核 + initramfs + DTB
                      └─ armada_root（btrfs）  root=UUID=…
```

- UEFI 加载器会在任意 FAT 分区上寻找 GRUB，不限于 `super`，这是本方案能成立的关键。
- GRUB 从自己所在的 FAT 加载内核，内核按 UUID 查找根分区，所以两者都能放到新分区上。
- Armada 有两个服务写死了 Android 的分区：GRUB 同步（`super`）和"启动成功"标记（`boot_a`）。[`armada/dualboot-fix.sh`](armada/dualboot-fix.sh) 在 `/etc` 中写入 systemd 覆盖配置，把它们改到正确的分区，Armada 系统更新后也会保留。

| 分区（LUN 0） | 内容 | 示例大小（512GB 机型） |
|---|---|---|
| `userdata` | Android 数据（缩小后） | 128 GiB，可自定 |
| `armada_esp`（新建） | Armada 的 `super.img`（GRUB FAT） | 256 MiB |
| `armada_root`（新建） | Armada 的 `userdata.simg` | 剩余空间，约 328 GiB |
| `boot_b` | Armada 的 `boot.img`（UEFI 加载器） | – |

## 准备

- TB321FU，**已解锁 BL**，**BOE 屏**（`adb shell getprop ro.vendor.display.paneltype` 返回 `1`），**Android 已 root**（KernelSU / SukiSU / Magisk）。
- 电脑上有 `adb`、`fastboot`、Python 3。
- **能通过 9008 刷入的完整原厂包**（QFIL / `fh_loader`），以及本机独有分区（`persist`、`modemst1/2`、`fsg`）的备份。A 槽用第三方 ROM 也可以。
- [armada-tb321fu 发布页](https://github.com/enij90/armada-tb321fu/releases)的镜像：`boot.img`、`super.img`，以及合并成 `userdata.simg` 的 `userdata.simg.part*`，全部用 `SHA256SUMS` 校验过。
- 平板最好有 300GB 以上的可分配空间，Armada 至少需要约 16 GiB。

## 步骤

以下 `adb shell su -c` 命令都在 Android 上以 root 执行。

### 1. 备份

备份所有重要数据，以及本教程会改动的分区：

```sh
for p in boot_a boot_b init_boot_a init_boot_b persist misc metadata modemst1 modemst2 fsg; do
  adb shell su -c "dd if=/dev/block/by-name/$p of=/sdcard/$p.img bs=4M" && adb pull /sdcard/$p.img && adb shell rm /sdcard/$p.img
done
```

`super` 约 13 GiB。如果手上的原厂包和当前系统版本不一致，建议把它也备份下来。

### 2. 导出 LUN 0 的分区表

```sh
adb shell su -c "dd if=/dev/block/sda of=/sdcard/gpt_primary.bin bs=4096 count=6"
N=$(adb shell su -c "blockdev --getsize64 /dev/block/sda" | tr -d '\r')
adb shell su -c "dd if=/dev/block/sda of=/sdcard/gpt_backup.bin bs=4096 skip=$((N/4096-5)) count=5"
adb pull /sdcard/gpt_primary.bin && adb pull /sdcard/gpt_backup.bin
```

这两个文件要保存好，以后恢复原始布局全靠它们。

### 3. 在电脑上生成新分区表

```sh
python3 tools/gpt_split.py gpt_primary.bin gpt_backup.bin new_primary.bin new_backup.bin --android-gib 128
```

脚本会先检查 GPT 是否有效、`userdata` 是不是最后一个分区、备份表和主表是否一致。然后在原位缩小 `userdata`（起始位置和 GUID 不变），在它后面新建 `armada_esp` 和 `armada_root`，并打印新布局和备份表的写入位置。

### 4. 写入分区表并清除 Android 数据

```sh
adb push new_primary.bin new_backup.bin /data/local/tmp/
adb shell su -c "dd if=/data/local/tmp/new_primary.bin of=/dev/block/sda bs=4096 seek=0 count=6 conv=notrunc,fsync"
adb shell su -c "dd if=/data/local/tmp/new_backup.bin of=/dev/block/sda bs=4096 seek=$((N/4096-5)) count=5 conv=notrunc,fsync"
# 校验：两组哈希都必须一致
adb shell su -c "dd if=/dev/block/sda bs=4096 count=6 | sha256sum; sha256sum /data/local/tmp/new_primary.bin"
adb shell su -c "dd if=/dev/block/sda bs=4096 skip=$((N/4096-5)) count=5 | sha256sum; sha256sum /data/local/tmp/new_backup.bin"
adb reboot recovery
```

在 recovery 里选 **Wipe data / factory reset**（清除数据），然后重启。Android 会在新的、更小的 `userdata` 上重新格式化：它的 fstab 带 `formattable`，而且没有固定长度。如果之前没退出 Google 账号，执行 `fastboot erase frp`。完成 Android 设置后，打开 USB 调试，重新安装 root 管理器。

### 5. 刷入 Armada（B 槽和新分区）

```sh
adb reboot bootloader
fastboot getvar partition-size:armada_root      # 确认分区存在
fastboot flash boot_b boot.img
fastboot flash armada_esp super.img
fastboot -S 700M flash armada_root userdata.simg   # 需要几分钟
```

这几条命令都不会碰 A 槽、`super` 和 `userdata`。

### 6. 第一次启动

```sh
fastboot set_active b
fastboot reboot
```

正常流程是：GRUB 菜单 → "Preparing Armada" → Steam 设置。中间可能自动重启一两次，这是上游的已知问题。

> 如果刚刷完大镜像后执行 `fastboot set_active` 卡住（一直没有 `OKAY`，设备序列号显示 `????????`，报 "no link"），就按住**电源键 + 音量减**约 15 秒，重新进入 fastboot，重插数据线后再执行一次。这时它会在几毫秒内完成。

### 7. 修复 Armada 的双系统配置（必须做）

在 Armada 上执行（用 Konsole；或者先在 Armada Tools 里打开 SSH，再远程执行）：

```sh
sudo ./armada/dualboot-fix.sh
```

输出最后应该出现 `in sync`。不做这一步会有两个问题：
- Armada 每次更新都会因为 GRUB 同步失败而回滚；
- B 槽永远不会被标记为启动成功，连续启动 7 次后 ABL 会放弃 B 槽，自动退回 Android。

第一次开机时，Armada 已经尝试过把 `super` 当作 FAT 挂载。因为 Android 的 `super` 不是 FAT 格式，挂载失败了，没有写入任何东西。

### 8. 一键切换（可选）

**Armada → Android**：在 rootless 容器里编译静态版 `qbootctl`（[linux-msm/qbootctl](https://github.com/linux-msm/qbootctl)），然后安装它和桌面图标：

```sh
./armada/build-qbootctl.sh
sudo ./armada/install-reboot-to-android.sh
```

`qbootctl` 会像 Android 的启动控制 HAL 一样，同时切换 UFS 启动 LUN（xbl_a / xbl_b）。不要只用 `sgdisk` 改 GPT 的属性位。

**Android → Armada**：一个 KernelSU / SukiSU 模块，调用 Android 自带的 `bootctl`（高通启动控制 HAL）。把文件夹内容打包成 zip 后安装：

```sh
cd android/reboot_to_armada && zip -r ../reboot_to_armada.zip . && cd ..
adb push reboot_to_armada.zip /data/local/tmp/
adb shell su -c "/data/adb/ksud module install /data/local/tmp/reboot_to_armada.zip"
```

重启后，在模块列表里点它的**执行**按钮；也可以打开它的 WebUI，添加到桌面。

任何情况下都能用 fastboot 兜底：`fastboot set_active a`（Android）或 `fastboot set_active b`（Armada）。

## 用 Kubuntu 代替 Armada

B 槽也可以改装 GUF296 的 Kubuntu 26.04。在 BOE 屏上它自带的内核会黑屏，所以要用 Armada 的内核启动，并补几个文件。详见 [kubuntu/README.zh-CN.md](kubuntu/README.zh-CN.md)。

## 注意事项

- **用 recovery 卡刷 Android ROM** 时，A/B 机型会写入"另一个槽"，`boot_b` 会被覆盖。刷完后重新执行 `fastboot flash boot_b boot.img`。ROM 不会动 `armada_esp` 和 `armada_root`。
- 原厂 OTA 也一样会写入另一个槽，所以要关闭 Android 系统更新。
- Armada 的 `tb321fu-panel` 默认也用 `super`，需要时这样运行：`sudo SUPER=/dev/disk/by-partlabel/armada_esp tb321fu-panel boe|csot`。
- 这个镜像的 `/usr/local` 是只读的，所以辅助文件放在 `/var/lib/dualboot`。
- 打开 SSH 后，记得用 `passwd` 修改默认的 `armada` 密码。
- **不要**刷 armada-tb321fu 仓库 `abl/` 目录里的 ROCKNIX ABL，那些是给其他机型用的。

## 还原

- **恢复成只有 Android 的单系统**：按第 4 步的方法，把原来的 `gpt_primary.bin` / `gpt_backup.bin` 写回 `/dev/block/sda`，执行 `fastboot set_active a`，然后在 recovery 里清除数据。如有需要，用备份恢复 `boot_b`。
- **出现任何问题**：用 9008 刷原厂包。`persist`、`modemst1/2`、`fsg` 要用自己机器的备份，不要用别人包里的通用版本。

## 致谢

- [enij90/armada-tb321fu](https://github.com/enij90/armada-tb321fu)：本教程基于的 Armada 移植。
- GUF296：这台平板最早的 Linux 移植，以及 UEFI 加载器、GRUB 模板和 [Kubuntu 构建](https://github.com/GUF296/ubuntu-y700-build-ci)。
- [Armada](https://github.com/armada-os/armada)、[ROCKNIX](https://github.com/ROCKNIX)、[linux-msm/qbootctl](https://github.com/linux-msm/qbootctl)。

## 许可证

本仓库的脚本采用 MIT 许可证，见 [LICENSE](LICENSE)。仓库不包含 qbootctl，`build-qbootctl.sh` 会从源码下载并编译它，qbootctl 遵循它自己的许可证。
