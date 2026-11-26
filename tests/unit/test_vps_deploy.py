import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vps-deploy.sh"
COMPOSE = "docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml"
UP = f"{COMPOSE} up -d --wait --wait-timeout 300"
RESTART = f"{COMPOSE} restart caddy"
DEPLOY_CALLS = [
    "backup",
    f"{COMPOSE} pull backend proxy",
    f"{COMPOSE} run --rm migrate",
    f"{COMPOSE} run --rm import-content",
    UP,
]
HEALTH_URL = "https://x/"
HEALTH_CALL = f"curl -fsS -o /dev/null --max-time 10 {HEALTH_URL}"
SECRET = "s3cr3t-value"
IMAGE_PREFIX = "ghcr.io/mik-en/efd"


@dataclass
class Checkout:
    repo: Path
    env: dict[str, str]
    previous: str
    target: str

    def git(self, *args: str) -> str:
        return git(self.repo, self.env, *args)

    def deploy(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        script = self.repo / "scripts" / "vps-deploy.sh"
        assert script.is_file(), f"Deployment script does not exist: {DEPLOY_SCRIPT}"
        return subprocess.run(
            [str(script), *args],
            cwd=self.repo.parent,
            env=self.env | env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def calls(self) -> list[str]:
        return Path(self.env["CALL_LOG"]).read_text().splitlines()

    def images(self) -> list[str]:
        """BACKEND_IMAGE as seen by each docker call, in order."""
        return Path(self.env["IMAGE_LOG"]).read_text().splitlines()


def git(cwd: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()


def executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def workspace(tmp_path):
    if " " in str(tmp_path):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            yield Path(directory)
    else:
        yield tmp_path


@pytest.fixture
def caddy_changed():
    return False


@pytest.fixture
def checkout(workspace, caddy_changed):
    workspace = workspace.resolve()
    bin_dir = workspace / "bin"
    bin_dir.mkdir()
    call_log = workspace / "calls.log"
    call_log.touch()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DEPLOY_", "FAKE_", "GIT_"))
        and key not in {"BASH_ENV", "ENV_FILE", "SSH_ORIGINAL_COMMAND"}
    }
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Deploy Test",
        GIT_AUTHOR_EMAIL="deploy@example.test",
        GIT_COMMITTER_NAME="Deploy Test",
        GIT_COMMITTER_EMAIL="deploy@example.test",
        LOCK_DIR=str(workspace),
        CALL_LOG=str(call_log),
        IMAGE_LOG=str(workspace / "images.log"),
        FAIL_MARKER=str(workspace / "docker-failed"),
        DEPLOY_HEALTH_DELAY="0",
    )
    executable(
        bin_dir / "docker",
        """printf 'docker %s\n' "$*" >> "$CALL_LOG"
printf '%s\n' "${BACKEND_IMAGE:-}" >> "$IMAGE_LOG"
if [[ -n ${FAKE_DOCKER_FAIL:-} && "$*" == *"$FAKE_DOCKER_FAIL"* ]]; then
    if [[ ${FAKE_DOCKER_FAIL_ONCE:-} != 1 || ! -e "$FAIL_MARKER" ]]; then
        touch "$FAIL_MARKER"
        exit 1
    fi
fi
""",
    )
    executable(
        bin_dir / "curl",
        """printf 'curl %s\n' "$*" >> "$CALL_LOG"
[[ ${FAKE_CURL_FAIL:-} != 1 ]]
""",
    )

    git(workspace, env, "init", "--bare", "--initial-branch=main", "origin.git")
    git(workspace, env, "clone", "origin.git", "author")
    author = workspace / "author"
    (author / "scripts").mkdir()
    (author / "deploy").mkdir()
    if DEPLOY_SCRIPT.is_file():
        shutil.copy2(DEPLOY_SCRIPT, author / "scripts")
    executable(
        author / "scripts" / "vps-job.sh",
        """printf '%s\n' "$*" >> "$CALL_LOG"
[[ ${FAKE_BACKUP_FAIL:-} != 1 ]] || exit 1
printf '2026-01-01T00:00:00Z backup ok: /backups/dump.sql.gz\n'
""",
    )
    (author / ".gitignore").write_text(".env.production\n")
    (author / "deploy" / "compose.production.yaml").write_text("services: {}\n")
    (author / "deploy" / "compose.vps.yaml").write_text("services: {}\n")
    (author / "deploy" / "Caddyfile").write_text("# C1\n")
    (author / "release.txt").write_text("C1\n")
    git(author, env, "add", ".")
    git(author, env, "commit", "-m", "C1")
    git(author, env, "push", "origin", "main")
    previous = git(author, env, "rev-parse", "HEAD")

    git(workspace, env, "clone", "origin.git", "checkout")
    repo = workspace / "checkout"
    (repo / ".env.production").write_text(f"SECRET_SENTINEL={SECRET}\n")
    (author / "release.txt").write_text("C2\n")
    if caddy_changed:
        (author / "deploy" / "Caddyfile").write_text("# C2\n")
    git(author, env, "commit", "-am", "C2")
    git(author, env, "push", "origin", "main")
    target = git(author, env, "rev-parse", "HEAD")
    return Checkout(repo, env, previous, target)


def assert_exit(result, code):
    assert result.returncode == code, (result.stdout, result.stderr)


def assert_untouched(checkout, result, code=2, head=None):
    assert_exit(result, code)
    assert checkout.git("rev-parse", "HEAD") == (head or checkout.previous)
    assert checkout.calls() == []


def assert_success(checkout, result, calls):
    assert_exit(result, 0)
    assert checkout.git("rev-parse", "HEAD") == checkout.target
    assert checkout.git("branch", "--show-current") == "main"
    assert checkout.calls() == calls
    assert result.stdout.rstrip().endswith(f"deploy ok: {checkout.target}")
    assert SECRET not in result.stdout + result.stderr


def assert_rollback(checkout, result, calls):
    assert_exit(result, 1)
    assert checkout.git("rev-parse", "HEAD") == checkout.previous
    assert checkout.calls() == calls
    assert f"deploy rolled back to {checkout.previous}" in result.stdout
    assert re.search(r"schema[^\n]*not reverted", result.stdout, re.IGNORECASE)
    assert "/backups/dump.sql.gz" in result.stdout
    assert SECRET not in result.stdout + result.stderr


def test_deploys_target_on_main(checkout):
    assert_success(checkout, checkout.deploy(checkout.target), DEPLOY_CALLS)


@pytest.mark.parametrize("caddy_changed", [True])
def test_restarts_caddy_after_up_when_config_changed(checkout):
    assert_success(checkout, checkout.deploy(checkout.target), [*DEPLOY_CALLS, RESTART])


def test_deploys_images_tagged_with_target_and_records_it(checkout):
    assert_success(checkout, checkout.deploy(checkout.target), DEPLOY_CALLS)
    assert checkout.images() == [f"{IMAGE_PREFIX}-backend:{checkout.target}"] * 4
    assert (checkout.repo / ".deployed-sha").read_text().strip() == checkout.target


def test_failed_deploy_does_not_record_target(checkout):
    checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="run --rm migrate")
    assert not (checkout.repo / ".deployed-sha").exists()


