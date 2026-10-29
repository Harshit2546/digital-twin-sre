"""
Tests for GitOperations: branch creation, touched-files isolation, and PR generation.
"""

from pathlib import Path
import subprocess
import pytest
from agent.git_ops import GitOperations
from agent.tools import AgentTools


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Creates a temporary git repository with initial commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "sre-agent@example.com"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "SRE Agent"], cwd=str(tmp_path), check=True)

    init_file = tmp_path / "README.md"
    init_file.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), check=True)

    return tmp_path


def test_create_branch(temp_git_repo: Path):
    git_ops = GitOperations(temp_git_repo)
    success = git_ops.create_branch("fix/test-branch")
    assert success is True

    # Verify branch name
    res = subprocess.run(["git", "branch", "--show-current"], cwd=str(temp_git_repo), capture_output=True, text=True)
    assert res.stdout.strip() == "fix/test-branch"


def test_commit_touched_files_isolates_user_work(temp_git_repo: Path):
    """
    Critical test:
    User has uncommitted work (draft.txt).
    Agent modifies fix.py.
    GitOperations must commit ONLY fix.py and leave draft.txt untouched.
    """
    # 1. User's uncommitted work
    user_file = temp_git_repo / "draft.txt"
    user_file.write_text("User secret personal notes\n")

    # 2. Agent's fix file
    agent_file = temp_git_repo / "fix.py"
    agent_file.write_text("PORT = 8080\n")

    git_ops = GitOperations(temp_git_repo)

    # Commit ONLY fix.py
    committed = git_ops.commit_touched_files(
        touched_files={"fix.py"},
        commit_message="fix(sre): update PORT config",
    )
    assert committed is True

    # 3. Check git log: fix.py must be committed
    log_res = subprocess.run(
        ["git", "show", "--name-only", "HEAD"],
        cwd=str(temp_git_repo),
        capture_output=True,
        text=True,
    )
    assert "fix.py" in log_res.stdout
    assert "draft.txt" not in log_res.stdout

    # 4. Check git status: draft.txt must still be uncommitted / untracked!
    status_res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(temp_git_repo),
        capture_output=True,
        text=True,
    )
    assert "?? draft.txt" in status_res.stdout


def test_agent_tools_touched_files_integration(temp_git_repo: Path):
    """
    Verifies that AgentTools records touched_files when edit_file or write_file is called.
    """
    tools = AgentTools(workspace_root=temp_git_repo)
    tools.write_file("service.py", "PORT = 5000\n")

    assert "service.py" in tools.touched_files

    tools.edit_file("service.py", "PORT = 5000", "PORT = 6000")
    assert "service.py" in tools.touched_files


def test_create_pull_request_offline(temp_git_repo: Path):
    git_ops = GitOperations(temp_git_repo)
    res = git_ops.create_pull_request(
        title="fix(sre): resolve port mismatch",
        body="Automated SRE remediation PR.",
        branch_name="fix/port-mismatch",
    )

    assert res["success"] is True
    assert "summary_file" in res or "pr_url" in res
    if "summary_file" in res:
        summary_path = Path(res["summary_file"])
        assert summary_path.exists()
        assert "fix(sre): resolve port mismatch" in summary_path.read_text()
