"""Sync LFS/moefIFSCivil/pdfs with the Hugging Face dataset.

Usage: sync_hf.py pull|push
"""

import os
import sys

from huggingface_hub import HfApi, snapshot_download

from common import DEFAULT_HF_REPO_ID, LFS_DIR, link_pdf, load_env, pdf_path, read_records

ALLOW_PATTERNS = ["pdfs/*.pdf"]


def pull(repo_id, token):
    print(f"*** Downloading {repo_id} -> {LFS_DIR}")
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        local_dir=LFS_DIR,
        allow_patterns=ALLOW_PATTERNS,
        token=token,
    )
    downloads = read_records("downloads")
    missing = []
    for year in sorted(downloads):
        if pdf_path(year).exists():
            link_pdf(year)
        else:
            missing.append(year)
    print(f"*** Linked {len(downloads) - len(missing)} PDFs into input/documents")
    if missing:
        print(f"*** WARNING not on HF / not local: {missing}")


def push(repo_id, token):
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    print(f"*** Uploading {LFS_DIR}/pdfs -> {repo_id}")
    commit = api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=LFS_DIR,
        allow_patterns=ALLOW_PATTERNS,
        commit_message="sync IFS civil list pdfs",
    )
    print(f"*** Done: {commit}")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("pull", "push"):
        raise SystemExit(f"Usage: {sys.argv[0]} pull|push")
    load_env()
    repo_id = os.environ.get("HF_REPO_ID", "").strip() or DEFAULT_HF_REPO_ID
    token = os.environ.get("HF_TOKEN", "").strip() or None
    if sys.argv[1] == "push" and not token:
        raise SystemExit("Missing environment variable: HF_TOKEN (set it in .env)")
    pull(repo_id, token) if sys.argv[1] == "pull" else push(repo_id, token)


if __name__ == "__main__":
    main()
