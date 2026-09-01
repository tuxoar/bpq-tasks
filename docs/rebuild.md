# Rebuilding the W2QS BPQ node from scratch

Disaster-recovery guide for the machine at `100.69.92.43` (Tailscale) /
`shaun-ThinkCentre-M900`: a Lenovo ThinkCentre M900 running Ubuntu 24.04
LTS that hosts the **W2QS-1 node / W2QS BBS / W2QS-10 telnet server** —
an RRI DTN Region 2 BPQ node in Vernon, NY.

This guide was reconstructed on 2026-09-01 from the live machine's shell
history, configs, scripts, and running processes. It documents only what
is actually in use today — the machine's history also contains VNC,
Chrome Remote Desktop, a `linbpq.service`/`rigctld.service` systemd pair,
pat, and gpsd experiments that were all abandoned and are deliberately
**not** part of this guide.

> **⚠ This guide is useless without the backup files.** Section 1 lists
> the files that must exist somewhere other than the machine itself.
> Verify that backup exists *today*, not during the disaster.

---

## 0. What this machine runs (architecture)

```
                      ┌────────────────────────────────────────────┐
                      │  tmux session "0" (everything runs here)   │
                      │                                            │
  IC-7100 (2m packet) │  window A: ./direwolf-bpq-start.sh         │
   USB ──────────────►│    rigctld -m 3070 (CAT/PTT) :4532         │
   (CAT + soundcard)  │    direwolf (1200bd KISS-over-TCP) :8001   │
                      │                                            │
  FT-991A + VARA HF   │  window B: ./start_bpq.sh                  │
   USB ──────────────►│    Xvfb :99                                │
  SCS PTC-II (Pactor) │    linbpq64 mail                           │
   USB ──────────────►│      ├─ launches VARA.exe under Wine :8300 │
                      │      ├─ Telnet server :8010, HTTP :8012    │
                      │      └─ AX/IP/UDP :10093 (KY2D, KW1U, ...) │
                      └────────────────────────────────────────────┘
```

BPQ ports (from `bpq32.cfg`):

| Port | What | How |
|---|---|---|
| 1 | AX/IP/UDP internet links | UDP 10093; MAPs to KY2D-0/1, KW1U-1, KC3BTV-1 |
| 2 | Telnet server (W2QS-10) | TCP 8010, HTTP console 8012 |
| 3 | 2 m packet 145.070 (IC-7100) | KISS over TCP → Dire Wolf at 127.0.0.1:8001 |
| 4 | HF Pactor (W2QS) | SCS PTC-IIusb on `/dev/ttyUSB_PTCIIUSB`, FT-991A rig control on `/dev/cp2105_enhanced` |
| 5 | HF VARA (W2QS) | VARA.exe under Wine, TCP 127.0.0.1:8300 |

The `bpq-tasks` cron jobs (this repo) run against the telnet port for
mail chores and stale-traffic notifications.

---

## 1. Prerequisites — the backup that must already exist

Copy these **off the machine** regularly (they cannot be recreated from
memory). Everything else in this guide is reproducible.

> **One-shot backup:** `./backup_node.sh` in this repo pulls every file
> below over SSH into a single tarball under `backups/` (gitignored —
> the archive holds real passwords and the VARA license; keep it
> chmod 600). Run it from a terminal so it can prompt for the node's
> sudo password to grab the root-only netplan file; then copy the
> tarball off this machine.

Configuration (small, changes occasionally):

- `~/linbpq/bpq32.cfg` — node config **(contains the sysop PASSWORD and
  the telnet `USER=` line with a real password — treat as secret)**
- `~/linbpq/linmail.cfg` — BBS/mail config (forwarding, users; large,
  maintained through the BBS web UI — do not try to recreate by hand)
- `~/linbpq/direwolf.conf` — Dire Wolf soundmodem config
- `~/linbpq/WP.cfg` — white pages
- `/etc/udev/rules.d/99-usb-serial.rules` — stable serial-device names
- `/etc/netplan/01-ax25.yaml` — network config (root-only; see §5)
- `/etc/ax25/axports`
- `~/ic7100-packet-start.sh`, `~/linbpq/direwolf-bpq-start.sh`,
  `~/linbpq/start_bpq.sh`, `~/scripts/bpq_logs.sh`
