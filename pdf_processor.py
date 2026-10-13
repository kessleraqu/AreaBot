from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from openai import OpenAI
import openai as openai_package

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional but recommended
    load_dotenv = None

from state_utils import VectorStoreState

# Default folder layout relative to this script.
PDF_ROOT = Path("pdf")
NOT_EXTRACTED_DIR = PDF_ROOT / "NotExtracted"
EXTRACTED_DIR = PDF_ROOT / "Extracted"
STATE_FILE = Path("vector_store_state.json")
DEFAULT_VECTOR_STORE_NAME = "AreaBot2 HVAC Library"
MAX_FILES_PER_BATCH = 10


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def ensure_vector_store(client: OpenAI, *, name: str, state: VectorStoreState) -> str:
    vector_store_id = state.get_vector_store_id()
    if vector_store_id:
        logging.debug("Using existing vector store: %s", vector_store_id)
        return vector_store_id

    logging.info("Creating vector store '%s'", name)
    try:
        vector_store = client.vector_stores.create(name=name)
    except AttributeError as exc:
        version = getattr(openai_package, "__version__", "unknown")
        raise RuntimeError(
            "Installed openai package (version %s) does not provide the vector store API. "
            "Install a 1.x release that supports vector stores (e.g. 'pip install \"openai<2.0\"')."
            % version
        ) from exc
    state.set_vector_store_id(vector_store.id)
    logging.info("Created vector store with id %s", vector_store.id)
    return vector_store.id


def chunked(iterable: Iterable[Path], size: int) -> Iterable[List[Path]]:
    chunk: List[Path] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def upload_batch(
    client: OpenAI,
    vector_store_id: str,
    batch: List[Path],
    *,
    state: Optional[VectorStoreState] = None,
) -> Tuple[bool, List[Tuple[Path, object]]]:
    uploads: List[Tuple[Path, object]] = []
    for file_path in batch:
        logging.info("Uploading %s", file_path.name)
        try:
            with file_path.open("rb") as stream:
                result = client.vector_stores.files.upload_and_poll(
                    vector_store_id=vector_store_id,
                    file=stream,
                )
        except AttributeError as exc:
            version = getattr(openai_package, "__version__", "unknown")
            raise RuntimeError(
                "Installed openai package (version %s) does not provide file upload helpers for vector stores. "
                "Install a 1.x release that supports vector stores (e.g. 'pip install \"openai<2.0\"')."
                % version
            ) from exc

        status = getattr(result, "status", "completed")
        if status != "completed":
            logging.error("Upload for %s failed with status %s", file_path.name, status)
            return False, []
        uploads.append((file_path, result))

    if state:
        for file_path, result in uploads:
            vector_file_id = getattr(result, "id", None)
            source_file_id = getattr(result, "file_id", None)
            if vector_file_id:
                state.record_file(
                    file_path.name,
                    vector_file_id,
                    source_file_id=source_file_id,
                    uploaded_at=getattr(result, "created_at", None),
                )
    logging.info("Uploaded %d file(s)", len(batch))
    return True, uploads


def move_files(batch: List[Path], destination_dir: Path) -> None:
    for file_path in batch:
        destination = destination_dir / file_path.name
        destination_dir.mkdir(parents=True, exist_ok=True)
        logging.debug("Moving %s -> %s", file_path, destination)
        file_path.replace(destination)


def collect_pdfs(source_dir: Path) -> List[Path]:
    if not source_dir.exists():
        logging.warning("Source directory %s does not exist", source_dir)
        return []
    pdfs = sorted(path for path in source_dir.iterdir() if path.suffix.lower() == ".pdf")
    logging.info("Found %d PDF(s) to ingest", len(pdfs))
    return pdfs


def process_pdfs(
    *,
    source_dir: Path,
    destination_dir: Path,
    vector_store_id: str,
    client: OpenAI,
    state: Optional[VectorStoreState] = None,
) -> List[Path]:
    pdfs = collect_pdfs(source_dir)
    if not pdfs:
        logging.info("No documents to process")
        return []

    processed: List[Path] = []
    for batch in chunked(pdfs, MAX_FILES_PER_BATCH):
        success, _ = upload_batch(client, vector_store_id, batch, state=state)
        if success:
            move_files(batch, destination_dir)
            for file_path in batch:
                processed.append(destination_dir / file_path.name)
        else:
            logging.error("Stopping ingestion due to upload failure")
            break
    return processed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload PDFs to an OpenAI vector store")
    parser.add_argument(
        "--source",
        type=Path,
        default=NOT_EXTRACTED_DIR,
        help="Directory containing PDFs to ingest",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=EXTRACTED_DIR,
        help="Directory to move processed PDFs into",
    )
    parser.add_argument(
        "--vector-store-name",
        default=DEFAULT_VECTOR_STORE_NAME,
        help="Name for the vector store (only used on first run)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=STATE_FILE,
        help="Path to cache vector store id",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    if load_dotenv:
        load_dotenv()
    else:
        logging.debug("python-dotenv not available; relying on shell environment")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable must be set")

    client = OpenAI(api_key=api_key)

    state = VectorStoreState(args.state_file)

    vector_store_id = ensure_vector_store(
        client,
        name=args.vector_store_name,
        state=state,
    )

    args.source.mkdir(parents=True, exist_ok=True)
    args.destination.mkdir(parents=True, exist_ok=True)

    processed_paths = process_pdfs(
        source_dir=args.source,
        destination_dir=args.destination,
        vector_store_id=vector_store_id,
        client=client,
        state=state,
    )

    if processed_paths:
        logging.info("Processed %d document(s)", len(processed_paths))


if __name__ == "__main__":
    main()
