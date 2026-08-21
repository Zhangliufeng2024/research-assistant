"""Core utilities for research assistant."""

import os
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .constants import DATA_EXTENSIONS, IMAGE_EXTENSIONS, MANUSCRIPT_EXTENSIONS, SOURCE_EXTENSIONS

_dotenv_loaded = False


def safe_resolve(path: Path, sandbox: Path) -> Path:
    """Resolve *path* and verify it stays within *sandbox*.

    Raises ``ValueError`` if the resolved path escapes the sandbox.
    Both *path* and *sandbox* are resolved before comparison so symlinks
    and ``..`` segments cannot escape.
    """
    resolved = path.resolve()
    sandbox_resolved = sandbox.resolve()
    if not (resolved == sandbox_resolved or str(resolved).startswith(str(sandbox_resolved) + os.sep)):
        raise ValueError(
            f"Path escapes sandbox: {resolved} is not inside {sandbox_resolved}"
        )
    return resolved


def ensure_dotenv_loaded() -> None:
    """Load .env once on first call. No-op on subsequent calls."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


SYNC_MANIFEST_NAME = ".sync_manifest.json"


def _file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_tree(source_dir: Path, dest_dir: Path) -> dict:
    """Incrementally mirror *source_dir* into *dest_dir*.

    Fixes the long-standing bug where ``copytree(dirs_exist_ok=True)`` left
    stale skill copies on user machines forever. Rules:

    - new/changed tracked files are copied;
    - previously-synced files that vanished from the source are deleted;
    - **existing untracked files are never touched** — a WRITER.md the user
      edited locally stays theirs until they delete it;
    - a ``.sync_manifest.json`` of content hashes records what we shipped.

    Returns ``{"updated": int, "removed": int}``.
    """
    import json as _json

    manifest_path = dest_dir / SYNC_MANIFEST_NAME
    old: dict[str, str] = {}
    if manifest_path.exists():
        try:
            old = _json.loads(manifest_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            old = {}

    source_files: dict[str, str] = {}
    for p in sorted(source_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(source_dir).as_posix()
            if rel == SYNC_MANIFEST_NAME or "__pycache__" in p.parts:
                continue
            try:
                source_files[rel] = _file_hash(p)
            except OSError:
                continue

    dest_dir.mkdir(parents=True, exist_ok=True)
    updated = removed = 0

    for rel, digest in source_files.items():
        target = dest_dir / rel
        if old.get(rel) == digest and target.exists():
            continue                      # unchanged since last sync
        if target.exists() and rel not in old:
            continue                      # user-created file — hands off
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / rel, target)
        updated += 1

    for rel in list(old.keys()):
        if rel not in source_files:
            target = dest_dir / rel
            try:
                if target.exists():
                    target.unlink()
                    removed += 1
            except OSError:
                pass

    try:
        manifest_path.write_text(
            _json.dumps(source_files, indent=0, sort_keys=True), encoding="utf-8",
        )
    except OSError:
        pass
    return {"updated": updated, "removed": removed}


def setup_claude_skills(package_dir: Path, work_dir: Path) -> None:
    """
    Set up Claude skills and WRITER.md by syncing .claude/ from package to
    the working directory (incremental, version-aware).

    Args:
        package_dir: Package installation directory containing .claude/
        work_dir: User's working directory where .claude/ should be synced
    """
    source_claude = package_dir / ".claude"
    dest_claude = work_dir / ".claude"

    if source_claude.exists():
        try:
            report = sync_tree(source_claude, dest_claude)
            if report["updated"] or report["removed"]:
                print(
                    f"[research-assistant] Skills synced "
                    f"({report['updated']} updated, {report['removed']} removed)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"[research-assistant] Warning: Could not sync skills to {dest_claude}: {e}",
                file=sys.stderr,
            )


def get_api_key(api_key: str | None = None) -> str:
    """Get the LLM API key.

    Checks: explicit param -> LLM_API_KEY env.

    Raises:
        ValueError: If no API key is found.
    """
    if api_key:
        return api_key

    ensure_dotenv_loaded()
    env_key = os.getenv("LLM_API_KEY")
    if not env_key:
        raise ValueError(
            "No API key found. Set LLM_API_KEY in .env"
        )
    return env_key


def load_system_instructions(work_dir: Path) -> str:
    """
    Load system instructions from .claude/WRITER.md in the working directory.

    Args:
        work_dir: Working directory containing .claude/WRITER.md.

    Returns:
        System instructions string.
    """
    instructions_file = work_dir / ".claude" / "WRITER.md"

    if instructions_file.exists():
        with open(instructions_file, encoding='utf-8') as f:
            return f.read()
    else:
        # Fallback if WRITER.md doesn't exist
        return (
            "You are a scientific writing assistant. Follow best practices for "
            "scientific communication and always present a plan before execution."
        )


def ensure_output_folder(cwd: Path, custom_dir: str | None = None) -> Path:
    """
    Ensure the writing_outputs folder exists.

    Args:
        cwd: Current working directory (project root).
        custom_dir: Optional custom output directory path.

    Returns:
        Path to the output folder.
    """
    if custom_dir:
        output_folder = Path(custom_dir).resolve()
    else:
        output_folder = cwd / "writing_outputs"

    output_folder.mkdir(exist_ok=True, parents=True)
    return output_folder


def get_image_extensions() -> frozenset[str]:
    """Return a set of common image file extensions."""
    return IMAGE_EXTENSIONS


def get_manuscript_extensions() -> frozenset[str]:
    """Return a set of manuscript file extensions that should go to drafts/ folder."""
    return MANUSCRIPT_EXTENSIONS


def get_source_extensions() -> frozenset[str]:
    """Return a set of source/context file extensions that should go to sources/ folder."""
    return SOURCE_EXTENSIONS


def get_data_extensions() -> frozenset[str]:
    """Return a set of data file extensions that should go to data/ folder."""
    return DATA_EXTENSIONS


def get_data_files(cwd: Path, data_files: list[str] | None = None) -> list[Path]:
    """
    Get data files either from provided list or from data folder.

    Args:
        cwd: Current working directory (project root).
        data_files: Optional list of file paths. If not provided, reads from data/ folder.

    Returns:
        List of Path objects for data files.
    """
    if data_files:
        return [Path(f).resolve() for f in data_files]

    data_folder = cwd / "data"
    if not data_folder.exists():
        return []

    files = []
    for file_path in data_folder.iterdir():
        if file_path.is_file():
            files.append(file_path)

    return files


def extract_images_from_docx(docx_path: Path, figures_output: Path) -> list[dict[str, Any]]:
    """
    Extract all images from a .docx file and copy them to the figures folder.

    A .docx file is a ZIP archive containing images in the word/media/ directory.
    This function extracts all image files and copies them to the specified output directory.

    Args:
        docx_path: Path to the .docx file.
        figures_output: Path to the figures output directory.

    Returns:
        List of dictionaries containing information about extracted images.
        Each dict has 'name', 'path', and 'source_docx' keys.
    """
    extracted_images = []
    image_extensions = get_image_extensions()

    try:
        with zipfile.ZipFile(docx_path, 'r') as zip_ref:
            # List all files in the archive
            all_files = zip_ref.namelist()

            # Filter for files in word/media/ directory that are images
            media_files = [f for f in all_files if f.startswith('word/media/')]

            for media_file in media_files:
                # Get the filename from the path
                file_name = Path(media_file).name
                file_ext = Path(media_file).suffix.lower()

                # Only extract if it's an image file
                if file_ext in image_extensions:
                    # Extract to figures folder
                    output_path = figures_output / file_name

                    # Read the file from the zip and write it to the output
                    with zip_ref.open(media_file) as source:
                        with open(output_path, 'wb') as target:
                            target.write(source.read())

                    extracted_images.append({
                        'name': file_name,
                        'path': str(output_path),
                        'source_docx': docx_path.name
                    })

    except (zipfile.BadZipFile, RuntimeError, KeyError):
        print(f"Warning: {docx_path.name} is not a valid .docx file (ZIP archive)")
    except Exception as e:
        print(f"Warning: Could not extract images from {docx_path.name}: {str(e)}")

    return extracted_images


def process_data_files(
    cwd: Path,
    data_files: list[Path],
    paper_output_path: str,
    delete_originals: bool = False,
) -> dict[str, Any] | None:
    """
    Process data files by copying them to the paper output folder.
    Manuscript files (.tex) go to drafts/,
    Source files (.md, .docx, .pdf) go to sources/,
    images go to figures/,
    data files (csv, json, etc.) go to data/,
    everything else goes to sources/.

    Args:
        cwd: Current working directory (project root).
        data_files: List of file paths to process.
        paper_output_path: Path to the paper output directory.
        delete_originals: Whether to delete original files after copying.

    Returns:
        Dictionary with information about processed files, or None if no files.
    """
    if not data_files:
        return None

    paper_output = Path(paper_output_path)
    data_output = paper_output / "data"
    figures_output = paper_output / "figures"
    drafts_output = paper_output / "drafts"
    sources_output = paper_output / "sources"

    # Ensure output directories exist
    data_output.mkdir(parents=True, exist_ok=True)
    figures_output.mkdir(parents=True, exist_ok=True)
    drafts_output.mkdir(parents=True, exist_ok=True)
    sources_output.mkdir(parents=True, exist_ok=True)

    image_extensions = get_image_extensions()
    manuscript_extensions = get_manuscript_extensions()
    get_source_extensions()
    data_extensions = get_data_extensions()

    processed_info = {
        'data_files': [],
        'image_files': [],
        'manuscript_files': [],
        'source_files': [],
        'all_files': []
    }

    for file_path in data_files:
        file_ext = file_path.suffix.lower()
        file_name = file_path.name

        # Determine destination based on file type
        # Priority: manuscript (.tex) → drafts/, images → figures/,
        # data files → data/, source files → sources/, everything else → sources/

        if file_ext in manuscript_extensions:
            # CRITICAL: Only .tex files go to drafts/ folder for editing workflow
            destination = drafts_output / file_name
            file_type = 'manuscript'
            processed_info['manuscript_files'].append({
                'name': file_name,
                'path': str(destination),
                'original': str(file_path),
                'extension': file_ext
            })
        elif file_ext in image_extensions:
            destination = figures_output / file_name
            file_type = 'image'
            processed_info['image_files'].append({
                'name': file_name,
                'path': str(destination),
                'original': str(file_path)
            })
        elif file_ext in data_extensions:
            destination = data_output / file_name
            file_type = 'data'
            processed_info['data_files'].append({
                'name': file_name,
                'path': str(destination),
                'original': str(file_path)
            })
        else:
            # Source files (.md, .docx, .pdf) and everything else go to sources/
            destination = sources_output / file_name
            file_type = 'source'
            processed_info['source_files'].append({
                'name': file_name,
                'path': str(destination),
                'original': str(file_path),
                'extension': file_ext
            })

        # Copy the file
        try:
            shutil.copy2(file_path, destination)
            processed_info['all_files'].append({
                'name': file_name,
                'type': file_type,
                'destination': str(destination),
                'original': str(file_path),  # track original for later deletion
            })

            # If it's a .docx file, extract images to figures folder
            if file_ext == '.docx':
                extracted_images = extract_images_from_docx(file_path, figures_output)
                if extracted_images:
                    for img_info in extracted_images:
                        processed_info['image_files'].append(img_info)

        except Exception as e:
            print(f"Warning: Could not process {file_name}: {str(e)}")

    # Only delete originals after ALL files have been successfully copied.
    # This prevents data loss if a later copy step fails.
    if delete_originals and processed_info['all_files']:
        for file_record in processed_info['all_files']:
            original = Path(file_record['original'])
            try:
                if original.exists():
                    original.unlink()
            except Exception as e:
                print(f"Warning: Could not delete original file {original.name}: {e}")

    return processed_info


def create_data_context_message(processed_info: dict[str, Any] | None) -> str:
    """
    Create a context message about available data files.

    Args:
        processed_info: Dictionary with processed file information.

    Returns:
        Context message string.
    """
    if not processed_info or not processed_info['all_files']:
        return ""

    context_parts = ["\n[DATA FILES AVAILABLE]"]

    # CRITICAL: If manuscript files (.tex) are present, this is an EDITING task
    if processed_info.get('manuscript_files'):
        context_parts.append("\n⚠️  EDITING MODE - Manuscript files (.tex) detected!")
        context_parts.append("\nManuscript files (in drafts/ folder for editing):")
        for file_info in processed_info['manuscript_files']:
            context_parts.append(f"  - {file_info['name']} ({file_info['extension']}): {file_info['path']}")
        context_parts.append("\n🔧 TASK: This is an EDITING task, not creating from scratch.")
        context_parts.append("   → Read the existing manuscript from drafts/")
        context_parts.append("   → Apply the requested changes/improvements")
        context_parts.append("   → Create new version following version numbering protocol")
        context_parts.append("   → Document changes in revision_notes.md")

    if processed_info.get('source_files'):
        context_parts.append("\nSource/Context files (in sources/ folder for reference):")
        for file_info in processed_info['source_files']:
            ext = file_info.get('extension', '')
            context_parts.append(f"  - {file_info['name']} ({ext}): {file_info['path']}")
        context_parts.append("\nNote: These files are available as reference/context material.")

    if processed_info.get('data_files'):
        context_parts.append("\nData files (in data/ folder):")
        for file_info in processed_info['data_files']:
            context_parts.append(f"  - {file_info['name']}: {file_info['path']}")

    if processed_info.get('image_files'):
        # Separate images by source (direct vs extracted from docx)
        direct_images = [img for img in processed_info['image_files'] if 'source_docx' not in img]
        extracted_images = [img for img in processed_info['image_files'] if 'source_docx' in img]

        context_parts.append("\nImage files (in figures/ folder):")

        if direct_images:
            context_parts.append("  Directly provided:")
            for file_info in direct_images:
                context_parts.append(f"    - {file_info['name']}: {file_info['path']}")

        if extracted_images:
            images_by_docx: dict[str, list] = defaultdict(list)
            for img in extracted_images:
                images_by_docx[img['source_docx']].append(img)

            context_parts.append("  Extracted from .docx files:")
            for docx_name, images in images_by_docx.items():
                img_names = ', '.join([img['name'] for img in images])
                context_parts.append(f"    - From {docx_name}: {img_names}")

        context_parts.append("\nNote: These images can be referenced as figures in the paper.")

    context_parts.append("[END DATA FILES]\n")

    return "\n".join(context_parts)