- `crontab -l` output
- `~/bpq-tasks/bpq.env` — gitignored; holds Telegram/QRZ credentials
- `~/.wine/drive_c/VARA/VARA.ini` and `~/.wine/drive_c/VARA FM/` —
  VARA settings **and license registration**

BBS data (changes daily — the hourly `bpq_logs.sh` cron copies it to
`~/bpq_backup_logs/` and `~/bpq_mail_archive/`, but those live on the
same disk; sync them off-machine too):

- `~/linbpq/Mail/` — all messages
- `~/linbpq/DIRMES.SYS`, `~/linbpq/BPQNODES.dat`

Installers you'll need again:

- VARA HF / VARA FM setup zips (kept in `~/vara-installers/`; also on
  winlink.org downloads)
- `linbpq64` binary: `http://www.cantab.net/users/john.wiseman/Downloads/Beta/linbpq64`

Also record the VARA license key somewhere safe if it isn't in VARA.ini.

---

## 2. Base OS

1. Install **Ubuntu 24.04 LTS** (server or desktop; the node runs
   headless — the GUI is not required).
2. Create user **`shaun`** (all paths below assume it).
3. SSH + Tailscale first, so the rest can be done remotely:

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install openssh-server
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --ssh
   ```

   Log in to the tailnet; the machine should come back as
   `shaun-thinkcentre-m900`. Restore `~/.ssh/authorized_keys`.

4. Add `shaun` to the hardware groups (log out/in afterwards):

   ```bash
   sudo usermod -aG dialout,tty,audio,video,render shaun
   ```

---

## 3. Packages

```bash
sudo add-apt-repository universe
sudo apt update
sudo apt install \
    direwolf libhamlib-utils ax25-tools ax25-apps \
    xvfb xauth x11-xkb-utils dbus-x11 \
    tmux nmap alsa-utils psmisc lsof \
    wget unzip screen libcap2-bin

# Kernel AX.25 modules (for the optional axcall test stack, §9)
sudo apt install linux-modules-extra-$(uname -r)

# Wine for VARA (32-bit libs needed)
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install wine64 wine32 winetricks
```

linbpq's runtime libraries:

```bash
sudo apt install libpcap0.8-dev libasound2-dev zlib1g libminiupnpc17
```

Optional (installed on the old box, not required for the node):
`flrig`, `gpsd gpsd-clients`, `tigervnc-standalone-server`, `xterm`.

---

## 4. udev rules — stable serial device names

`bpq32.cfg` and the start scripts refer to symlinks, not raw `ttyUSBn`
numbers. Restore `/etc/udev/rules.d/99-usb-serial.rules`:

```
# IC-7100 A (CAT) and B ports
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", ENV{ID_SERIAL}=="Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7100_02014042_A", SYMLINK+="ttyUSB_IC7100_A"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", ENV{ID_SERIAL}=="Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7100_02014042_B", SYMLINK+="ttyUSB_IC7100_B"

# SCS PTC-IIusb Pactor modem
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="d010", ENV{ID_SERIAL}=="SCS_SCS_PTC-IIusb_PTS955D1", SYMLINK+="ttyUSB_PTCIIUSB"

# Ten-Tec Eagle (alternate HF rig)
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="2405", ENV{ID_MODEL_ID}=="000b", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="tentec"

# CP2105 dual UART (FT-991A CAT = enhanced port)
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="10c4", ENV{ID_MODEL_ID}=="ea70", ENV{ID_SERIAL_SHORT}=="00F618F9", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="cp2105_enhanced"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="10c4", ENV{ID_MODEL_ID}=="ea70", ENV{ID_SERIAL_SHORT}=="00F618F9", ENV{ID_USB_INTERFACE_NUM}=="01", SYMLINK+="cp2105_standard"

