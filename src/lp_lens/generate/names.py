"""Invented names for managers, funds and investors.

Every string here is made up. The word lists are deliberately built from compounded English place
elements that do not correspond to firms operating in private markets, and the suffixes are the
generic legal-form words any such name would end in. No name is drawn from a real firm, index or
institution; any resemblance to one is coincidental and not intended.

The lists are sampled without replacement so names are unique, which is what lets the dimension
tables carry a natural key alongside the surrogate id.
"""

from __future__ import annotations

MANAGER_STEMS: tuple[str, ...] = (
    "Aldermere",
    "Brightwater",
    "Calderwood",
    "Dunmarrow",
    "Eastvale",
    "Fernhollow",
    "Glenmara",
    "Havenridge",
    "Ironvale",
    "Juniper Reach",
    "Kestrelford",
    "Larkhaven",
    "Marchmont",
    "Northwold",
    "Oakmere",
    "Pinehurst",
    "Quarrymoor",
    "Redcliff",
    "Stonebridge",
    "Thornfield",
    "Umberlane",
    "Vantagewood",
    "Westmarch",
    "Yarrowdale",
    "Zephyrgate",
    "Ashcombe",
    "Bramblewick",
    "Cloverdon",
    "Dovesmoor",
    "Elmbarrow",
    "Foxgarth",
    "Greyfen",
)

MANAGER_SUFFIXES: tuple[str, ...] = (
    "Capital",
    "Partners",
    "Capital Partners",
    "Advisors",
    "Investment Partners",
)

INVESTOR_STEMS: tuple[str, ...] = (
    "Cedar Ridge",
    "Harrowgate",
    "Silverbeck",
    "Maplecourt",
    "Ravenscourt",
    "Thistledown",
    "Windermoor",
    "Ashbury",
    "Fairholt",
    "Lindenmere",
    "Orchardleigh",
    "Penwicke",
    "Sandbourne",
    "Tollworth",
    "Wrenfield",
    "Ellersby",
)

# One naming pattern per investor type, so the name and the type agree.
INVESTOR_PATTERNS: dict[str, str] = {
    "Pension": "{stem} Pension Trust",
    "Endowment": "{stem} University Endowment",
    "Insurance": "{stem} Assurance Group",
    "Family Office": "{stem} Family Office",
    "Sovereign Wealth": "{stem} Sovereign Fund",
}

# How each strategy reads inside a fund name.
STRATEGY_LABELS: dict[str, str] = {
    "Buyout": "Buyout",
    "Venture": "Ventures",
    "Growth": "Growth",
    "Private Credit": "Credit",
    "Real Estate": "Realty",
    "Infrastructure": "Infrastructure",
    "Secondaries": "Secondaries",
}

_ROMAN: tuple[tuple[int, str], ...] = (
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def roman(n: int) -> str:
    """Roman numeral for a fund sequence number. Used for names like "Oakmere Buyout IV"."""
    if n < 1:
        raise ValueError(f"fund sequence number must be >= 1, got {n}")
    out = []
    for value, symbol in _ROMAN:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


def investor_name(stem: str, investor_type: str) -> str:
    try:
        return INVESTOR_PATTERNS[investor_type].format(stem=stem)
    except KeyError as exc:
        raise ValueError(f"no name pattern for investor type {investor_type!r}; add one to INVESTOR_PATTERNS") from exc


def strategy_label(strategy: str) -> str:
    try:
        return STRATEGY_LABELS[strategy]
    except KeyError as exc:
        raise ValueError(f"no fund-name label for strategy {strategy!r}; add one to STRATEGY_LABELS") from exc
