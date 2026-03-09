from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

BEGIN_MARKER = "# >>> veille-tech cron (managed) >>>"
END_MARKER = "# <<< veille-tech cron (managed) <<<"


def ask_yes_no(prompt: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    accepted_yes = {"y", "yes", "o", "oui"}
    accepted_no = {"n", "no", "non"}

    while True:
        raw = input(f"{prompt} {suffix} ").strip().lower()
        if not raw:
            return default
        if raw in accepted_yes:
            return True
        if raw in accepted_no:
            return False
        print("Reponse invalide. Tape y/n.")


def ask_int(prompt: str, default: int, min_value: int, max_value: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}] ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Valeur invalide: entre un entier.")
            continue

        if min_value <= value <= max_value:
            return value
        print(f"Valeur hors limite: {min_value}..{max_value}")


def ask_text(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}] ").strip()
    return raw or default


def parse_env_defaults(env_path: Path) -> dict[str, str]:
    defaults: dict[str, str] = {}
    if not env_path.exists():
        return defaults

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        defaults[key.strip()] = value.strip().strip('"').strip("'")
    return defaults


def parse_int_or_fallback(raw: str | None, fallback: int, min_value: int, max_value: int) -> int:
    if raw is None:
        return fallback
    try:
        value = int(raw.strip())
    except ValueError:
        return fallback
    if min_value <= value <= max_value:
        return value
    return fallback


def read_crontab_lines() -> list[str]:
    proc = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout.splitlines()

    message = f"{proc.stdout}\n{proc.stderr}".lower()
    if "no crontab for" in message:
        return []

    raise RuntimeError(
        "Impossible de lire la crontab actuelle:\n"
        f"stdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )


def write_crontab_lines(lines: list[str]) -> None:
    content = "\n".join(lines).strip()
    if content:
        content += "\n"

    proc = subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Impossible d'ecrire la crontab:\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )


def strip_managed_block(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    inside_block = False

    for line in lines:
        if line == BEGIN_MARKER:
            inside_block = True
            continue
        if line == END_MARKER:
            inside_block = False
            continue
        if not inside_block:
            cleaned.append(line)

    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned


def build_command(
    project_root: Path,
    python_bin: str,
    script_name: str,
    log_path: Path,
) -> str:
    root_q = shlex.quote(str(project_root))
    python_q = shlex.quote(python_bin)
    script_q = shlex.quote(str(project_root / script_name))
    log_q = shlex.quote(str(log_path))
    return f"cd {root_q} && {python_q} {script_q} >> {log_q} 2>&1"


def main() -> int:
    project_root = Path(__file__).resolve().parent
    env_defaults = parse_env_defaults(project_root / ".env")

    default_timezone = env_defaults.get("TIMEZONE", "Europe/Paris")
    default_run_hour = parse_int_or_fallback(
        env_defaults.get("RUN_HOUR"),
        8,
        0,
        23,
    )
    default_run_minute = parse_int_or_fallback(
        env_defaults.get("RUN_MINUTE"),
        30,
        0,
        59,
    )
    default_cyber_minute = parse_int_or_fallback(
        env_defaults.get("CYBER_RUN_MINUTE"),
        0,
        0,
        59,
    )
    default_cyber_hour = parse_int_or_fallback(
        env_defaults.get("CYBER_RUN_HOUR"),
        10,
        0,
        23,
    )

    default_python = project_root / ".venv" / "bin" / "python3"
    python_bin_default = (
        str(default_python)
        if default_python.exists()
        else sys.executable
    )

    print("=== Setup cron veille-tech ===")
    print("Ce script ecrit un bloc gere automatiquement dans ta crontab utilisateur.\n")

    install_daily = ask_yes_no("Activer le job quotidien IA (run_once.py) ?", True)
    daily_hour = None
    daily_minute = None
    if install_daily:
        daily_hour = ask_int("Heure quotidienne (0-23)", default_run_hour, 0, 23)
        daily_minute = ask_int("Minute quotidienne (0-59)", default_run_minute, 0, 59)

    install_cyber = ask_yes_no(
        "Activer le job cyber quotidien (run_cyber_once.py) ?",
        True,
    )
    cyber_hour = None
    cyber_minute = None
    if install_cyber:
        cyber_hour = ask_int("Heure quotidienne cyber (0-23)", default_cyber_hour, 0, 23)
        cyber_minute = ask_int("Minute quotidienne cyber (0-59)", default_cyber_minute, 0, 59)

    if not install_daily and not install_cyber:
        if not ask_yes_no(
            "Aucun job selectionne. Supprimer le bloc veille-tech existant de la crontab ?",
            True,
        ):
            print("Aucun changement.")
            return 0

    timezone = ask_text("Timezone cron (CRON_TZ)", default_timezone)
    python_bin = ask_text("Chemin Python a utiliser", python_bin_default)

    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ai_log = logs_dir / "ai-cron.log"
    cyber_log = logs_dir / "cyber-cron.log"

    managed_lines: list[str] = []
    if install_daily or install_cyber:
        managed_lines.append(BEGIN_MARKER)
        managed_lines.append(f"CRON_TZ={timezone}")
        managed_lines.append("")

        if install_daily and daily_hour is not None and daily_minute is not None:
            managed_lines.append("# Veille IA quotidienne")
            managed_lines.append(
                f"{daily_minute} {daily_hour} * * * "
                f"{build_command(project_root, python_bin, 'run_once.py', ai_log)}"
            )
            managed_lines.append("")

        if install_cyber and cyber_hour is not None and cyber_minute is not None:
            managed_lines.append("# Veille cyber quotidienne")
            managed_lines.append(
                f"{cyber_minute} {cyber_hour} * * * "
                f"{build_command(project_root, python_bin, 'run_cyber_once.py', cyber_log)}"
            )
            managed_lines.append("")

        managed_lines.append(END_MARKER)

    print("\nBloc cron genere:")
    if managed_lines:
        print("\n".join(managed_lines))
    else:
        print("(suppression du bloc veille-tech)")

    if not ask_yes_no("\nAppliquer ces changements a la crontab maintenant ?", True):
        print("Annule. Aucun changement applique.")
        return 0

    current_lines = read_crontab_lines()
    kept_lines = strip_managed_block(current_lines)
    new_lines = kept_lines.copy()
    if managed_lines:
        if new_lines:
            new_lines.append("")
        new_lines.extend(managed_lines)

    write_crontab_lines(new_lines)
    print("\nCron configure avec succes.")

    if install_daily:
        assert daily_hour is not None and daily_minute is not None
        print(f"- IA quotidienne: {daily_hour:02d}:{daily_minute:02d}")
    if install_cyber:
        assert cyber_hour is not None and cyber_minute is not None
        print(f"- Cyber quotidien: {cyber_hour:02d}:{cyber_minute:02d}")
    if not install_daily and not install_cyber:
        print("- Bloc veille-tech supprime de la crontab")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
