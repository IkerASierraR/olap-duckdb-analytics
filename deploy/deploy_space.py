"""Publishes the app to a Hugging Face Space (Docker SDK). Used by GitHub Actions.

Env vars: HF_TOKEN (write token) and HF_SPACE_ID (e.g. "user/olap-duckdb-analytics").
"""
import os
import pathlib
import shutil
import tempfile

from huggingface_hub import HfApi

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["app.py", "Dockerfile", "requirements.txt", ".dockerignore", "olap"]

SPACE_README = """---
title: OLAP con DuckDB
emoji: 🦆
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

Dashboard OLAP (slice, dice, roll-up, drill-down, pivot) sobre DuckDB.
Código fuente y pipeline: {repo}
"""


def main() -> None:
    space_id = os.environ["HF_SPACE_ID"]
    repo = os.environ.get("GITHUB_REPO_URL", "")
    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(space_id, repo_type="space", space_sdk="docker", exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp)
        for name in FILES:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, stage / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, stage / name)
        (stage / "README.md").write_text(SPACE_README.format(repo=repo), encoding="utf-8")
        api.upload_folder(
            folder_path=stage,
            repo_id=space_id,
            repo_type="space",
            commit_message=f"Deploy {os.environ.get('GITHUB_SHA', 'local')[:7]} from GitHub Actions",
        )
    print(f"Deployed: https://huggingface.co/spaces/{space_id}")


if __name__ == "__main__":
    main()
