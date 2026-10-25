# B 槽改装 Kubuntu（BOE 屏）

[English](README.md) | **简体中文**

在主教程的双系统布局（`boot_b`、`armada_esp`、`armada_root`）上，把 B 槽的 Armada 换成 GUF296 的 [TB321FU Kubuntu 26.04](https://github.com/GUF296/ubuntu-y700-build-ci/releases)。

> [!WARNING]
> 风险与主教程相同。已验证环境：BOE 屏的一台机器，Armada `v20261015.0544305`，Kubuntu `tb321fu-kubuntu2604-fcitx5-plasma-keyboard-clean-20260629`。

## 为什么不能直接刷 Kubuntu 的镜像

在 **BOE** 屏上，Kubuntu 的镜像启动后黑屏、背光亮（[GUF296/ubuntu-y700-build-ci#1](https://github.com/GUF296/ubuntu-y700-build-ci/issues/1)）。它的 7.1.1 内核和设备树只支持 **CSOT** 屏（`lenovo,tb321fu-kirby-nt36523-csot-dsc-vid`），内核里没有 BOE 屏驱动。

Armada 的 7.2.6 内核和设备树能驱动 BOE 屏，所以这里的组合是：

| 分区 | 内容 |
|---|---|
| `boot_b` | Kubuntu 的 `boot.img`（UEFI 加载器） |
| `armada_esp` | Armada 的 `super.img`，只换了 `grub.cfg`：Armada 内核 + BOE 设备树 + initramfs，`root=PARTLABEL=armada_root` |
| `armada_root` | Kubuntu rootfs（ext4），扩到整个分区，再加上下面这些 |

Kubuntu rootfs 还需要补的东西（逐个排查出来的）：

- **Armada 的内核模块**（`/usr/lib/modules/7.2.6`）。缺了它就没有 `qcom_q6v5_pas`，ADSP 不启动，pmic_glink altmode 和 DisplayPort 控制器一直 deferred，MSM DRM 驱动无法绑定。即使换了内核，屏幕也还是黑的。
- **`novatek_ts_boe_fw.bin`**。BOE 设备树让触控驱动加载这个文件，Kubuntu 只带了 CSOT 的。另外补 Kubuntu 缺少的 `battmgr.jsn`、`vpu33_p4.mbn`。
- **B 槽的启动成功标记**。没有它，ABL 启动 7 次后会放弃 B 槽，回到 Android。

## 准备

- 主教程第 1–4 步的双系统分区表，A 槽 Android 已 root。
- Armada 发布镜像（只当零件来源）：`super.img`、`userdata.simg`（合并后的）。两者必须来自**同一个版本**，`make_bundle.py` 会校验内核和模块是否匹配。
- Kubuntu 发布包：`boot.img.7z`、`rootfs.img.7z.*`。先合并 rootfs 分卷（`cat rootfs.img.7z.* > rootfs.img.7z`）再解压。
- 电脑上有 Python 3，并 `pip install zstandard`（Armada 的 btrfs 用 zstd 压缩）。

## 步骤

### 1. 在电脑上准备

```sh
python3 kubuntu/tools/raw2simg.py TB321FU-kubuntu2604-arm64-rootfs.img rootfs.simg
python3 kubuntu/tools/make_esp.py super.img kubuntu_esp.img
python3 kubuntu/tools/make_bundle.py userdata.simg super.img kubuntu-bundle.tar
```

- `raw2simg.py`：`fastboot` 发不了 20 GiB 的原始镜像（`std::bad_alloc`），需要转换。全 0 块写成 `FILL` 块，**不能**用 `DONT_CARE`：`armada_root` 上还有 Armada 的旧数据，跳过的块会把旧数据留下。（跳过全 0 块会把所有含全 0 4K 块的文件写坏，比如 `python3.14` 和 `libc.so.6`，结果 Python 一运行就段错误，apport 无限循环报错。）
- `make_esp.py`：复制 `super.img`，只改写 `/boot/grub/grub.cfg`。
- `make_bundle.py`：直接读取 `userdata.simg`（不用展开成 300 GiB），把模块、固件和 `kubuntu/rootfs/` 打成一个包。

### 2. 刷 B 槽

```sh
adb reboot bootloader
fastboot flash boot_b boot.img                    # Kubuntu 的
fastboot flash armada_esp kubuntu_esp.img
fastboot -S 700M flash armada_root rootfs.simg    # 3–4 分钟，写 0 比较慢
fastboot reboot                                   # 回到 A 槽的 Android
```

### 3. 在 Android 上补全 rootfs

```sh
adb push kubuntu-bundle.tar kubuntu/install-to-rootfs.sh /data/local/tmp/
adb shell su -c "sh /data/local/tmp/install-to-rootfs.sh /data/local/tmp/kubuntu-bundle.tar"
```

它会执行 `e2fsck` + `resize2fs`，装入整个包，启用启动成功标记服务，并在每个用户的桌面上放一个 **重启到 Android** 图标。

### 4. 启动 Kubuntu

```sh
adb reboot bootloader
fastboot set_active b
fastboot reboot
```

GRUB 显示 **Kubuntu (Armada kernel, BOE)**，随后 SDDM 以 `GUF296` 自动登录 Plasma。这个用户的密码没有公开，可以按下文自己加一个用户。

## 切换系统

- **Kubuntu → Android：** 点 **重启到 Android**。它执行 `y700-slotctl to-android`，只清除 B 槽的重试次数和启动成功位；下次启动时 ABL 自动回退到 A 槽，切换工作（包括交换类型 GUID）由 ABL 自己完成。GPT 的其他内容都不动。
- **Android → Kubuntu：** 主教程的 `reboot_to_armada` 模块可以直接用（它只是选择 B 槽），或者 `fastboot set_active b`。
- `y700-mark-boot-successful.service` 在开机 20 秒后执行 `y700-slotctl mark-success`。

> [!CAUTION]
> 不要只改属性位来切槽。高通切槽时还会交换每一对 `_a`/`_b` 分区的**类型 GUID**；只改属性位的话，A 槽会带着“非活动”GUID（`77036cd4-…`），ABL 在 logo 之后直接掉进 fastboot。请用 `fastboot set_active`、`bootctl`、`qbootctl`，或者像上面那样让 ABL 自己回退。

## 添加自己的用户

镜像里 `GUF296` 的密码没有公开。在 Android 上挂载 rootfs 到 `$R`（同 `install-to-rootfs.sh`），并 bind 挂载 `/proc`、`/sys`、`/dev` 后：

```sh
chroot $R useradd -m -s /bin/bash -G sudo 用户名
echo '用户名:密码' | chroot $R chpasswd
sed -i 's/^User=.*/User=用户名/' $R/etc/sddm.conf.d/*.conf   # 自动登录
```

把 `/home/GUF296/.config` 和 `.local` 复制过去，可以保留输入法和屏幕键盘的设置。

## 已知问题

- 睡眠后无法正常唤醒。
- 屏幕键盘不会自动弹出，需要点面板上的键盘按钮。
- 震动能用，但手感和 Android 不同。
- `apt` 升级的内核不会被使用，B 槽始终从 `armada_esp` 启动 7.2.6 内核。不要删除 `/usr/lib/modules/7.2.6`。
- 在 recovery 卡刷 Android ROM 会覆盖 `boot_b`，之后要重新刷入 Kubuntu 的 `boot.img`。

## 文件

| 路径 | 用途 |
|---|---|
| `tools/raw2simg.py` | 原始镜像 → Android sparse，全 0 块写成 `FILL` |
| `tools/make_esp.py` | Armada `super.img` → Kubuntu 用的 `armada_esp` 镜像 |
| `tools/make_bundle.py` | 模块 + 固件 + `rootfs/` → `kubuntu-bundle.tar` |
| `tools/btrfs_sparse.py` | 直接在 Android sparse 镜像上读取 btrfs 的只读工具（也可以当命令行用：`ls`、`cat`、`get`） |
| `install-to-rootfs.sh` | 在 Android 上运行：扩容并安装上面的包 |
| `rootfs/` | 装进 Kubuntu 的文件：`y700-slotctl`、开机服务、桌面图标、只允许 `to-android` 的 sudoers 规则 |

本仓库不包含任何固件或内核模块，`make_bundle.py` 从你自己下载的 Armada 镜像里提取。
