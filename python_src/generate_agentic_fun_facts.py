"""
Generate bird fun facts by asking the `pi` coding agent for species-specific facts.

This is an alternative to the search/Ollama pipeline in bird_fun_facts.py. It reads
the existing bird image/link databases, asks `pi` for one verified species fact per
bird, and stores the result in the same shape consumed by the Go sender.
"""
import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tqdm.auto import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BIRD_DB_PATH = SCRIPT_DIR / "bird_db.json"
DEFAULT_BIRD_LINKS_PATH = SCRIPT_DIR / "bird_db_links.json"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "bird_fact_db_pi.json"
CANNOT_FIND_FACT = "I cannot find a fact."
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1b\\))")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    with path.open("r") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected {path} to contain a JSON object")

    return data


def load_existing_facts(path: Path) -> dict[str, dict[str, Any]]:
    """Load the current fact database, returning an empty database if it is absent."""
    try:
        return load_json(path)
    except FileNotFoundError:
        return {}


def save_fact_database(path: Path, fact_db: dict[str, dict[str, Any]]) -> None:
    """Save facts atomically so interrupted runs do not corrupt the database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with tmp_path.open("w") as f:
        json.dump(fact_db, f, indent=2, ensure_ascii=False)
        f.write("\n")

    tmp_path.replace(path)


def build_species_list(
    bird_db: dict[str, Any],
    bird_links: dict[str, Any],
    bird_name: str | None,
) -> list[str]:
    """Build the list of species that have both an image URL and a species page."""
    species = sorted(
        name
        for name, image_url in bird_db.items()
        if image_url and name in bird_links and bird_links[name]
    )

    if bird_name is None:
        return species

    if bird_name not in species:
        raise ValueError(
            f"{bird_name!r} was not found in both bird_db.json and bird_db_links.json "
            "with a non-empty image URL"
        )

    return [bird_name]


def build_pi_prompt(bird_name: str) -> str:
    """Create the prompt sent to pi."""
    return (
        f"Find one fun fact about the bird species {bird_name}. "
        f"Make sure the fact is specifically about {bird_name}, not just its genus, "
        "family, lookalikes, or birds in general. Use a minimal number of searches to extract the fact. "
        "Be efficient. Fun facts include unique properties of the bird, birdsong, mating ritual, or behavior. "
        "Last resort is where the bird is found (but include this info if you can). Verify that the fact belongs to "
        "this exact species. If it does not, or you cannot verify it, respond with "
        f"exactly: {CANNOT_FIND_FACT}\n\n"
        "Response style: you are a whacky, zany bird expert whose bird-loving "
        "personality is flapping wildly through the rafters. Use playful wording, "
        "bird puns, and a little feathery chaos, but keep the answer factual and "
        "specific to the species. If the verified information supports it, include "
        "where the species can be found. Respond with 1 or 2 sentences of just the fact, or "
        f"'{CANNOT_FIND_FACT}' Do not include citations, markdown, labels, or any "
        "extra commentary."
    )


def clean_pi_response(text: str) -> str:
    """Normalize pi output while preserving the fact text itself."""
    text = ANSI_ESCAPE_RE.sub("", text)
    text = CONTROL_CHAR_RE.sub("", text)
    text = text.strip()

    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()

    if (
        (text.startswith('"') and text.endswith('"'))
        or (text.startswith("'") and text.endswith("'"))
    ):
        text = text[1:-1].strip()

    return text


def is_cannot_find_response(text: str) -> bool:
    """Return True when pi clearly reports that it could not verify a fact."""
    normalized = text.strip().lower().rstrip(".")
    return normalized == CANNOT_FIND_FACT.lower().rstrip(".")


def ask_pi_for_fact(bird_name: str, timeout: int) -> str | None:
    """Ask pi for a fact about a single bird species."""
    prompt = build_pi_prompt(bird_name)

    try:
        completed = subprocess.run(
            ["pi", "--print", "--no-session", prompt],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("Could not find `pi` on PATH") from None
    except subprocess.TimeoutExpired:
        print(f"Timed out asking pi for {bird_name}", file=sys.stderr)
        return None

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        print(
            f"pi failed for {bird_name} with exit code {completed.returncode}"
            + (f": {stderr}" if stderr else ""),
            file=sys.stderr,
        )
        return None

    fact = clean_pi_response(completed.stdout)

    if not fact or is_cannot_find_response(fact):
        print(f"No verified fact found for {bird_name}", file=sys.stderr)
        return None

    return fact


def build_fact_entry(
    bird_name: str,
    fact: str,
    bird_db: dict[str, Any],
    bird_links: dict[str, Any],
) -> dict[str, Any]:
    """Create the database entry consumed by the Go sender."""
    return {
        "fact": fact,
        "urls": [],
        "img_url": bird_db[bird_name],
        "species_page": bird_links[bird_name],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate species-specific bird fun facts with the pi CLI."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to the output fact database. Default: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--bird-name",
        help="Generate a fact for exactly one species.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate facts for species already present in the output database.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for each pi call. Default: 600.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    bird_db = load_json(DEFAULT_BIRD_DB_PATH)
    bird_links = load_json(DEFAULT_BIRD_LINKS_PATH)
    fact_db = load_existing_facts(args.output)

    species = build_species_list(bird_db, bird_links, args.bird_name)

    if not args.force:
        species = [name for name in species if name not in fact_db]

    random.shuffle(species)

    print(f"Loaded {len(fact_db)} existing facts. Attempting {len(species)} species.")

    for bird_name in tqdm(species, desc="Gathering agentic fun facts"):
        fact = ask_pi_for_fact(bird_name, args.timeout)
        if not fact:
            continue

        fact_db[bird_name] = build_fact_entry(bird_name, fact, bird_db, bird_links)
        save_fact_database(args.output, fact_db)

    save_fact_database(args.output, fact_db)
    print(f"Saved {len(fact_db)} facts to {args.output}")


if __name__ == "__main__":
    main()
