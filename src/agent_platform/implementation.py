"""Safe application of one LLM-generated patch in an isolated GitHub Actions workspace."""

import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from agent_platform.sdlc_agents import ImplementationPatch

DIFF_HEADER = re.compile(r"^diff --git a/(?P<before>.+) b/(?P<after>.+)$", re.MULTILINE)
PROHIBITED_PREFIXES = (".github/", ".env", ".git/", "node_modules/")
PROHIBITED_PATHS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
UNSAFE_DIFF_MARKERS = (
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "rename from ",
    "rename to ",
    "Binary files ",
)


def changed_paths(unified_diff: str) -> set[str]:
    """Extract modified paths and reject creation, deletion and malformed diffs."""
    if any(marker in unified_diff for marker in UNSAFE_DIFF_MARKERS):
        raise ValueError("Агенту запрещено менять тип, имя или режим файла.")
    paths: set[str] = set()
    for match in DIFF_HEADER.finditer(unified_diff):
        before, after = match.group("before"), match.group("after")
        if before != after:
            raise ValueError("Агенту запрещены переименования, создания и удаления файлов.")
        paths.add(before)
    if not paths:
        raise ValueError("Агент должен вернуть unified diff хотя бы для одного файла.")
    return paths


def validate_patch(unified_diff: str, allowed_paths: list[str]) -> list[str]:
    """Allow a patch only for explicitly approved, existing repository paths."""
    allowed = set(allowed_paths)
    paths = changed_paths(unified_diff)
    for path in paths:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Diff содержит небезопасный путь.")
        if (
            path.startswith(PROHIBITED_PREFIXES)
            or path in PROHIBITED_PATHS
            or path not in allowed
        ):
            raise ValueError(f"Diff меняет неразрешённый файл: {path}")
    return sorted(paths)


class FeatureBranchWorkspace:
    """Perform only predetermined Git operations in the ephemeral Actions checkout."""

    def __init__(self, project_root: str) -> None:
        self.root = Path(project_root).resolve()

    def checkout(self, branch: str) -> None:
        self._run(["git", "fetch", "origin", branch])
        self._run(["git", "switch", "--create", branch, "--track", f"origin/{branch}"])

    def apply_patch(self, patch: ImplementationPatch, allowed_paths: list[str]) -> list[str]:
        paths = validate_patch(patch.unified_diff, allowed_paths)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".diff", dir=self.root, delete=False
        ) as patch_file:
            patch_file.write(patch.unified_diff)
            patch_path = Path(patch_file.name)
        try:
            self._run(["git", "apply", "--check", "--whitespace=error", str(patch_path)])
            self._run(["git", "apply", "--whitespace=error", str(patch_path)])
        finally:
            patch_path.unlink(missing_ok=True)
        return paths

    def verify_commit_and_push(self, *, paths: list[str], feature_id: str) -> str:
        self._run(["pnpm", "check"])
        self._run(["pnpm", "test"])
        self._run(["git", "add", "--", *paths])
        changed = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=self.root, check=False
        ).returncode
        if changed == 0:
            raise RuntimeError("После применения diff нет изменений для коммита.")
        if changed != 1:
            raise RuntimeError("Не удалось проверить staged-изменения.")
        self._run(["git", "config", "user.name", "sdlc-implementation-agent[bot]"])
        self._run(
            [
                "git",
                "config",
                "user.email",
                "41898282+sdlc-implementation-agent[bot]@users.noreply.github.com",
            ]
        )
        self._run(["git", "commit", "-m", f"Реализовать {feature_id} по утверждённой спецификации"])
        self._run(["git", "push", "origin", "HEAD"])
        return "pnpm check; pnpm test"

    def _run(self, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            cwd=self.root,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Команда проверки ветки завершилась с ошибкой: {' '.join(command)}\n"
                f"{completed.stderr[-2_000:]}"
            )
