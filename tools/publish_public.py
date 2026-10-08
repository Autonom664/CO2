"""Build a filtered public copy of this repository, and optionally push it.

The working repository keeps its full history, including the agents'
internal coordination files. The public copy:

- drops those files from every commit (decision D22)
- rewrites the author e-mail to a GitHub noreply address (D23)
- rewords commit messages that name internal hosts
- is scanned afterwards; publishing stops if anything internal is left

    python tools/publish_public.py --noreply 12345+user@users.noreply.github.com
    python tools/publish_public.py --noreply ... --remote git@github.com:user/repo.git --push

Needs git-filter-repo (pip install git-filter-repo). Without --push it
only builds and checks the copy in --out.
"""

from __future__ import annotations

import argparse
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Internal coordination files: kept in the working repo, never published.
PRIVATE_PATHS = [
    "docs/HANDOFF.md",
    "docs/HANDOFF_ARCHIVE.md",
    "docs/COPILOT_COLLABORATION_PROPOSAL.md",
    "docs/collab/claude_proposal.md",
    "docs/collab/AGREEMENT.md",
]
# Wording replaced in commit messages.
MESSAGE_REPLACEMENTS = {
    "dst-ovh": "the web server",
    "hr-ovh": "another server",
}
# Anything matching these in the public copy (files or messages) stops publishing.
FORBIDDEN = [
    r"57\.129\.\d+\.\d+",
    r"ubuntu@",
    r"dst-ovh",
    r"hr-ovh",
    r"gokartklub|rubsupply|vandeltracking",
    r"@dstchemicals\.com",
    r"DATAFORDELER_API_KEY\s*=\s*['\"]?[A-Za-z0-9]{12,}",
    r"BEGIN (RSA|OPENSSH|EC) PRIVATE KEY",
]
WORK_EMAIL = "mbi@dstchemicals.com"


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        args, cwd=cwd, check=True, text=True, encoding="utf-8",
        capture_output=capture,
    )
    return result.stdout if capture else ""


def filter_repo_command() -> list[str]:
    if shutil.which("git-filter-repo"):
        return ["git-filter-repo"]
    return [sys.executable, "-m", "git_filter_repo"]


def remove_tree(path: Path) -> None:
    """rmtree that also removes git's read-only object files on Windows."""
    def make_writable(function, target, _):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    shutil.rmtree(path, onexc=make_writable)


def build_copy(out: Path, noreply: str, name: str) -> None:
    if out.exists():
        remove_tree(out)
    run("git", "clone", "--no-local", "--quiet", str(ROOT), str(out))
    with tempfile.TemporaryDirectory() as folder:
        mailmap = Path(folder) / "mailmap"
        mailmap.write_text(f"{name} <{noreply}> <{WORK_EMAIL}>\n", encoding="utf-8")
        replacements = Path(folder) / "messages"
        replacements.write_text(
            "".join(f"{old}==>{new}\n" for old, new in MESSAGE_REPLACEMENTS.items()),
            encoding="utf-8",
        )
        command = [
            *filter_repo_command(), "--force", "--invert-paths",
            *[arg for path in PRIVATE_PATHS for arg in ("--path", path)],
            "--mailmap", str(mailmap),
            "--replace-message", str(replacements),
        ]
        run(*command, cwd=out)


def scan(out: Path) -> list[str]:
    """Search every file in every commit, every message and every author."""
    problems = []
    pattern = re.compile("|".join(f"(?:{p})" for p in FORBIDDEN), re.IGNORECASE)
    # This script lists the patterns itself, so its own file is skipped;
    # authors and commit messages are always checked.
    history = run("git", "log", "--all", "-p", "--format=%an <%ae>%n%B", "--", ".",
                  ":(exclude)tools/publish_public.py", cwd=out, capture=True)
    history += run("git", "log", "--all", "--format=%an <%ae> %cn <%ce>%n%B", cwd=out, capture=True)
    for number, line in enumerate(history.splitlines(), 1):
        if pattern.search(line):
            problems.append(f"history line {number}: {line[:120]}")
    for path in PRIVATE_PATHS:
        if run("git", "log", "--all", "--format=%h", "--", path, cwd=out, capture=True).strip():
            problems.append(f"{path} is still in the history")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--noreply", required=True, help="GitHub noreply e-mail for the author")
    parser.add_argument("--name", default="Michael Binger")
    parser.add_argument("--out", type=Path, default=ROOT.parent / f"{ROOT.name}-public")
    parser.add_argument("--remote", help="GitHub remote URL to push to")
    parser.add_argument("--push", action="store_true", help="push after a clean scan")
    args = parser.parse_args()

    status = run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT, capture=True)
    if status.strip():
        print("Note: uncommitted changes in the working repo are not included:\n" + status)
    print(f"Building the public copy in {args.out} …")
    build_copy(args.out, args.noreply, args.name)
    problems = scan(args.out)
    commits = run("git", "rev-list", "--count", "HEAD", cwd=args.out, capture=True).strip()
    if problems:
        print(f"STOP: {len(problems)} internal details found in the public copy:")
        for problem in problems[:20]:
            print("  -", problem)
        return 1
    print(f"Clean: {commits} commits, no internal files, hosts, addresses or secrets found.")
    if args.push:
        if not args.remote:
            print("--push needs --remote")
            return 1
        run("git", "remote", "add", "origin", args.remote, cwd=args.out)
        run("git", "push", "-u", "origin", "HEAD:main", cwd=args.out)
        print(f"Pushed to {args.remote}")
    else:
        print("Not pushed (no --push). Review the copy, then rerun with --remote and --push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