# Second CP2105 (serial 011F44FB) → ttyUSB30/31
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="10c4", ENV{ID_MODEL_ID}=="ea70", ENV{ID_USB_SERIAL_SHORT}=="011F44FB", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="ttyUSB30"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="10c4", ENV{ID_MODEL_ID}=="ea70", ENV{ID_USB_SERIAL_SHORT}=="011F44FB", ENV{ID_USB_INTERFACE_NUM}=="01", SYMLINK+="ttyUSB31"
```

Then: `sudo udevadm control --reload-rules && sudo udevadm trigger`.

> **New hardware note:** the `ID_SERIAL` / `ID_SERIAL_SHORT` values are
> per-device serial numbers. If a USB adapter is ever replaced, get the
> new values with `udevadm info -q property -n /dev/ttyUSBn` and update
> the rule. The IC-7100 identifies itself by name, so its rules survive
> cable/port changes.

Verify: `ls -l /dev/ttyUSB_IC7100_A /dev/ttyUSB_PTCIIUSB /dev/cp2105_enhanced`
(with the radios plugged in).

---

## 5. Network (netplan)

The machine uses a hand-written `/etc/netplan/01-ax25.yaml` (mode 600,
root-owned) instead of the installer's `50-cloud-init.yaml` /
NetworkManager files, which were moved out of `/etc/netplan/` to `~`.
It gives `eno1` a static address on the hamnet subnet, with the hamnet
router (10.73.73.1) as default gateway and primary DNS:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eno1:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      addresses:
        - 10.73.73.5/29
      routes:
        - to: default
          via: 10.73.73.1
      nameservers:
        addresses: [10.73.73.1, 9.9.9.9, 1.1.1.1]
```

Restore procedure: place the file in `/etc/netplan/`,
`sudo chmod 600 /etc/netplan/01-ax25.yaml`, remove other yaml files from
that directory, then `sudo netplan try` (it auto-reverts if you lose the
session). Confirm with `ip a`, `ping 10.6.6.1`, `ping google.com`, and
`tailscale netcheck`.

---

## 6. Wine + VARA

VARA HF is a 32/64-bit Windows app run under the **default wine prefix**
`~/.wine` (a `~/prefix32` win32 prefix exists from early experiments but
is not what BPQ launches).

```bash
wine wineboot                       # create ~/.wine
winetricks vcrun2010 vcrun2013 vcrun2015 vb6run   # runtimes VARA needs
cd ~/vara-installers
wine "VARA setup (Run as Administrator).exe"      # install to C:\VARA
wine "VARA FM setup (Run as Administrator).exe"   # optional, C:\VARA FM
```

Then restore `~/.wine/drive_c/VARA/VARA.ini` from backup (callsign,
license, soundcard and PTT settings). If starting fresh instead, run
`wine C:\\VARA\\VARA.exe` once under a real display and configure:
callsign W2QS, license key, soundcard = the FT-991A USB codec,
PTT = CAT.

BPQ launches VARA itself via port 5's config line
(`PATH wine-stable C:\\VARA\\VARA.exe`), so nothing needs to autostart.

---

## 7. linbpq

```bash
mkdir ~/linbpq && cd ~/linbpq
wget http://www.cantab.net/users/john.wiseman/Downloads/Beta/linbpq64
chmod +x linbpq64
```

Restore from backup into `~/linbpq/`:

- `bpq32.cfg` (and the alternate-rig variants if wanted:
  `bpq32.cfg.ftdx10`, `bpq32.cfg.tentec`, `bpq32.cfg.ICOM` — the node
  has run with different HF rigs; the active file is the FT-991A/VARA/
  Pactor + IC-7100 packet version described in §0)
- `linmail.cfg`, `WP.cfg`, `DIRMES.SYS`, `BPQNODES.dat`
- the whole `Mail/` directory
- `direwolf.conf`, `direwolf-bpq-start.sh`, `start_bpq.sh`

`start_bpq.sh` is three lines:

```bash
Xvfb :99 &
export DISPLAY=:99
/home/shaun/linbpq/linbpq64 mail
```

(Xvfb because the VARA GUI needs *a* display; `mail` starts the BBS.)

Key secrets inside `bpq32.cfg` (restore from backup — not recorded
here): the `PASSWORD=` sysop password and the telnet
`USER=<user>,<password>,W2QS,"",sysop` line. The telnet user matches
`BPQ_USER` in this repo's `bpq.env`.

`direwolf.conf` (current contents, for reference):

```
ADEVICE plughw:1,0          # IC-7100 USB audio codec — check card no. with arecord -l
ACHANNELS 1
CHANNEL 0
MYCALL W2QS-7
MODEM 1200
PTT RIG 2 127.0.0.1:4532    # PTT via rigctld
TXDELAY 100
TXTAIL 30
PERSIST 63
SLOTTIME 10
AGWPORT 8000
KISSPORT 8001               # bpq32.cfg port 3 connects here
```

`direwolf-bpq-start.sh` starts rigctld for the IC-7100
(`-m 3070 -s 19200 -c 0x88` on `/dev/serial/by-id/*IC-7100*_A-if00-port0`),
waits until CAT answers, then runs Dire Wolf in the foreground.

