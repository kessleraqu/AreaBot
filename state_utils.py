from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional


class VectorStoreState:
    """Helper to persist vector store metadata alongside cached file mappings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logging.warning("Failed to load vector store state from %s: %s", self.path, exc)
            return {}

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def get_vector_store_id(self) -> Optional[str]:
        raw = self._data.get("vector_store_id")
        return raw if isinstance(raw, str) and raw else None

    def set_vector_store_id(self, vector_store_id: str) -> None:
        self._data["vector_store_id"] = vector_store_id
        self._data.setdefault("files", {})
        self.save()

    def _files(self) -> Dict[str, Dict[str, Any]]:
        files = self._data.setdefault("files", {})
        if not isinstance(files, dict):
            files = {}
            self._data["files"] = files
        return files

    def record_file(
        self,
        filename: str,
        vector_file_id: str,
        source_file_id: Optional[str] = None,
        *,
        uploaded_at: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {"vector_file_id": vector_file_id}
        if source_file_id:
            payload["source_file_id"] = source_file_id
        payload["uploaded_at"] = uploaded_at or int(time.time())
        files = self._files()
        if files.get(filename) == payload:
            return
        files[filename] = payload
        self.save()

    def remove_file(self, filename: str) -> None:
        files = self._files()
        if filename in files:
            files.pop(filename)
            self.save()

    def get_entry(self, filename: str) -> Optional[Dict[str, Any]]:
        entry = self._files().get(filename)
        if isinstance(entry, dict):
            return entry
        return None

    def entries(self) -> Dict[str, Dict[str, Any]]:
        files = self._files()
        return {name: meta for name, meta in files.items() if isinstance(meta, dict)}

    def find_by_vector_file_id(self, vector_file_id: str) -> Optional[str]:
        for name, meta in self.entries().items():
            if meta.get("vector_file_id") == vector_file_id:
                return name
        return None

    def bulk_merge(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        files = self._files()
        changed = False
        for name, meta in mapping.items():
            if not isinstance(meta, dict):
                continue
            current = files.get(name)
            if current != meta:
                files[name] = meta
                changed = True
        if changed:
            self.save()