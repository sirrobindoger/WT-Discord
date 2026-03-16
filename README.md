# WarThunderRPC

War Thunder Discord Rich Presence for Windows. The app reads War Thunder's local telemetry on `127.0.0.1:8111` and updates Discord with your current vehicle, map, and match state.

Download the latest `WarThunderRPC_Setup.exe` from GitHub Releases to install it. The repository is mainly for development and building releases.

## Requirements

- Windows
- Python 3.11+

## Features

- Detects whether you are in the hangar, a test drive, or a live match
- Shows the current vehicle and resolves a cleaner display name for many vehicles
- Identifies the current map from War Thunder's local map telemetry
- Tracks simple live match context such as match type and kill count
- Supports both local testing and a packaged Windows `.exe` workflow

Example RPC status:

> Driving a M1A1 HC, 3/4 Crew  
> Ground Battle, 2 Kills

## Setup

Use the repo-local virtual environment for everything:

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

These commands are only for managing a Python environment. The packaged app, Windows service integration, and `.exe` build target are Windows-only.

## Build the EXE

### Windows

```powershell
.venv\Scripts\python.exe build.py
```

This produces `dist\WarThunderRPC_Setup.exe`.

## GitHub Releases

Publishing a GitHub Release will trigger the Actions workflow in `.github/workflows/build-release.yml`. It builds the Windows `.exe`, uploads it as a workflow artifact, and attaches `WarThunderRPC_Setup.exe` to the published release automatically.