### Swapping in a different radio (regenerating the config)

The node has run with several HF rigs (FTdx10, Ten-Tec Eagle, FT-991A —
hence `bpq32.cfg.ftdx10`, `bpq32.cfg.tentec`, `bpq32.cfg.ICOM` in the
backup). The working pattern, refined over those swaps:

**1. Identify the new radio's serial device and give it a stable name.**

```bash
ls -l /dev/serial/by-id/          # often good enough on its own
udevadm info -q property -n /dev/ttyUSB0    # note ID_VENDOR_ID, ID_MODEL_ID,
                                            # ID_SERIAL / ID_SERIAL_SHORT,
                                            # ID_USB_INTERFACE_NUM (dual-UART chips)
```

Add a rule to `/etc/udev/rules.d/99-usb-serial.rules` following the §4
patterns, then `sudo udevadm control --reload-rules && sudo udevadm
trigger` and confirm the symlink appears. For dual-UART chips (CP2105,
IC-7100) match `ID_USB_INTERFACE_NUM` too — CAT is usually the
"enhanced"/A interface.

**2. Find the Hamlib model number and verify CAT works** before
touching any BPQ config:

```bash
rigctld --list | grep -i <radio name>       # e.g. 3070=IC-7100, 1042=FTdx10, 16013=Ten-Tec Eagle
rigctl -m <model> -r /dev/<symlink> -s <baud> f    # must return the dial frequency
```

Iterate on baud rate (and `-c <CI-V addr>` for Icoms) until `f` answers.
Radio-side: enable CAT in the rig's menus and note its configured baud.

**3. Update the config for the role the radio plays:**

- **2 m packet (Dire Wolf):** no bpq32.cfg change needed — port 3 only
  knows about KISS TCP 8001. Set `RIG_MODEL`, `RIG_BAUD`,
  `RIG_CIV_ADDRESS`, `RIG_DEVICE` at the top of (or as env vars to)
  `direwolf-bpq-start.sh`, and update `ADEVICE` in `direwolf.conf` to
  the new radio's soundcard (`arecord -l` to list; test capture with
  `arecord -D plughw:X,0 -f S16_LE -V mono /dev/null` while the channel
  is busy).
- **HF VARA:** point VARA at the new soundcard and CAT/PTT in its own
  GUI (`DISPLAY=:0 wine C:\\VARA\\VARA.exe`, or via the running node's
  VARA window), and update the `RIGCONTROL` block under port 4 in
  `bpq32.cfg` — device path, baud, and rig type on the first line
  (currently `/dev/cp2105_enhanced 38400 YAESU FT991A PTT_SETS_INPUT`);
  the frequency-schedule lines below it usually carry over unchanged.
- **HF Pactor:** the PTC-IIusb modem side never changes; only the same
  `RIGCONTROL` block above matters (it retunes the radio for both
  Pactor and VARA — `INTERLOCK=1` ties ports 4 and 5 together).

**4. Test in the foreground, then snapshot.** Keep the old config as a
variant, edit, and run linbpq interactively so parse errors are visible:

```bash
cd ~/linbpq
cp bpq32.cfg bpq32.cfg.<old-rig>     # snapshot before editing
nano bpq32.cfg
./start_bpq.sh                        # watch startup output for port errors
```

Iterate until all ports come up clean, verify with the §8 checks
(`nmap`, telnet login, `MHEARD`, a test VARA or packet connect), then
save the working file as `bpq32.cfg.<new-rig>` so the next swap starts
from a known-good copy — and refresh the off-machine backup (§1).

---

## 8. Start the node (runbook)

Everything runs in one tmux session, started manually after boot:

```bash
tmux new -s linbpq            # or plain `tmux`

# window 1 — radio stack
cd ~/linbpq
./direwolf-bpq-start.sh       # rigctld + direwolf; stays in foreground

# window 2 (Ctrl-b c) — BPQ
cd ~/linbpq
./start_bpq.sh                # Xvfb + linbpq64 mail (launches VARA)
```

Detach with `Ctrl-b d`; reattach later with `tmux attach`.

Order matters: Dire Wolf must be listening on 8001 before linbpq starts,
or BPQ's port 3 won't attach.

### Verify

```bash
nmap localhost                # expect 8000/8001 (direwolf), 8010/8012 (BPQ), 4532 (rigctld)
telnet localhost 8010         # BPQ telnet login with the bpq32.cfg USER
rigctl -m 2 -r localhost:4532 f   # IC-7100 frequency via rigctld
```

