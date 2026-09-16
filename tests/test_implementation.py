import pytest

from agent_platform.implementation import changed_paths, validate_patch
from agent_platform.sdlc_agents import ImplementationPatch

PATCH = """diff --git a/server/routers.ts b/server/routers.ts
index 1111111..2222222 100644
--- a/server/routers.ts
+++ b/server/routers.ts
@@ -1 +1 @@
-old
+new
"""


def test_patch_accepts_an_explicitly_allowed_existing_file() -> None:
    assert changed_paths(PATCH) == {"server/routers.ts"}
    assert validate_patch(PATCH, ["server/routers.ts"]) == ["server/routers.ts"]


def test_patch_rejects_paths_outside_the_approved_allowlist() -> None:
    with pytest.raises(ValueError, match="неразрешённый файл"):
        validate_patch(PATCH, ["client/src/pages/Counterparties.tsx"])


def test_patch_rejects_workflow_changes_even_if_listed() -> None:
    workflow_patch = PATCH.replace("server/routers.ts", ".github/workflows/ci.yml")

    with pytest.raises(ValueError, match="неразрешённый файл"):
        validate_patch(workflow_patch, [".github/workflows/ci.yml"])


def test_patch_rejects_file_renames() -> None:
    renamed_patch = PATCH.replace(
        "diff --git a/server/routers.ts b/server/routers.ts",
        "diff --git a/server/routers.ts b/server/new-routers.ts",
    )

    with pytest.raises(ValueError, match="переименования"):
        changed_paths(renamed_patch)


def test_patch_rejects_dependency_manifests_and_mode_changes() -> None:
    manifest_patch = PATCH.replace("server/routers.ts", "package.json")

    with pytest.raises(ValueError, match="неразрешённый файл"):
        validate_patch(manifest_patch, ["package.json"])

    with pytest.raises(ValueError, match="тип, имя или режим"):
        changed_paths(
            PATCH.replace("index 1111111..2222222 100644", "old mode 100644\nnew mode 100755")
        )


def test_implementation_patch_requires_an_actual_unified_diff() -> None:
    with pytest.raises(ValueError, match="должен начинаться"):
        ImplementationPatch(summary="Изменений нет", unified_diff=" ")
