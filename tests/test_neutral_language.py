"""The app serves softball and baseball players. Nothing a family reads, and
nothing an AI assistant is told, may assume the player's gender.

This has slipped through three times. The only permitted uses are the pronoun
choices themselves ("she/her", "he/him")."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = [
    *sorted((ROOT / "src" / "recruiting_desk").glob("*.py")),
    *sorted((ROOT / "src" / "recruiting_desk" / "static").glob("*.html")),
    *sorted((ROOT / "src" / "recruiting_desk" / "static").glob("*.js")),
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "README.md",
]
GENDERED = re.compile(r"\b(she|her|hers|herself|he|him|his|himself|daughter|son|sister|brother)\b", re.I)
ALLOWED = re.compile(r"she/her|he/him|they/them")


def test_no_gendered_language():
    found = []
    for f in CHECK:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if GENDERED.search(ALLOWED.sub("", line)):
                found.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not found, "Gendered wording found:\n" + "\n".join(found)
