#!/usr/bin/env python3
import argparse
import subprocess
import sys


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
    for domain in domains:
        domain = domain.lower()
        if host == domain or host.endswith(f".{domain}"):
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
    args = ap.parse_args()

    steps = []
    if args.fix:
        steps += [
            ["ruff", "check", "--select", "I", "--fix", "."],
            ["isort", "."],
            ["black", "."],
        ]
    steps += [["ruff", "check", "."]]

    for cmd in steps:
        print("$", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
