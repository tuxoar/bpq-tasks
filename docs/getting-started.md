[← back to README](../README.md)

# Getting started

## Getting Python

You need Python **3.8 or newer** (3.13+ works — the script doesn't use the
removed `telnetlib` module). No packages to install; the standard library
is enough.

**Windows** — install from [python.org/downloads](https://www.python.org/downloads/)
(check **"Add python.exe to PATH"** during install), or from a terminal:

```powershell
winget install Python.Python.3.12
```

Then run scripts with either `python` or the `py` launcher:

```powershell
py bpq_admin.py list mynode.example.com --user N0CALL
```

If typing `python` opens the Microsoft Store instead of Python, use `py`,
or disable the Store alias under *Settings → Apps → Advanced app settings →
App execution aliases*.

**macOS** — macOS no longer ships Python. Install with
[Homebrew](https://brew.sh) (`brew install python`) or the
[python.org](https://www.python.org/downloads/) installer, then use
`python3`:

```bash
python3 bpq_admin.py list mynode.example.com --user N0CALL
```

**Linux** — almost always preinstalled as `python3`. If not:
`sudo apt install python3` (Debian/Ubuntu), `sudo dnf install python3`
(Fedora), or `sudo pacman -S python` (Arch).

```bash
python3 bpq_admin.py list mynode.example.com --user N0CALL
# or make it directly executable:
chmod +x bpq_admin.py
./bpq_admin.py list mynode.example.com --user N0CALL
```

Check your install with `python3 --version` (or `py --version` on Windows).

> The examples in these docs use `python`; substitute `python3` or `py` as
> your system requires.

## Quick start

1. Get the tool:

   ```bash
   git clone <this-repo-url>
   cd bpq-tasks
   ```

   (Or just download the script you need — each is self-contained.)

2. Find your node's telnet details: the host is wherever your node runs,
   and the port is the one configured in the Telnet Server section of
   `bpq32.cfg` (commonly `8010`). Your login is usually your callsign and
   the password from your node user entry.

3. List your new private messages:

   ```bash
   python bpq_admin.py list mynode.example.com --port 8010 --user N0CALL
   ```

   You'll be prompted for your password, then see something like:

   ```
   Connected to mynode.example.com:8010
   Logged in, entering BBS...
   BBS login successful (prompt 'de N0CALL>')
   running LPN ...
   3309   31-Aug PN      22 W2QS   @W2QS   W2QS   test
   ```

If that works, everything else is the same command shape:
`python bpq_admin.py ACTION HOST --user USER [options]`.

Next steps:

- [Configuration](configuration.md) — common arguments, and keeping
  credentials out of shell history with an env file.
- The [README](../README.md) — the full list of actions, each linking to
  its own page.