Browse the node console at `http://<host>:8012`. Check
`~/linbpq/logs/log_<date>_BBS.txt` for BBS activity, and confirm AXIP
partners appear in `NODES` after a broadcast interval (UDP 10093 must be
reachable/forwarded if behind NAT).

---

## 9. Optional: kernel AX.25 test stack (axcall)

For interactive keyboard connects on 2 m without BPQ,
`~/ic7100-packet-start.sh` builds a kernel AX.25 stack (rigctld +
direwolf + kissattach + mkiss → `ax0`). It needs:

```bash
sudo modprobe ax25 mkiss
sudo mkdir -p /etc/ax25
```

`/etc/ax25/axports`:

```
radio W2QS-7 0 255 2 IC-7100 145.070 Packet
```

Then `bash ~/ic7100-packet-start.sh` and e.g. `axcall radio K1YMI-4`.
Don't run it at the same time as the BPQ stack — they'd fight over the
radio and rigctld port.

---

## 10. bpq-tasks (this repo) + cron

```bash
cd ~ && git clone <this-repo> bpq-tasks
cd bpq-tasks
cp bpq.env.sample bpq.env && chmod 600 bpq.env
# restore real values from backup: BPQ_HOST/PORT/USER + BPQ_PASS,
# QRZ credentials, Telegram bot token/chat id
```

Supporting dirs and log-backup script:

```bash
mkdir -p ~/scripts ~/bpq_backup_logs ~/bpq_mail_archive ~/bpq_cron_logs
```

`~/scripts/bpq_logs.sh`:

```bash
#!/bin/bash
echo "Copying logs to backup dir..."
cp -r -u /home/shaun/linbpq/logs/* /home/shaun/bpq_backup_logs/
echo "Done"

echo "Copying messages to backup dir..."
cp -r -u /home/shaun/linbpq/Mail/*.mes /home/shaun/bpq_mail_archive/
echo "Done"
```

Crontab (`crontab -e`):

```cron
0 * * * * /home/shaun/scripts/bpq_logs.sh
0 */12 * * * source /home/shaun/bpq-tasks/bpq.env && /usr/bin/python3 /home/shaun/bpq-tasks/bpq_admin.py notify-stale >> /home/shaun/bpq-tasks/bpq_admin.log 2>&1
```

(The old box also had a `*/1 * * * * ~/bin/conky/grid` line from the
73Linux desktop setup — cosmetic, skip it.)

---

## 11. Known dead ends (do not resurrect)

Present in the old machine's history/filesystem but **not in use** —
listed so a future rebuild doesn't waste time on them:

- `linbpq.service` + `/usr/local/bin/linbpq-xvfb.sh` and
  `rigctld.service` (FTdx10-era): both installed but **disabled**; the
  tmux runbook in §8 replaced them. Re-enabling `linbpq.service` is a
  reasonable future improvement, but its wrapper doesn't start Dire Wolf
  first, so it would need work.
- TigerVNC / Chrome Remote Desktop: remote access is Tailscale SSH now.
- `~/prefix32` Wine prefix: superseded by `~/.wine`.
- pat, gpsd, flrig, 73Linux/conky: unrelated to the node.
- A `BBS` nologin system user was once created (`useradd BBS -M -s
  /usr/sbin/nologin`); nothing in the current stack references it.

---

## 12. Post-rebuild checklist

- [ ] Tailscale up, SSH keys restored, machine reachable at its tailnet name
- [ ] `ls -l /dev/ttyUSB_IC7100_A /dev/ttyUSB_PTCIIUSB /dev/cp2105_enhanced` all resolve
- [ ] `netplan` applied; LAN, internet, hamnet (10.6.6.1) and tailnet all ping
- [ ] tmux stack up; `nmap localhost` shows 4532, 8000/8001, 8010, 8012
- [ ] Telnet login works; `bpq_admin.py list` from this repo succeeds
- [ ] VARA window appears in BPQ (check via HTTP console); VARA shows **licensed**, not trial
- [ ] Heard stations appear on port 3 (`MHEARD`) and AXIP nodes repopulate
- [ ] A test message to the BBS forwards correctly
- [ ] Cron jobs firing (`grep CRON /var/log/syslog`); notify-stale Telegram message arrives
- [ ] Off-machine backup of §1 files re-established from the new build