def test_rollback_restores_previously_deployed_images(checkout):
    (checkout.repo / ".deployed-sha").write_text(f"{checkout.previous}\n")
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="run --rm migrate")
    assert_rollback(checkout, result, [*DEPLOY_CALLS[:3], UP])
    assert checkout.images()[-1] == f"{IMAGE_PREFIX}-backend:{checkout.previous}"
    assert (checkout.repo / ".deployed-sha").read_text().strip() == checkout.previous


def test_first_deploy_rollback_falls_back_to_local_images(checkout):
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="run --rm migrate")
    assert_rollback(checkout, result, [*DEPLOY_CALLS[:3], UP])
    assert checkout.images()[-1] == ""


def test_leaves_current_commit_alone(checkout):
    result = checkout.deploy(checkout.previous)
    assert_untouched(checkout, result, code=0)
    assert f"already at {checkout.previous}" in result.stdout


@pytest.mark.parametrize(
    "sha_format",
    ["{:.7}", "{!s}0", "{}; rm -rf /", "uppercase"],
    ids=["short", "too-long", "shell-command", "uppercase"],
)
def test_rejects_invalid_sha(checkout, workspace, sha_format):
    if sha_format == "{}; rm -rf /":
        executable(workspace / "bin" / "rm", """printf 'rm %s\n' "$*" >> "$CALL_LOG"\nexit 1\n""")
    sha = (
        checkout.target.upper() if sha_format == "uppercase" else sha_format.format(checkout.target)
    )
    assert_untouched(checkout, checkout.deploy(sha))


