# Kubuntu in slot B (BOE panel)

**English** | [简体中文](README.zh-CN.md)

Run GUF296's [Kubuntu 26.04 for the TB321FU](https://github.com/GUF296/ubuntu-y700-build-ci/releases) in slot B instead of Armada, on the same dual-boot layout as the main guide (`boot_b`, `armada_esp`, `armada_root`).

> [!WARNING]
> Same risks as the main guide. Tested on one BOE-panel unit with Armada `v20261015.0544305` and Kubuntu `tb321fu-kubuntu2604-fcitx5-plasma-keyboard-clean-20260629`.

## Why not just flash the Kubuntu images

On a **BOE** panel the Kubuntu images boot to a black screen with the backlight on ([GUF296/ubuntu-y700-build-ci#1](https://github.com/GUF296/ubuntu-y700-build-ci/issues/1)). Its 7.1.1 kernel and device tree only know the **CSOT** panel (`lenovo,tb321fu-kirby-nt36523-csot-dsc-vid`), and there is no BOE panel driver in the kernel.

Armada's 7.2.6 kernel and DTB do drive the BOE panel. So this setup uses:

| Partition | Contents |
|---|---|
| `boot_b` | Kubuntu `boot.img` (UEFI loader) |
| `armada_esp` | Armada `super.img` with a new `grub.cfg`: Armada kernel + BOE DTB + initramfs, `root=PARTLABEL=armada_root` |
| `armada_root` | Kubuntu rootfs (ext4), grown to the whole partition, plus the files below |

Things the Kubuntu rootfs needs on top, found the hard way:

- **Armada's kernel modules** (`/usr/lib/modules/7.2.6`). Without them `qcom_q6v5_pas` is missing, the ADSP never starts, pmic_glink altmode and the DisplayPort controller stay deferred, and the MSM DRM driver never binds. The screen stays black even with the right kernel.
- **`novatek_ts_boe_fw.bin`**. The BOE DTB asks the touch driver for it; Kubuntu only ships the CSOT one. Also `battmgr.jsn` and `vpu33_p4.mbn`, which Kubuntu lacks.
- **A boot-successful flag for slot B**, or the ABL gives up after 7 boots and falls back to Android.

## What you need

- The dual-boot partition table from the main guide (steps 1–4), Android rooted in slot A.
- Armada release images (only used as a parts source): `super.img`, `userdata.simg` (joined parts). Use **the same release** for both; `make_bundle.py` checks the kernel matches the modules.
- Kubuntu release: `boot.img.7z`, `rootfs.img.7z.*`. Extract them; join the rootfs parts first (`cat rootfs.img.7z.* > rootfs.img.7z`).
- Python 3 on the PC, plus `pip install zstandard` (Armada's btrfs is zstd-compressed).

## Steps

### 1. Prepare on the PC

```sh
python3 kubuntu/tools/raw2simg.py TB321FU-kubuntu2604-arm64-rootfs.img rootfs.simg
python3 kubuntu/tools/make_esp.py super.img kubuntu_esp.img
python3 kubuntu/tools/make_bundle.py userdata.simg super.img kubuntu-bundle.tar
```

- `raw2simg.py`: `fastboot` cannot send the 20 GiB raw image (`std::bad_alloc`), so convert it. Zero blocks are written as `FILL` chunks, **not** `DONT_CARE`: `armada_root` still holds the old Armada data, and skipped blocks would keep it. (Skipping them corrupted every file with an all-zero 4K block, e.g. `python3.14` and `libc.so.6`, and Python segfaulted in a loop.)
- `make_esp.py`: copies `super.img` and rewrites only `/boot/grub/grub.cfg`.
- `make_bundle.py`: reads `userdata.simg` in place (no 300 GiB expansion) and packs the modules, firmware and `kubuntu/rootfs/`.

### 2. Flash slot B

```sh
adb reboot bootloader
fastboot flash boot_b boot.img                    # Kubuntu's
fastboot flash armada_esp kubuntu_esp.img
fastboot -S 700M flash armada_root rootfs.simg    # 3–4 minutes, writing zeros is slow
fastboot reboot                                   # back to Android, slot A
```

### 3. Finish the rootfs from Android

```sh
adb push kubuntu-bundle.tar kubuntu/install-to-rootfs.sh /data/local/tmp/
adb shell su -c "sh /data/local/tmp/install-to-rootfs.sh /data/local/tmp/kubuntu-bundle.tar"
```

It runs `e2fsck` + `resize2fs`, installs the bundle, enables the boot-successful service and puts a **Reboot to Android** icon on each user's desktop.

### 4. Boot Kubuntu

```sh
adb reboot bootloader
fastboot set_active b
fastboot reboot
```

GRUB shows **Kubuntu (Armada kernel, BOE)**, then SDDM logs into Plasma automatically as `GUF296`. Its password is not published; see below to add your own user.

## Switching

- **Kubuntu → Android:** the **Reboot to Android** icon. It runs `y700-slotctl to-android`, which only clears slot B's retry count and successful bit; on the next boot the ABL falls back to slot A and does the switch itself, including the type GUID swap. Nothing else in the GPT is touched.
- **Android → Kubuntu:** the `reboot_to_armada` module from the main guide works unchanged (it just selects slot B), or `fastboot set_active b`.
- `y700-mark-boot-successful.service` runs `y700-slotctl mark-success` 20 s after boot.

> [!CAUTION]
> Do not switch slots by editing only the attribute bits. Qualcomm slot switching also swaps the partition **type GUIDs** of every `_a`/`_b` pair; flipping just the bits leaves slot A with the "inactive" GUID (`77036cd4-…`) and the ABL drops to fastboot right after the logo. Use `fastboot set_active`, `bootctl`, `qbootctl`, or let the ABL fall back as above.

## Adding your own user

The image's `GUF296` password is not public. From Android, with the rootfs mounted at `$R` (as in `install-to-rootfs.sh`) and `/proc`, `/sys`, `/dev` bind-mounted:

```sh
chroot $R useradd -m -s /bin/bash -G sudo NAME
echo 'NAME:PASSWORD' | chroot $R chpasswd
sed -i 's/^User=.*/User=NAME/' $R/etc/sddm.conf.d/*.conf   # autologin
```

Copy `/home/GUF296/.config` and `.local` to keep the input method and keyboard setup.

## Known issues

- Suspend: the tablet does not wake up reliably.
- The on-screen keyboard does not pop up by itself; use the keyboard button in the panel.
- Haptics work but feel different from Android.
- Kernel updates from `apt` are not used; slot B always boots the 7.2.6 kernel from `armada_esp`. Do not remove `/usr/lib/modules/7.2.6`.
- Flashing an Android ROM in recovery overwrites `boot_b`; flash Kubuntu's `boot.img` again afterwards.

## Files

| Path | Purpose |
|---|---|
| `tools/raw2simg.py` | raw image → Android sparse, zeros as `FILL` |
| `tools/make_esp.py` | Armada `super.img` → `armada_esp` image for Kubuntu |
| `tools/make_bundle.py` | modules + firmware + `rootfs/` → `kubuntu-bundle.tar` |
| `tools/btrfs_sparse.py` | read-only btrfs reader working on an Android sparse image (also a CLI: `ls`, `cat`, `get`) |
| `install-to-rootfs.sh` | run on Android: grow the fs and install the bundle |
| `rootfs/` | files installed into Kubuntu: `y700-slotctl`, the service, the desktop entry, a sudoers rule for `to-android` only |

No firmware or kernel modules are stored in this repository; `make_bundle.py` takes them from your own Armada download.
