from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Dict

from openai import OpenAI

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

QUESTION = "And remote monitoring?"
STATE_FILE = Path("vector_store_state.json")
MEMORY_FILE = Path("conversation_memory.jsonl")
MAX_TURNS = 10


def load_vector_store_id(state_file: Path) -> str:
    if not state_file.exists():
        raise RuntimeError("vector_store_state.json not found; run pdf_processor.py first to create a vector store.")

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("vector_store_state.json is not valid JSON") from exc

    vector_store_id = data.get("vector_store_id")
    if not vector_store_id:
        raise RuntimeError("vector_store_state.json does not contain 'vector_store_id'.")
    return vector_store_id


def load_memory(memory_file: Path) -> List[Dict[str, str]]:
    if not memory_file.exists():
        return []

    turns: List[Dict[str, str]] = []
    with memory_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                logging.warning("Skipping malformed memory line")
    return turns[-MAX_TURNS:]


def save_memory(memory_file: Path, turns: List[Dict[str, str]]) -> None:
    bounded = turns[-MAX_TURNS:]
    with memory_file.open("w", encoding="utf-8") as handle:
        for turn in bounded:
            handle.write(json.dumps(turn, ensure_ascii=True) + "\n")


def build_message_history(turns: List[Dict[str, str]]) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    for turn in turns[-MAX_TURNS:]:
        user_text = turn.get("user")
        assistant_text = turn.get("assistant")
        if user_text:
            history.append({"role": "user", "content": user_text})
        if assistant_text:
            history.append({"role": "assistant", "content": assistant_text})
    return history


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if load_dotenv:
        load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable must be set")

    vector_store_id = load_vector_store_id(STATE_FILE)
    turns = load_memory(MEMORY_FILE)
    message_history = build_message_history(turns)
    message_history.append({"role": "user", "content": QUESTION})

    client = OpenAI(api_key=api_key)

    logging.info("Sending question to model using vector store %s...", vector_store_id)

    response = client.responses.create(
        model="gpt-5",
        reasoning={"effort": "low"},
        input=message_history,
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
            }
        ],
    )

    answer = response.output_text
    logging.info("Model response:\n%s", answer)

    turns.append({"user": QUESTION, "assistant": answer})
    save_memory(MEMORY_FILE, turns)


if __name__ == "__main__":
    main()
