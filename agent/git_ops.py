"""
agent/git_ops.py

Git and GitHub automation for shipping autonomous SRE bug fixes.
Enforces explicit touched-files staging to prevent accidental contamination
of uncommitted developer work.
"""

from __future__ import annotations
import logging
from pathlib import Path
import subprocess
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


class GitOperations:
    """
    Handles git branching, surgical staging of touched files, conventional commits,
    and Pull Request creation.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git"] + args,
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def create_branch(self, branch_name: str) -> bool:
        """
        Creates and checks out a new git branch.
        """
        res = self._run_git(["checkout", "-b", branch_name])
        if res.returncode != 0:
            # If branch already exists, switch to it
            res = self._run_git(["checkout", branch_name])
        return res.returncode == 0

    def commit_touched_files(self, touched_files: Iterable[str], commit_message: str) -> bool:
        """
        Stages ONLY the exact files modified by the agent.
        Protects the developer's uncommitted work from accidental commits.
        """
        files_to_stage = list(touched_files)
        if not files_to_stage:
            logger.warning("No touched files to commit.")
            return False

        # 1. Stage only the explicitly touched files
        for rel_path in files_to_stage:
            target_path = self.workspace_root / rel_path
            if target_path.exists():
                add_res = self._run_git(["add", rel_path])
                if add_res.returncode != 0:
                    logger.warning("Failed to stage %s: %s", rel_path, add_res.stderr)

        # 2. Verify something is actually staged
        diff_res = self._run_git(["diff", "--cached", "--quiet"])
        if diff_res.returncode == 0:
            # Nothing staged (diff is empty)
            logger.info("Nothing staged to commit.")
            return False

        # 3. Commit staged changes
        commit_res = self._run_git(["commit", "-m", commit_message])
        return commit_res.returncode == 0

    def push_branch(self, branch_name: str, remote: str = "origin") -> bool:
        """
        Pushes the remediation branch to the remote repository.
        """
        res = self._run_git(["push", "-u", remote, branch_name])
        return res.returncode == 0

    def create_pull_request(
        self,
        title: str,
        body: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> Dict[str, Any]:
        """
        Opens a GitHub Pull Request via the `gh` CLI or falls back to an offline artifact.
        """
        # 1. Try GitHub CLI (gh)
        try:
            gh_res = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--head",
                    branch_name,
                    "--base",
                    base_branch,
                ],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if gh_res.returncode == 0:
                pr_url = gh_res.stdout.strip()
                return {
                    "success": True,
                    "mode": "gh_cli",
                    "pr_url": pr_url,
                    "branch": branch_name,
                }
        except Exception as e:
            logger.info("GitHub CLI (gh) unavailable or failed: %s", e)

        # 2. Offline / local fallback: persist PR summary to disk
        artifact_dir = self.workspace_root / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        summary_file = artifact_dir / f"pr_{branch_name.replace('/', '_')}.md"

        content = f"# Pull Request: {title}\n\n**Branch:** `{branch_name}` -> `{base_branch}`\n\n{body}\n"
        summary_file.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "mode": "offline_summary",
            "branch": branch_name,
            "summary_file": str(summary_file),
            "instructions": f"Push with 'git push origin {branch_name}' and create PR from {summary_file}.",
        }
