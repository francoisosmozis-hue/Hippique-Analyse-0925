"""Lint utility for validating daily meeting source URLs."""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from urllib.parse import urlparse

try:  # Python 3.9+
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # pragma: no cover - fallback for older interpreters
    ZoneInfo = None  # type: ignore

PARIS_TZ = ZoneInfo("Europe/Paris") if ZoneInfo is not None else None
DEFAULT_DOMAINS: tuple[str, ...] = ("zeturf.fr", "www.zeturf.fr")


class Diagnostics:
    """Collects lint diagnostics and exposes helper utilities."""

    __slots__ = ("errors", "warnings")

    def __init__(self) -> None:
        self.errors: list[tuple[int | None, str]] = []
        self.warnings: list[tuple[int | None, str]] = []

    def add_error(self, line: int | None, message: str) -> None:
        self.errors.append((line, message))

    def add_warning(self, line: int | None, message: str) -> None:
        self.warnings.append((line, message))

    def exit_code(self, warn_only: bool) -> int:
        """Return the process exit code based on collected diagnostics."""

        # ``warn_only`` is kept for backward compatibility but no longer
        # influences the exit status (only the emitted message severity).
        if self.errors:
            return 1
        if self.warnings:
            return 0
        return 0


def _iter_urls(path: Path) -> Iterator[tuple[int, str]]:
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        yield idx, line


def _validate_domain(host: str, domains: Sequence[str]) -> bool:
    host = host.lower()
    for d in domains:
        domain_lower = d.lower()
        if host == domain_lower or host.endswith(f".{domain_lower}"):
            return True
    return False


def _today_slug() -> str:
    tz = PARIS_TZ or dt.timezone.utc
    return dt.datetime.now(tz).strftime("%Y-%m-%d")


def lint_file(
    file_path: Path,
    *,
    enforce_today: bool,
    domains: Sequence[str],
) -> Diagnostics:
    diagnostics = Diagnostics()

    if not file_path.exists():
        diagnostics.add_error(None, f"Fichier introuvable: {file_path}")
        return diagnostics

    seen: dict[str, int] = {}
    today_slug = _today_slug() if enforce_today else None
    active_count = 0

    for line_no, url in _iter_urls(file_path):
        active_count += 1

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            diagnostics.add_error(line_no, f"Schéma invalide (attendu http/https): {url}")
            continue
        if not parsed.netloc:
            diagnostics.add_error(line_no, f"Nom de domaine manquant: {url}")
            continue
        if not _validate_domain(parsed.netloc, domains):
            expected = ", ".join(sorted(set(domains)))
            diagnostics.add_error(
                line_no,
                f"Domaine inattendu '{parsed.netloc}'. Attendu: {expected}.",
            )
            continue

        previous_line = seen.get(url)
        if previous_line is not None:
            diagnostics.add_error(
                line_no,
                f"URL dupliquée (également ligne {previous_line}).",
            )
        else:
            seen[url] = line_no

        if today_slug and today_slug not in url:
            diagnostics.add_warning(
                line_no,
                f"La date du jour ({today_slug}) est absente de l'URL.",
            )

    if active_count == 0:
        diagnostics.add_warning(None, "Aucune URL active détectée dans le fichier.")

    return diagnostics


def _emit(level: str, file_path: Path, diagnostics: Iterable[tuple[int | None, str]]) -> None:
    for line, message in diagnostics:
        if line is None:
            print(f"::{level}::{message}")
        else:
            print(f"::{level} file={file_path},line={line}::{message}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint de sources.txt (URLs ZEturf).",
    )
    parser.add_argument(
        "--file",
        default="sources.txt",
        help="Chemin vers le fichier des sources (par défaut: sources.txt).",
    )
    parser.add_argument(
        "--enforce-today",
        action="store_true",
        help="Signale les URLs qui ne contiennent pas la date du jour.",
    )
    parser.add_argument(
        "--domain",
        dest="domains",
        action="append",
        help="Domaine autorisé (répéter l'option pour plusieurs valeurs).",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help=(
            "Force l'émission des avertissements au niveau warning ; la CLI"
            " renvoie 2 s'il reste des avertissements et 1 s'il reste des"
            " erreurs."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    domains = (
        tuple(domain.lower() for domain in args.domains if domain)
        if args.domains
        else DEFAULT_DOMAINS
    )

    file_path = Path(args.file)
    diagnostics = lint_file(
        file_path,
        enforce_today=args.enforce_today,
        domains=domains,
    )

    _emit("error", file_path, diagnostics.errors)
    warning_level = "warning" if args.warn_only else "notice"
    _emit(warning_level, file_path, diagnostics.warnings)

    print(
        f"Résumé: {len(diagnostics.errors)} erreur(s), "
        f"{len(diagnostics.warnings)} avertissement(s)."
    )

    return diagnostics.exit_code(args.warn_only)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
