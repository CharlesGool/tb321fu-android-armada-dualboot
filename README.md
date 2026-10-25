# Android + Armada dual boot on the Lenovo Legion Tab Gen 3 (TB321FU)

**English** | [简体中文](README.zh-CN.md)

Keep Android and run [Armada for the TB321FU](https://github.com/enij90/armada-tb321fu) (a SteamOS-like Linux) on the same tablet. Android lives in A/B slot **A**, Armada in slot **B**, each with its own partitions. You switch with one tap on either side.

The upstream install replaces Android: it writes Armada's GRUB FAT over `super` and its system over `userdata`. This guide splits `userdata` instead, so Android's `super` is never touched.

> [!WARNING]
> Unofficial, not supported by the Armada or armada-tb321fu projects. It rewrites the partition table and **erases Android's data**. Do it only if you can recover the tablet over Qualcomm EDL (9008) with a full stock firmware package. Tested on one BOE-panel unit with a 512 GB disk, Armada `v20261015.0544305`, Android 15.

## How it works

```
ABL (Lenovo, unlocked)
 ├─ slot A → boot_a ......... Android  (super + userdata, unchanged except userdata is smaller)
 └─ slot B → boot_b ......... Armada UEFI loader
                └─ armada_esp (FAT)  GRUB + kernel + initramfs + DTB
                      └─ armada_root (btrfs)  root=UUID=…
```

- The UEFI loader finds GRUB on any FAT partition, not only on `super`. That is what makes this possible.
- GRUB loads the kernel from its own FAT, and the kernel finds root by UUID. So both pieces can live on new partitions.
- Two Armada services have Android's partitions hard-coded: GRUB sync (`super`) and the boot-successful flag (`boot_a`). [`armada/dualboot-fix.sh`](armada/dualboot-fix.sh) redirects them with systemd drop-ins in `/etc`, which survive Armada updates.

| Partition (LUN 0) | Contents | Example size (512 GB unit) |
|---|---|---|
| `userdata` | Android data (shrunk) | 128 GiB, your choice |
| `armada_esp` (new) | Armada `super.img` (GRUB FAT) | 256 MiB |
| `armada_root` (new) | Armada `userdata.simg` | rest, ≈ 328 GiB |
| `boot_b` | Armada `boot.img` (UEFI loader) | – |

## Requirements

- TB321FU with an **unlocked bootloader**, **BOE panel** (`adb shell getprop ro.vendor.display.paneltype` prints `1`), and **root on Android** (KernelSU/SukiSU/Magisk).
- PC with `adb`, `fastboot`, Python 3.
- A **full stock firmware package** that flashes over 9008 (QFIL / `fh_loader`), plus your own backup of the device-unique partitions (`persist`, `modemst1/2`, `fsg`). A third-party ROM is fine on slot A.
- The [armada-tb321fu release](https://github.com/enij90/armada-tb321fu/releases) images: `boot.img`, `super.img`, `userdata.simg.part*` joined into `userdata.simg`, checked against `SHA256SUMS`.
- About 300 GB or more of free space on the tablet is ideal; Armada needs at least ~16 GiB.

## Steps

All `adb shell su -c` commands run on Android as root.

### 1. Back up

Back up everything you care about, including the partitions this guide changes:

```sh
for p in boot_a boot_b init_boot_a init_boot_b persist misc metadata modemst1 modemst2 fsg; do
  adb shell su -c "dd if=/dev/block/by-name/$p of=/sdcard/$p.img bs=4M" && adb pull /sdcard/$p.img && adb shell rm /sdcard/$p.img
done
```

(`super` is about 13 GiB; add it too if your stock package might not match what is installed.)

### 2. Dump the partition table of LUN 0

```sh
adb shell su -c "dd if=/dev/block/sda of=/sdcard/gpt_primary.bin bs=4096 count=6"
N=$(adb shell su -c "blockdev --getsize64 /dev/block/sda" | tr -d '\r')
adb shell su -c "dd if=/dev/block/sda of=/sdcard/gpt_backup.bin bs=4096 skip=$((N/4096-5)) count=5"
adb pull /sdcard/gpt_primary.bin && adb pull /sdcard/gpt_backup.bin
```

Keep these two files. They are your way back to the original layout.

### 3. Build the new partition table (offline)

```sh
python3 tools/gpt_split.py gpt_primary.bin gpt_backup.bin new_primary.bin new_backup.bin --android-gib 128
```

The script checks that the GPT is valid, that `userdata` is the last partition, and that the backup table matches. It then shrinks `userdata` in place, keeping its start and GUIDs, and adds `armada_esp` and `armada_root` after it. It prints the new layout and the block where the backup table goes.

### 4. Write it and wipe Android data

```sh
adb push new_primary.bin new_backup.bin /data/local/tmp/
adb shell su -c "dd if=/data/local/tmp/new_primary.bin of=/dev/block/sda bs=4096 seek=0 count=6 conv=notrunc,fsync"
adb shell su -c "dd if=/data/local/tmp/new_backup.bin of=/dev/block/sda bs=4096 seek=$((N/4096-5)) count=5 conv=notrunc,fsync"
# verify: both pairs of hashes must match
adb shell su -c "dd if=/dev/block/sda bs=4096 count=6 | sha256sum; sha256sum /data/local/tmp/new_primary.bin"
adb shell su -c "dd if=/dev/block/sda bs=4096 skip=$((N/4096-5)) count=5 | sha256sum; sha256sum /data/local/tmp/new_backup.bin"
adb reboot recovery
```

In recovery choose **Wipe data / factory reset**, then reboot. Android formats the new, smaller `userdata` (its fstab has `formattable` and no fixed length). If you did not remove your Google account first, run `fastboot erase frp`. Set up Android, enable USB debugging and reinstall your root manager.

### 5. Flash Armada into slot B and the new partitions

```sh
adb reboot bootloader
fastboot getvar partition-size:armada_root      # sanity check
fastboot flash boot_b boot.img
fastboot flash armada_esp super.img
fastboot -S 700M flash armada_root userdata.simg   # several minutes
```

None of these touch slot A, `super` or `userdata`.

### 6. First boot

```sh
fastboot set_active b
fastboot reboot
```

You should see GRUB, then "Preparing Armada" and the Steam setup. The tablet may reboot once or twice; this is a known upstream issue.

> If `fastboot set_active` hangs right after the big flash (no `OKAY`, device shows as `????????` with "no link"), hold **Power + Volume Down** for about 15 s to get back into fastboot. Replug the cable and run it again; it then returns in milliseconds.

### 7. Fix Armada for the dual-boot layout (required)

On Armada (Konsole, or SSH after enabling it in Armada Tools):

```sh
sudo ./armada/dualboot-fix.sh
```

The output should end with `in sync`. Without this fix:
- every Armada update fails to sync GRUB and rolls back;
- slot B is never marked successful, so after 7 boots the ABL gives up on it and boots Android.

The first boot already tried to mount `super` as FAT. That failed harmlessly, because Android's `super` is not FAT, and nothing was written.

### 8. One-tap switching (optional)

**Armada → Android:** builds a static `qbootctl` ([linux-msm/qbootctl](https://github.com/linux-msm/qbootctl)) in a rootless container, then installs it with a desktop icon:

```sh
./armada/build-qbootctl.sh
sudo ./armada/install-reboot-to-android.sh
```

`qbootctl` also switches the UFS boot LUN (xbl_a/xbl_b), as Android's boot HAL does. Do not flip only the GPT attribute bits with `sgdisk`.

**Android → Armada:** a KernelSU/SukiSU module that calls Android's own `bootctl` (Qualcomm boot HAL). Zip the folder contents and install it:

```sh
cd android/reboot_to_armada && zip -r ../reboot_to_armada.zip . && cd ..
adb push reboot_to_armada.zip /data/local/tmp/
adb shell su -c "/data/adb/ksud module install /data/local/tmp/reboot_to_armada.zip"
```

After a reboot, use the module's **Action** button, or open its WebUI and add it to the home screen.

Fallback from anywhere: `fastboot set_active a` (Android) / `fastboot set_active b` (Armada).

## Kubuntu instead of Armada

Slot B can run GUF296's Kubuntu 26.04 instead. On BOE panels its own kernel shows a black screen, so it boots with Armada's kernel and needs a few extra files. See [kubuntu/README.md](kubuntu/README.md).

## Keep in mind

- **Updating Android by flashing a ROM zip in recovery** writes to the *other* slot, so it overwrites `boot_b`. Afterwards run `fastboot flash boot_b boot.img` again. `armada_esp` and `armada_root` are never touched by ROMs.
- Stock OTA would do the same. Keep Android OTA off.
- Armada's `tb321fu-panel` also defaults to `super`. Run it as `sudo SUPER=/dev/disk/by-partlabel/armada_esp tb321fu-panel boe|csot`.
- On this image `/usr/local` is read-only, so the helper files live in `/var/lib/dualboot`.
- Change the default `armada` password (`passwd`) if you enable SSH.
- Do **not** flash the ROCKNIX ABLs from the armada-tb321fu `abl/` folder; they are for other devices.

## Undo

- **Back to single-boot Android:** write your original `gpt_primary.bin` / `gpt_backup.bin` back to `/dev/block/sda` the same way as step 4, run `fastboot set_active a`, then wipe data in recovery. Optionally restore `boot_b` from your backup.
- **Anything broken:** flash the stock package over 9008. Restore your own `persist`, `modemst1/2` and `fsg`; do not use generic ones from someone else's package.

## Credits

- [enij90/armada-tb321fu](https://github.com/enij90/armada-tb321fu): the Armada port this guide builds on.
- GUF296: the original Linux port, UEFI loader and GRUB template for this tablet, and the [Kubuntu build](https://github.com/GUF296/ubuntu-y700-build-ci).
- [Armada](https://github.com/armada-os/armada), [ROCKNIX](https://github.com/ROCKNIX), [linux-msm/qbootctl](https://github.com/linux-msm/qbootctl).

## License

The scripts in this repository are MIT licensed, see [LICENSE](LICENSE). qbootctl is not included; `build-qbootctl.sh` fetches and builds it from source under its own license.