def test_accepts_ssh_forced_command(checkout):
    result = checkout.deploy(SSH_ORIGINAL_COMMAND=f"deploy {checkout.target}")
    assert_success(checkout, result, DEPLOY_CALLS)


@pytest.mark.parametrize(
    "command",
    ["deploy {}; id", "bash", "deploy  {}", "", None],
    ids=["shell-command", "wrong-command", "extra-space", "empty", "unset"],
)
def test_rejects_invalid_ssh_forced_command(checkout, workspace, command):
    if command == "deploy {}; id":
        executable(workspace / "bin" / "id", """printf 'id %s\n' "$*" >> "$CALL_LOG"\nexit 1\n""")
    env = {} if command is None else {"SSH_ORIGINAL_COMMAND": command.format(checkout.target)}
    assert_untouched(checkout, checkout.deploy(**env))


def test_rejects_commit_outside_remote_main(checkout):
    checkout.git("switch", "-c", "local-only")
    checkout.git("commit", "--allow-empty", "-m", "Local-only commit")
    local_commit = checkout.git("rev-parse", "HEAD")
    checkout.git("switch", "main")
    assert_untouched(checkout, checkout.deploy(local_commit))


def test_rejects_downgrade(checkout):
    checkout.git("pull", "--ff-only", "origin", "main")
    assert_untouched(checkout, checkout.deploy(checkout.previous), head=checkout.target)


def test_rejects_modified_tracked_file(checkout):
    tracked_file = checkout.repo / "release.txt"
    tracked_file.write_text("local edit\n")
    assert_untouched(checkout, checkout.deploy(checkout.target))
    assert tracked_file.read_text() == "local edit\n"


def test_requires_env_file(checkout):
    (checkout.repo / ".env.production").unlink()
    assert_untouched(checkout, checkout.deploy(checkout.target))


def test_backup_failure_prevents_checkout(checkout):
    result = checkout.deploy(checkout.target, FAKE_BACKUP_FAIL="1")
    assert_exit(result, 1)
    assert checkout.git("rev-parse", "HEAD") == checkout.previous
    assert checkout.calls() == ["backup"]


def test_migration_failure_rolls_back_code(checkout):
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="run --rm migrate")
    assert_rollback(checkout, result, [*DEPLOY_CALLS[:3], UP])


def test_pull_failure_rolls_back_code(checkout):
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="pull", FAKE_DOCKER_FAIL_ONCE="1")
    assert_rollback(checkout, result, [*DEPLOY_CALLS[:2], UP])


@pytest.mark.parametrize("caddy_changed", [True])
def test_up_failure_restarts_caddy_during_rollback(checkout):
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="up -d", FAKE_DOCKER_FAIL_ONCE="1")
    assert_rollback(checkout, result, [*DEPLOY_CALLS, UP, RESTART])


def test_health_failure_retries_five_times_then_rolls_back(checkout):
    result = checkout.deploy(checkout.target, DEPLOY_HEALTH_URL=HEALTH_URL, FAKE_CURL_FAIL="1")
    assert_rollback(checkout, result, [*DEPLOY_CALLS, *([HEALTH_CALL] * 5), UP])


def test_successful_health_check_runs_once(checkout):
    result = checkout.deploy(checkout.target, DEPLOY_HEALTH_URL=HEALTH_URL)
    assert_success(checkout, result, [*DEPLOY_CALLS, HEALTH_CALL])


def test_rollback_failure_requires_manual_action(checkout):
    result = checkout.deploy(checkout.target, FAKE_DOCKER_FAIL="up -d")
    assert_exit(result, 4)
    assert checkout.calls() == [*DEPLOY_CALLS, UP]
    assert "manual action required" in result.stderr.lower()


@pytest.mark.skipif(shutil.which("flock") is None, reason="flock is unavailable")
def test_rejects_deploy_when_lock_is_held(checkout):
    lock_path = Path(checkout.env["LOCK_DIR"]) / "efd-deploy.lock"
    with lock_path.open("a") as lock:
        subprocess.run(
            ["flock", "-n", str(lock.fileno())], pass_fds=(lock.fileno(),), check=True, timeout=5
        )
        assert_untouched(checkout, checkout.deploy(checkout.target), code=3)
