import re


def normalize(text: str) -> str:
    """
    Normalizes text for open-ended answer comparison.

    Applied both when saving the correct answer (during question creation)
    and when processing user input (during answer submission),
    ensuring consistent comparison between the two.

    - Collapses multiple whitespace characters (spaces, tabs, newlines) into a single space
    - Strips leading and trailing whitespace
    - Converts text to lowercase

    Returns normalized string ready for comparison
    """

    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    text = text.lower()

    return text
