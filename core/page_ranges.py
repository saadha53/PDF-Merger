import re


def parse_page_order(text: str, page_count: int) -> list[int]:
    """Convert 1-based pages/ranges to ordered zero-based indexes; blank means all."""
    if page_count < 1:
        raise ValueError("The PDF has no pages.")
    if not text.strip():
        return list(range(page_count))
    pages = []
    for token in text.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", token)
        if not match:
            raise ValueError("Use page numbers or ranges, for example: 3, 1-2, 5-4.")
        start = int(match[1])
        end = int(match[2] or match[1])
        if not (1 <= start <= page_count and 1 <= end <= page_count):
            raise ValueError(f"Page numbers must be between 1 and {page_count}.")
        step = 1 if end >= start else -1
        pages.extend(range(start - 1, end - 1 + step, step))
    return pages


def parse_split_groups(text: str, page_count: int) -> list[list[int]]:
    """Blank splits every page; semicolons separate output PDFs."""
    if not text.strip():
        return [[page] for page in parse_page_order("", page_count)]
    groups = text.split(";")
    if any(not group.strip() for group in groups):
        raise ValueError("Each split group must contain pages.")
    return [parse_page_order(group, page_count) for group in groups]
