from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

from amazify.shortcuts import install_amazify_shortcuts, remove_amazify_shortcuts


APP_NAME = "Amazify"
APP_VERSION = "0.1.0"
EXE_NAME = "amazify.exe"
WINDOWED_EXE_DIR_NAME = "amazifyw"
WINDOWED_EXE_NAME = "amazifyw.exe"
SETUP_NAME = "AmazifySetup.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Amazify"


def bundled_file(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set")
    return Path(local_app_data) / "Programs" / APP_NAME


def normalize_path(path: str | Path) -> str:
    return str(Path(path).resolve()).rstrip("\\")


def user_path_entries() -> list[str]:
    try:
        raw = winreg.QueryValueEx(
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment"),
            "Path",
        )[0]
    except FileNotFoundError:
        return []
    if not isinstance(raw, str):
        return []
    return [entry for entry in raw.split(";") if entry.strip()]


def write_user_path(entries: list[str]) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(entries))


def add_to_user_path(path: Path) -> bool:
    target = normalize_path(path)
    entries = user_path_entries()
    normalized_entries = {normalize_path(entry).lower() for entry in entries}
    if target.lower() in normalized_entries:
        return False
    write_user_path([*entries, target])
    return True


def remove_from_user_path(path: Path) -> bool:
    target = normalize_path(path).lower()
    entries = user_path_entries()
    kept = [entry for entry in entries if normalize_path(entry).lower() != target]
    if len(kept) == len(entries):
        return False
    write_user_path(kept)
    return True


def write_uninstall_entry(target_dir: Path, setup_path: Path) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Amazify")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target_dir / EXE_NAME))
        winreg.SetValueEx(
            key,
            "UninstallString",
            0,
            winreg.REG_SZ,
            f'"{setup_path}" --uninstall',
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def delete_uninstall_entry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass


def _is_windowed() -> bool:
    """Return True when running as a windowed PyInstaller executable (no console)."""
    return sys.stdout is None


def _message_box(title: str, message: str, *, error: bool = False) -> None:
    """Show a Windows MessageBox.  Used for feedback in windowed (no-console) mode."""
    try:
        import ctypes

        MB_OK = 0x0
        MB_ICONERROR = 0x10
        MB_ICONINFORMATION = 0x40
        icon = MB_ICONERROR if error else MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK | icon)
    except Exception:
        pass


def notify_environment_change() -> None:
    try:
        import ctypes

        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def install(args: argparse.Namespace) -> int:
    source_exe = bundled_file(EXE_NAME)
    if not source_exe.exists():
        raise RuntimeError(f"Installer is missing bundled {EXE_NAME}")

    target_dir = install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    target_exe = target_dir / EXE_NAME
    source_windowed_dir = bundled_file(WINDOWED_EXE_DIR_NAME)
    source_windowed_exe = bundled_file(WINDOWED_EXE_NAME)
    target_windowed_dir = target_dir / WINDOWED_EXE_DIR_NAME
    target_windowed_exe = target_windowed_dir / WINDOWED_EXE_NAME
    legacy_windowed_exe = target_dir / WINDOWED_EXE_NAME
    setup_copy = target_dir / SETUP_NAME
    shutil.copy2(source_exe, target_exe)
    shortcut_exe = target_exe
    if source_windowed_dir.is_dir():
        if target_windowed_dir.exists():
            shutil.rmtree(target_windowed_dir)
        shutil.copytree(source_windowed_dir, target_windowed_dir)
        shortcut_exe = target_windowed_exe
        if legacy_windowed_exe.exists():
            legacy_windowed_exe.unlink()
    elif source_windowed_exe.exists():
        target_windowed_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_windowed_exe, target_windowed_exe)
        shortcut_exe = target_windowed_exe
        if legacy_windowed_exe.exists():
            legacy_windowed_exe.unlink()
    shutil.copy2(Path(sys.executable), setup_copy)

    path_changed = add_to_user_path(target_dir)
    write_uninstall_entry(target_dir, setup_copy)
    shortcut_result = install_amazify_shortcuts(
        shortcut_exe,
        start_menu=not args.no_start_menu_shortcut,
        desktop=args.desktop_shortcut or args.shortcuts,
        taskbar=args.taskbar_shortcut or args.shortcuts,
    )
    notify_environment_change()

    lines: list[str] = []
    lines.append(f"{APP_NAME} installed.")
    lines.append(f"Installed CLI: {target_exe}")
    lines.append(f"Command: amazify")
    for shortcut in shortcut_result.created:
        lines.append(f"Created shortcut: {shortcut}")
    for warning in shortcut_result.warnings:
        lines.append(f"Shortcut warning: {warning}")
    if path_changed:
        lines.append(f"Added to user PATH: {target_dir}")
        lines.append("Open a new terminal if the command is not visible in this one yet.")
    else:
        lines.append("User PATH already contains the install directory.")
    windowed = _is_windowed()
    if sys.stdout is not None:
        for line in lines:
            print(line)
    if windowed:
        summary = (
            f"{APP_NAME} has been installed successfully.\n\n"
            f"Launch Amazon Music (Amazify) from the Start Menu to get started."
        )
        if shortcut_result.warnings:
            summary += "\n\nWarnings:\n" + "\n".join(shortcut_result.warnings)
        _message_box(f"{APP_NAME} Setup", summary)
    return 0


def uninstall() -> int:
    target_dir = install_dir()
    remove_from_user_path(target_dir)
    shortcut_result = remove_amazify_shortcuts()
    delete_uninstall_entry()
    notify_environment_change()

    if target_dir.exists():
        command = f'ping 127.0.0.1 -n 2 > nul & rmdir /s /q "{target_dir}"'
        subprocess.Popen(
            ["cmd", "/c", command],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    windowed = _is_windowed()
    if sys.stdout is not None:
        print(f"{APP_NAME} uninstalled.")
        for shortcut in shortcut_result.removed:
            print(f"Removed shortcut: {shortcut}")
        for warning in shortcut_result.warnings:
            print(f"Shortcut warning: {warning}")
    if windowed:
        summary = f"{APP_NAME} has been uninstalled."
        if shortcut_result.warnings:
            summary += "\n\nWarnings:\n" + "\n".join(shortcut_result.warnings)
        _message_box(f"{APP_NAME} Setup", summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Amazify for the current Windows user.")
    parser.add_argument("--uninstall", action="store_true", help="Remove Amazify from this user account.")
    parser.add_argument(
        "--shortcuts",
        action="store_true",
        help="Create all optional launch shortcuts, including Desktop and taskbar.",
    )
    parser.add_argument(
        "--desktop-shortcut",
        action="store_true",
        help="Create an Amazon Music (Amazify) shortcut on the Desktop.",
    )
    parser.add_argument(
        "--taskbar-shortcut",
        action="store_true",
        help="Try to pin the Amazon Music (Amazify) shortcut to the taskbar.",
    )
    parser.add_argument(
        "--no-start-menu-shortcut",
        action="store_true",
        help="Do not create the default Amazon Music (Amazify) Start Menu shortcut.",
    )
    args = parser.parse_args(argv)
    if args.uninstall:
        return uninstall()
    return install(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        msg = f"Install failed: {exc}"
        if sys.stderr is not None:
            try:
                print(msg, file=sys.stderr)
            except (AttributeError, OSError):
                pass
        if _is_windowed():
            _message_box(f"{APP_NAME} Setup", msg, error=True)
        raise SystemExit(1)
