"""
Intent Recognition service for VibeLocate Natural Language AI Search.

Clear Arabic/English property-search requests are parsed locally first.
The external LLM is used only as a fallback for incomplete/ambiguous requests.

POI constraints are encoded in required_amenities for backward compatibility:

- nearby cafe
- nearby school
- far bar
- far nightclub
"""

from __future__ import annotations

import re
from typing import Any

from app.deepseek_client import DeepSeekUnavailableError, call_json
from app.schemas import KNOWN_PROPERTY_TYPES, ParsedCriteria, QueryRequest


_TYPE_LIST_STR = ", ".join(
    f'"{property_type}"'
    for property_type in KNOWN_PROPERTY_TYPES
)


POI_DEFINITIONS: dict[str, dict[str, Any]] = {
    "restaurant": {
        "near": "nearby restaurant",
        "far": "far restaurant",
        "aliases": [
            "restaurant",
            "restaurants",
            "مطعم",
            "مطاعم",
        ],
    },

    "supermarket": {
        "near": "nearby supermarket",
        "far": "far supermarket",
        "aliases": [
            "supermarket",
            "super market",
            "grocery",
            "grocery store",
            "سوبرماركت",
            "سوبر ماركت",
            "بقالة",
        ],
    },

    "cafe": {
        "near": "nearby cafe",
        "far": "far cafe",
        "aliases": [
            "cafe",
            "café",
            "coffee shop",
            "coffee",
            "مقهى",
            "كافيه",
            "كوفي",
        ],
    },

    "pharmacy": {
        "near": "nearby pharmacy",
        "far": "far pharmacy",
        "aliases": [
            "pharmacy",
            "drugstore",
            "صيدلية",
            "صيدليه",
        ],
    },

    "transit_station": {
        "near": "nearby transit station",
        "far": "far transit station",
        "aliases": [
            "transit station",
            "metro station",
            "bus station",
            "train station",
            "metro",
            "محطة مترو",
            "محطة باص",
            "محطة حافلات",
            "مترو",
            "محطة",
        ],
    },

    "school": {
        "near": "nearby school",
        "far": "far school",
        "aliases": [
            "school",
            "schools",
            "مدرسة",
            "مدرسه",
            "مدارس",
        ],
    },

    "clinic": {
        "near": "nearby clinic",
        "far": "far clinic",
        "aliases": [
            "clinic",
            "medical clinic",
            "عيادة",
            "عياده",
            "مستوصف",
        ],
    },

    "hospital": {
        "near": "nearby hospital",
        "far": "far hospital",
        "aliases": [
            "hospital",
            "hospitals",
            "مستشفى",
            "مستشفيات",
        ],
    },

    "park": {
        "near": "nearby park",
        "far": "far park",
        "aliases": [
            "park",
            "parks",
            "garden",
            "public park",
            "حديقة",
            "حديقه",
            "منتزه",
        ],
    },

    "police": {
        "near": "nearby police",
        "far": "far police",
        "aliases": [
            "police station",
            "police",
            "مركز شرطة",
            "شرطة",
            "مخفر",
        ],
    },

    "bar": {
        "near": "nearby bar",
        "far": "far bar",
        "aliases": [
            "bar",
            "bars",
            "بار",
        ],
    },

    "nightclub": {
        "near": "nearby nightclub",
        "far": "far nightclub",
        "aliases": [
            "nightclub",
            "night club",
            "nightclubs",
            "night clubs",
            "نادي ليلي",
            "ملهى ليلي",
            "ملاهي ليلية",
        ],
    },
}


ALLOWED_POI_VALUES = {
    definition[relation]
    for definition in POI_DEFINITIONS.values()
    for relation in (
        "near",
        "far",
    )
}


SYSTEM_PROMPT = f"""
You are an intent-extraction engine for a real-estate search application.

The user can write in Arabic or English.

Return ONLY one JSON object with exactly these fields:

{{
  "property_type": string or null,
  "action_type": string or null,
  "min_budget": number or null,
  "max_budget": number or null,
  "budget_currency": string or null,
  "min_bedrooms": integer or null,
  "max_bedrooms": integer or null,
  "vibe_tags": array,
  "required_amenities": array,
  "location_hint": string or null,
  "confidence": number,
  "needs_clarification": boolean
}}

PROPERTY TYPE:

- property_type must be one of:
  {_TYPE_LIST_STR}

- If not explicitly stated or clearly implied, return null.

ACTION TYPE:

- action_type must be:
  "buy"
  "rent"
  "booking"
  null

- Never invent buy/rent/booking.

BUDGET:

Maximum budget:

under
below
less than
up to
maximum
max

أقل من
اقل من
حتى
تحت
بحد أقصى
بحد اقصى

These mean:

min_budget = null
max_budget = stated value

Minimum budget:

at least
minimum
more than
above
over

أكثر من
اكثر من
فوق
على الأقل
على الاقل
حد أدنى
حد ادنى

These mean:

min_budget = stated value
max_budget = null

Normalize AED / dirham / درهم to AED.
Normalize USD / dollar / دولار to USD.

Do not invent budget or currency.

BEDROOMS:

Exact count:

min_bedrooms = max_bedrooms

Minimum count:

set min_bedrooms only

Maximum count:

set max_bedrooms only

Range count:

set both min_bedrooms and max_bedrooms.

Examples:

"من غرفتين إلى 4 غرف"
min_bedrooms = 2
max_bedrooms = 4

"بين 2 و4 غرف"
min_bedrooms = 2
max_bedrooms = 4

"2 to 4 bedrooms"
min_bedrooms = 2
max_bedrooms = 4

"between 2 and 4 bedrooms"
min_bedrooms = 2
max_bedrooms = 4

LOCATION:

location_hint must be the most specific location explicitly stated.

Never invent a location.

POI CONSTRAINTS:

required_amenities may contain ONLY these values:

{chr(10).join(sorted(ALLOWED_POI_VALUES))}

Examples:

User:
شقة قريبة من مدرسة ومقهى وبعيدة عن بار ونادي ليلي

Return:

"required_amenities": [
  "nearby school",
  "nearby cafe",
  "far bar",
  "far nightclub"
]

User:
apartment near metro station and hospital but far from nightclub

Return:

"required_amenities": [
  "nearby transit station",
  "nearby hospital",
  "far nightclub"
]

OTHER RULES:

- vibe_tags must always be an array.
- required_amenities must always be an array.
- confidence must be between 0 and 1.
- needs_clarification=true only when the request is too vague
  or contains contradictory POI constraints.
- Do not invent constraints.
"""


_ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


def _normalize_text(
    value: Any,
) -> str:

    if value is None:
        return ""

    text = str(
        value
    ).translate(
        _ARABIC_DIGITS
    )

    text = (
        text
        .replace(
            "٬",
            ",",
        )
        .replace(
            "٫",
            ".",
        )
    )

    return re.sub(
        r"\s+",
        " ",
        text,
        flags=re.UNICODE,
    ).strip()


def _ensure_list(
    value: Any,
) -> list:

    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return value

    if isinstance(
        value,
        (
            tuple,
            set,
        ),
    ):
        return list(
            value
        )

    return [
        value
    ]


def _safe_float(
    value: Any,
) -> float | None:

    if (
        value is None
        or value == ""
    ):
        return None

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _safe_int(
    value: Any,
) -> int | None:

    if (
        value is None
        or value == ""
    ):
        return None

    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _contains_alias(
    text: str,
    alias: str,
) -> bool:

    text_cf = (
        text
        .casefold()
    )

    alias_cf = (
        alias
        .casefold()
        .strip()
    )

    if not alias_cf:
        return False

    if re.search(
        r"[A-Za-z]",
        alias_cf,
    ):
        pattern = (
            rf"(?<![a-z0-9])"
            rf"{re.escape(alias_cf)}"
            rf"(?![a-z0-9])"
        )

        return (
            re.search(
                pattern,
                text_cf,
            )
            is not None
        )

    return (
        alias_cf
        in text_cf
    )


def _canonical_property_type(
    candidate: str | None,
) -> str | None:

    if not candidate:
        return None

    candidate_cf = (
        str(
            candidate
        )
        .strip()
        .casefold()
    )

    for known in KNOWN_PROPERTY_TYPES:

        if (
            str(
                known
            )
            .strip()
            .casefold()
            == candidate_cf
        ):
            return known

    return None


_PROPERTY_TYPE_ALIASES = {
    "Apartment": [
        "apartment",
        "flat",
        "شقة",
        "شقه",
    ],

    "Villa": [
        "villa",
        "فيلا",
    ],

    "Townhouse": [
        "townhouse",
        "town house",
        "تاون هاوس",
    ],

    "Penthouse": [
        "penthouse",
        "بنتهاوس",
        "بنت هاوس",
    ],

    "House": [
        "house",
        "home",
        "منزل",
        "بيت",
    ],

    "Office": [
        "office",
        "مكتب",
    ],

    "Warehouse": [
        "warehouse",
        "مستودع",
        "مخزن",
    ],

    "Land": [
        "land",
        "plot",
        "أرض",
        "ارض",
    ],

    "Building": [
        "building",
        "full building",
        "مبنى",
        "عمارة",
        "عماره",
    ],

    "Commercial Shop": [
        "commercial shop",
        "retail shop",
        "shop",
        "محل تجاري",
        "محل",
    ],

    "Showroom": [
        "showroom",
        "معرض",
    ],

    "Hotel": [
        "hotel",
        "فندق",
    ],

    "Restaurant": [
        "restaurant",
        "مطعم",
    ],

    "Clinic": [
        "clinic",
        "medical clinic",
        "عيادة",
        "عياده",
        "مستوصف",
    ],

    "School": [
        "school",
        "مدرسة",
        "مدرسه",
    ],

    "Cafe": [
        "cafe",
        "café",
        "coffee shop",
        "مقهى",
        "كافيه",
    ],
}


_AMBIGUOUS_POI_PROPERTY_TYPES = {
    "Restaurant",
    "Clinic",
    "School",
    "Cafe",
}


_NEAR_CUES = [
    "close to",
    "next to",
    "nearby",
    "near",
    "beside",
    "around",

    "قريبة من",
    "قريب من",
    "بالقرب من",
    "بالقرب",
    "بجانب",
    "جنب",
    "قريبة",
    "قريب",
    "حول",
]


_FAR_CUES = [
    "far away from",
    "far from",
    "away from",
    "not near",
    "far",

    "بعيدة عن",
    "بعيد عن",
    "بعيدة من",
    "بعيد من",
    "بعيدة",
    "بعيد",
]


def _cue_pattern(
    cues: list[str],
) -> str:

    ordered = sorted(
        cues,
        key=len,
        reverse=True,
    )

    return "|".join(
        re.escape(
            cue
        )
        for cue in ordered
    )


_RELATION_PATTERN = re.compile(
    rf"(?P<near>{_cue_pattern(_NEAR_CUES)})"
    rf"|"
    rf"(?P<far>{_cue_pattern(_FAR_CUES)})",
    flags=(
        re.IGNORECASE
        |
        re.UNICODE
    ),
)


def _poi_relation_segments(
    text: str,
) -> list[
    tuple[
        str,
        str,
    ]
]:

    normalized = (
        _normalize_text(
            text
        )
        .casefold()
    )

    matches = list(
        _RELATION_PATTERN
        .finditer(
            normalized
        )
    )

    if not matches:
        return []

    segments: list[
        tuple[
            str,
            str,
        ]
    ] = []

    for index, match in enumerate(
        matches
    ):

        relation = (
            "near"
            if match.group(
                "near"
            )
            is not None
            else "far"
        )

        start = (
            match.end()
        )

        end = (
            matches[
                index + 1
            ].start()

            if (
                index + 1
                < len(
                    matches
                )
            )

            else len(
                normalized
            )
        )

        segment = (
            normalized[
                start:end
            ]
        )

        segments.append(
            (
                relation,
                segment,
            )
        )

    return segments


def _alias_used_as_poi_constraint(
    text: str,
    aliases: list[str],
) -> bool:

    for (
        _,
        segment,
    ) in _poi_relation_segments(
        text
    ):

        if any(
            _contains_alias(
                segment,
                alias,
            )
            for alias
            in aliases
        ):
            return True

    return False


def _detect_property_type_from_text(
    text: str,
) -> str | None:

    normalized = (
        _normalize_text(
            text
        )
    )

    for (
        canonical,
        aliases,
    ) in _PROPERTY_TYPE_ALIASES.items():

        if (
            canonical
            in _AMBIGUOUS_POI_PROPERTY_TYPES
        ):
            continue

        known = (
            _canonical_property_type(
                canonical
            )
        )

        if (
            known
            and any(
                _contains_alias(
                    normalized,
                    alias,
                )
                for alias
                in aliases
            )
        ):
            return known

    for canonical in _AMBIGUOUS_POI_PROPERTY_TYPES:

        aliases = (
            _PROPERTY_TYPE_ALIASES[
                canonical
            ]
        )

        known = (
            _canonical_property_type(
                canonical
            )
        )

        if not known:
            continue

        if not any(
            _contains_alias(
                normalized,
                alias,
            )
            for alias
            in aliases
        ):
            continue

        if _alias_used_as_poi_constraint(
            normalized,
            aliases,
        ):
            continue

        return known

    return None


def _detect_action_type_from_text(
    text: str,
) -> str | None:

    normalized = (
        _normalize_text(
            text
        )
        .casefold()
    )

    rent_aliases = [
        "for rent",
        "rent",
        "rental",
        "lease",
        "للإيجار",
        "للايجار",
        "إيجار",
        "ايجار",
        "استئجار",
    ]

    buy_aliases = [
        "for sale",
        "buy",
        "purchase",
        "للبيع",
        "شراء",
        "اشتري",
        "أريد شراء",
        "اريد شراء",
    ]

    booking_aliases = [
        "booking",
        "book",
        "reserve",
        "reservation",
        "حجز",
        "احجز",
    ]

    if any(
        _contains_alias(
            normalized,
            alias,
        )
        for alias
        in rent_aliases
    ):
        return "rent"

    if any(
        _contains_alias(
            normalized,
            alias,
        )
        for alias
        in buy_aliases
    ):
        return "buy"

    if any(
        _contains_alias(
            normalized,
            alias,
        )
        for alias
        in booking_aliases
    ):
        return "booking"

    return None


_NUMBER_PATTERN = (
    r"([0-9]+"
    r"(?:[.,][0-9]+)?"
    r"\s*"
    r"(?:k|m|ألف|الف|مليون)?)"
)


def _parse_number(
    value: str | None,
) -> float | None:

    if value is None:
        return None

    raw = (
        _normalize_text(
            value
        )
        .casefold()
        .strip()
    )

    multiplier = 1.0

    if re.search(
        r"(?:ألف|الف)\s*$",
        raw,
    ):
        multiplier = (
            1_000.0
        )

        raw = re.sub(
            r"(?:ألف|الف)\s*$",
            "",
            raw,
        ).strip()

    elif re.search(
        r"مليون\s*$",
        raw,
    ):
        multiplier = (
            1_000_000.0
        )

        raw = re.sub(
            r"مليون\s*$",
            "",
            raw,
        ).strip()

    elif raw.endswith(
        "k"
    ):
        multiplier = (
            1_000.0
        )

        raw = (
            raw[:-1]
            .strip()
        )

    elif raw.endswith(
        "m"
    ):
        multiplier = (
            1_000_000.0
        )

        raw = (
            raw[:-1]
            .strip()
        )

    raw = (
        raw
        .replace(
            ",",
            "",
        )
        .replace(
            " ",
            "",
        )
    )

    try:
        return (
            float(
                raw
            )
            * multiplier
        )

    except ValueError:
        return None


def _extract_budget_from_text(
    text: str,
) -> tuple[
    float | None,
    float | None,
]:

    normalized = (
        _normalize_text(
            text
        )
        .casefold()
    )

    def is_bedroom_number(
        match: re.Match,
    ) -> bool:
        """
        Prevent bedroom numbers from being interpreted as prices.

        Examples that must NOT be budgets:
        - from 2 to 4 bedrooms
        - between 2 and 4 bedrooms
        - at least 3 bedrooms
        - up to 2 bedrooms
        - من 2 إلى 4 غرف
        - على الأقل 3 غرف
        """

        tail = normalized[
            match.end():
        ]

        return (
            re.match(
                r"\s*"
                r"(?:"
                r"bedroom|"
                r"bedrooms|"
                r"bed|"
                r"beds|"
                r"غرفة|"
                r"غرفه|"
                r"غرف"
                r")"
                r"(?:\b|\s|$|[,،.])",
                tail,
                flags=(
                    re.IGNORECASE
                    |
                    re.UNICODE
                ),
            )
            is not None
        )

    # ---------------------------------------------------------
    # BUDGET RANGE
    # ---------------------------------------------------------

    range_patterns = [
        (
            rf"بين\s*"
            rf"{_NUMBER_PATTERN}"
            rf"\s*"
            rf"(?:و|الى|إلى|-)"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),

        (
            rf"من\s*"
            rf"{_NUMBER_PATTERN}"
            rf"\s*"
            rf"(?:الى|إلى|حتى|-)"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),

        (
            rf"(?:between|from)\s*"
            rf"{_NUMBER_PATTERN}"
            rf"\s*"
            rf"(?:and|to|-)"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),

        (
            rf"{_NUMBER_PATTERN}"
            rf"\s*"
            rf"(?:-|–|—)"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),
    ]

    for pattern in range_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        # Important:
        # "from 2 to 4 bedrooms" is a bedroom range,
        # not a budget range.
        if is_bedroom_number(
            match
        ):
            continue

        first = (
            _parse_number(
                match.group(1)
            )
        )

        second = (
            _parse_number(
                match.group(2)
            )
        )

        if (
            first is not None
            and
            second is not None
        ):
            return (
                min(
                    first,
                    second,
                ),
                max(
                    first,
                    second,
                ),
            )

    # ---------------------------------------------------------
    # MAXIMUM BUDGET
    # ---------------------------------------------------------

    max_patterns = [
        (
            rf"(?:"
            rf"أقل\s*من|"
            rf"اقل\s*من|"
            rf"بحد\s*أقصى|"
            rf"بحد\s*اقصى|"
            rf"حتى|"
            rf"تحت"
            rf")"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),

        (
            rf"(?:"
            rf"under|"
            rf"below|"
            rf"less\s+than|"
            rf"up\s+to|"
            rf"maximum|"
            rf"max"
            rf")"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),
    ]

    for pattern in max_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        # Example:
        # "up to 2 bedrooms"
        # must not become max_budget=2.
        if is_bedroom_number(
            match
        ):
            continue

        return (
            None,
            _parse_number(
                match.group(1)
            ),
        )

    # ---------------------------------------------------------
    # MINIMUM BUDGET
    # ---------------------------------------------------------

    min_patterns = [
        (
            rf"(?:"
            rf"أكثر\s*من|"
            rf"اكثر\s*من|"
            rf"فوق|"
            rf"على\s*الأقل|"
            rf"على\s*الاقل|"
            rf"حد\s*أدنى|"
            rf"حد\s*ادنى"
            rf")"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),

        (
            rf"(?:"
            rf"at\s+least|"
            rf"minimum|"
            rf"more\s+than|"
            rf"over|"
            rf"above"
            rf")"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),
    ]

    for pattern in min_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        # Example:
        # "at least 3 bedrooms"
        # must not become min_budget=3.
        if is_bedroom_number(
            match
        ):
            continue

        return (
            _parse_number(
                match.group(1)
            ),
            None,
        )

    # ---------------------------------------------------------
    # EXACT BUDGET
    # ---------------------------------------------------------

    exact_patterns = [
        (
            rf"(?:"
            rf"بسعر|"
            rf"ميزانية|"
            rf"ميزانيتي|"
            rf"budget(?:\s+of)?|"
            rf"price(?:\s+of)?"
            rf")"
            rf"\s*"
            rf"{_NUMBER_PATTERN}"
        ),
    ]

    for pattern in exact_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if match:

            value = (
                _parse_number(
                    match.group(1)
                )
            )

            if value is not None:
                return (
                    value,
                    value,
                )

    return (
        None,
        None,
    )

def _detect_currency_from_text(
    text: str,
) -> str | None:

    normalized = (
        _normalize_text(
            text
        )
        .casefold()
    )

    if any(
        value in normalized
        for value
        in [
            "aed",
            "درهم",
            "د.إ",
            "dirham",
        ]
    ):
        return "AED"

    if any(
        value in normalized
        for value
        in [
            "usd",
            "دولار",
            "dollar",
            "$",
        ]
    ):
        return "USD"

    if any(
        value in normalized
        for value
        in [
            "sar",
            "ريال سعودي",
            "saudi riyal",
        ]
    ):
        return "SAR"

    if any(
        value in normalized
        for value
        in [
            "eur",
            "يورو",
            "euro",
        ]
    ):
        return "EUR"

    if any(
        value in normalized
        for value
        in [
            "gbp",
            "جنيه استرليني",
            "pound",
        ]
    ):
        return "GBP"

    return None


def _detect_bedrooms_from_text(
    text: str,
) -> tuple[
    int | None,
    int | None,
]:

    normalized = (
        _normalize_text(
            text
        )
        .casefold()
    )

    arabic_word_numbers = [
        (
            r"(?:غرفة\s+واحدة|غرفه\s+واحده)",
            1,
        ),

        (
            r"(?:غرفتين|غرفتان)",
            2,
        ),

        (
            r"(?:ثلاث\s+غرف|ثلاثة\s+غرف)",
            3,
        ),

        (
            r"(?:اربع\s+غرف|أربع\s+غرف|اربعة\s+غرف|أربعة\s+غرف)",
            4,
        ),

        (
            r"(?:خمس\s+غرف|خمسة\s+غرف)",
            5,
        ),
    ]

    def parse_bedroom_endpoint(
        value: str,
    ) -> int | None:

        fragment = (
            _normalize_text(
                value
            )
            .casefold()
            .strip()
        )

        numeric_match = re.search(
            r"\d+",
            fragment,
        )

        if numeric_match:
            return int(
                numeric_match.group(0)
            )

        for (
            pattern,
            count,
        ) in arabic_word_numbers:

            if re.fullmatch(
                pattern,
                fragment,
                flags=re.IGNORECASE,
            ):
                return count

        return None

    # ---------------------------------------------------------
    # BEDROOM RANGE
    # This MUST come before min/max/exact detection.
    # ---------------------------------------------------------

    arabic_word_endpoint = (
        r"(?:"
        r"غرفة\s+واحدة|"
        r"غرفه\s+واحده|"
        r"غرفتين|"
        r"غرفتان|"
        r"ثلاث\s+غرف|"
        r"ثلاثة\s+غرف|"
        r"اربع\s+غرف|"
        r"أربع\s+غرف|"
        r"اربعة\s+غرف|"
        r"أربعة\s+غرف|"
        r"خمس\s+غرف|"
        r"خمسة\s+غرف"
        r")"
    )

    arabic_numeric_endpoint_with_unit = (
        r"\d+\s*(?:غرفة|غرف|غرفه)"
    )

    arabic_first_endpoint = (
        rf"(?:"
        rf"{arabic_word_endpoint}|"
        rf"{arabic_numeric_endpoint_with_unit}|"
        rf"\d+"
        rf")"
    )

    arabic_second_endpoint = (
        rf"(?:"
        rf"{arabic_word_endpoint}|"
        rf"{arabic_numeric_endpoint_with_unit}"
        rf")"
    )

    arabic_range_patterns = [
        (
            rf"(?:من|بين)\s*"
            rf"(?P<first>{arabic_first_endpoint})\s*"
            rf"(?:إلى|الى|حتى|و|-|–|—)\s*"
            rf"(?P<second>{arabic_second_endpoint})"
        ),
    ]

    english_endpoint_with_unit = (
        r"\d+\s*(?:bedroom|bedrooms|bed|beds)"
    )

    english_first_endpoint = (
        rf"(?:"
        rf"{english_endpoint_with_unit}|"
        rf"\d+"
        rf")"
    )

    english_range_patterns = [
        (
            rf"from\s+"
            rf"(?P<first>{english_first_endpoint})\s*"
            rf"(?:to|-|–|—)\s*"
            rf"(?P<second>{english_endpoint_with_unit})"
        ),

        (
            rf"between\s+"
            rf"(?P<first>{english_first_endpoint})\s*"
            rf"(?:and|-|–|—)\s*"
            rf"(?P<second>{english_endpoint_with_unit})"
        ),

        (
            rf"(?P<first>{english_first_endpoint})\s*"
            rf"(?:to|-|–|—)\s*"
            rf"(?P<second>{english_endpoint_with_unit})"
        ),
    ]

    for pattern in [
        *arabic_range_patterns,
        *english_range_patterns,
    ]:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        first = (
            parse_bedroom_endpoint(
                match.group(
                    "first"
                )
            )
        )

        second = (
            parse_bedroom_endpoint(
                match.group(
                    "second"
                )
            )
        )

        if (
            first is None
            or
            second is None
        ):
            continue

        return (
            min(
                first,
                second,
            ),
            max(
                first,
                second,
            ),
        )

    # ---------------------------------------------------------
    # MINIMUM BEDROOMS
    # ---------------------------------------------------------

    for (
        pattern,
        count,
    ) in arabic_word_numbers:

        minimum_pattern = (
            rf"{pattern}"
            rf"\s*"
            rf"(?:"
            rf"أو\s*أكثر|"
            rf"او\s*اكثر|"
            rf"على\s*الأقل|"
            rf"على\s*الاقل"
            rf")"
        )

        if re.search(
            minimum_pattern,
            normalized,
            flags=re.IGNORECASE,
        ):
            return (
                count,
                None,
            )

    min_patterns = [
        (
            r"(?:at\s+least|minimum|min)"
            r"\s*(\d+)"
            r"\s*(?:bedroom|bedrooms|bed|beds)"
        ),

        (
            r"(\d+)"
            r"\s*(?:bedroom|bedrooms|bed|beds)"
            r"\s*(?:or\s+more|minimum)"
        ),

        (
            r"(\d+)"
            r"\s*(?:غرفة|غرف|غرفه)"
            r"\s*(?:"
            r"أو\s*أكثر|"
            r"او\s*اكثر|"
            r"على\s*الأقل|"
            r"على\s*الاقل"
            r")"
        ),
    ]

    for pattern in min_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if match:
            return (
                int(
                    match.group(1)
                ),
                None,
            )

    # ---------------------------------------------------------
    # MAXIMUM BEDROOMS
    # ---------------------------------------------------------

    for (
        pattern,
        count,
    ) in arabic_word_numbers:

        maximum_pattern = (
            rf"{pattern}"
            rf"\s*"
            rf"(?:"
            rf"أو\s*أقل|"
            rf"او\s*اقل|"
            rf"كحد\s*أقصى|"
            rf"كحد\s*اقصى|"
            rf"بحد\s*أقصى|"
            rf"بحد\s*اقصى"
            rf")"
        )

        if re.search(
            maximum_pattern,
            normalized,
            flags=re.IGNORECASE,
        ):
            return (
                None,
                count,
            )

    max_patterns = [
        (
            r"(?:at\s+most|maximum|max)"
            r"\s*(\d+)"
            r"\s*(?:bedroom|bedrooms|bed|beds)"
        ),

        (
            r"(\d+)"
            r"\s*(?:bedroom|bedrooms|bed|beds)"
            r"\s*(?:or\s+less|maximum)"
        ),

        (
            r"(\d+)"
            r"\s*(?:غرفة|غرف|غرفه)"
            r"\s*(?:"
            r"أو\s*أقل|"
            r"او\s*اقل|"
            r"كحد\s*أقصى|"
            r"كحد\s*اقصى|"
            r"بحد\s*أقصى|"
            r"بحد\s*اقصى"
            r")"
        ),
    ]

    for pattern in max_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if match:
            return (
                None,
                int(
                    match.group(1)
                ),
            )

    # ---------------------------------------------------------
    # EXACT BEDROOM COUNT
    # This comes LAST.
    # ---------------------------------------------------------

    for (
        pattern,
        count,
    ) in arabic_word_numbers:

        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        ):
            return (
                count,
                count,
            )

    exact_patterns = [
        (
            r"(\d+)"
            r"\s*"
            r"(?:"
            r"bedroom|"
            r"bedrooms|"
            r"bed|"
            r"beds"
            r")\b"
        ),

        (
            r"(\d+)"
            r"\s*"
            r"(?:"
            r"غرفة|"
            r"غرف|"
            r"غرفه"
            r")\b"
        ),
    ]

    for pattern in exact_patterns:

        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        if match:

            count = int(
                match.group(1)
            )

            return (
                count,
                count,
            )

    return (
        None,
        None,
    )


_LOCATION_ALIASES = [
    (
        "dubai marina",
        "Dubai Marina",
    ),

    (
        "دبي مارينا",
        "Dubai Marina",
    ),

    (
        "مرسى دبي",
        "Dubai Marina",
    ),

    (
        "downtown dubai",
        "Downtown Dubai",
    ),

    (
        "داون تاون دبي",
        "Downtown Dubai",
    ),

    (
        "وسط مدينة دبي",
        "Downtown Dubai",
    ),

    (
        "business bay",
        "Business Bay",
    ),

    (
        "بزنس باي",
        "Business Bay",
    ),

    (
        "الخليج التجاري",
        "Business Bay",
    ),

    (
        "palm jumeirah",
        "Palm Jumeirah",
    ),

    (
        "نخلة جميرا",
        "Palm Jumeirah",
    ),

    (
        "abu dhabi",
        "Abu Dhabi",
    ),

    (
        "أبو ظبي",
        "أبوظبي",
    ),

    (
        "ابو ظبي",
        "أبوظبي",
    ),

    (
        "أبوظبي",
        "أبوظبي",
    ),

    (
        "ابوظبي",
        "أبوظبي",
    ),

    (
        "ras al khaimah",
        "Ras Al Khaimah",
    ),

    (
        "رأس الخيمة",
        "رأس الخيمة",
    ),

    (
        "راس الخيمة",
        "رأس الخيمة",
    ),

    (
        "umm al quwain",
        "Umm Al Quwain",
    ),

    (
        "أم القيوين",
        "أم القيوين",
    ),

    (
        "ام القيوين",
        "أم القيوين",
    ),

    (
        "sharjah",
        "Sharjah",
    ),

    (
        "الشارقة",
        "الشارقة",
    ),

    (
        "شارقة",
        "الشارقة",
    ),

    (
        "ajman",
        "Ajman",
    ),

    (
        "عجمان",
        "عجمان",
    ),

    (
        "fujairah",
        "Fujairah",
    ),

    (
        "الفجيرة",
        "الفجيرة",
    ),

    (
        "فجيرة",
        "الفجيرة",
    ),

    (
        "dubai",
        "Dubai",
    ),

    (
        "دبي",
        "دبي",
    ),
]


def _normalize_location_alias(
    value: str,
) -> str:

    normalized = (
        _normalize_text(
            value
        )
        .casefold()
    )

    for (
        alias,
        canonical,
    ) in sorted(
        _LOCATION_ALIASES,
        key=lambda item: len(
            item[0]
        ),
        reverse=True,
    ):

        if (
            normalized
            == alias.casefold()
        ):
            return canonical

    return (
        _normalize_text(
            value
        )
    )


def _detect_location_from_text(
    text: str,
) -> str | None:

    original = (
        _normalize_text(
            text
        )
    )

    # Prefer known locations first.
    for (
        alias,
        canonical,
    ) in sorted(
        _LOCATION_ALIASES,
        key=lambda item: len(
            item[0]
        ),
        reverse=True,
    ):

        if _contains_alias(
            original,
            alias,
        ):
            return canonical

    stop_ar = (
        r"بسعر|"
        r"بميزانية|"
        r"ميزانية|"
        r"ميزانيتي|"
        r"اقل|"
        r"أقل|"
        r"اكثر|"
        r"أكثر|"
        r"تحت|"
        r"فوق|"
        r"حتى|"
        r"قريب|"
        r"قريبة|"
        r"بالقرب|"
        r"بجانب|"
        r"جنب|"
        r"بعيد|"
        r"بعيدة|"
        r"مع|"
        r"للبيع|"
        r"للإيجار|"
        r"للايجار|"
        r"غرفة|"
        r"غرفه|"
        r"غرف|"
        r"غرفتين|"
        r"غرفتان"
    )

    stop_en = (
        r"under|"
        r"below|"
        r"less|"
        r"over|"
        r"above|"
        r"with|"
        r"near|"
        r"nearby|"
        r"close|"
        r"next|"
        r"far|"
        r"away|"
        r"budget|"
        r"bedroom|"
        r"bedrooms|"
        r"bed|"
        r"beds|"
        r"for\s+rent|"
        r"for\s+sale"
    )

    patterns = [
        (
            rf"(?:^|\s)"
            rf"في\s+"
            rf"(.+?)"
            rf"(?="
            rf"\s+(?:{stop_ar})\b"
            rf"|[,،]"
            rf"|$"
            rf")"
        ),

        (
            rf"(?:^|\s)"
            rf"in\s+"
            rf"(.+?)"
            rf"(?="
            rf"\s+(?:{stop_en})\b"
            rf"|[,،]"
            rf"|$"
            rf")"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            original,
            flags=(
                re.IGNORECASE
                |
                re.UNICODE
            ),
        )

        if match:

            location = (
                match
                .group(1)
                .strip(
                    " .،,"
                )
            )

            if location:
                return (
                    _normalize_location_alias(
                        location
                    )
                )

    return None


def _canonicalize_existing_poi_constraints(
    existing: list,
) -> list[str]:

    result: list[str] = []

    for value in _ensure_list(
        existing
    ):

        raw = (
            _normalize_text(
                value
            )
            .casefold()
        )

        if not raw:
            continue

        if (
            raw
            in ALLOWED_POI_VALUES
        ):

            if (
                raw
                not in result
            ):
                result.append(
                    raw
                )

            continue

        relation: str | None = None

        if (
            raw.startswith(
                "nearby "
            )
            or raw.startswith(
                "near "
            )
        ):
            relation = "near"

        elif (
            raw.startswith(
                "far from "
            )
            or raw.startswith(
                "far "
            )
        ):
            relation = "far"

        for definition in POI_DEFINITIONS.values():

            if any(
                _contains_alias(
                    raw,
                    alias,
                )
                for alias
                in definition[
                    "aliases"
                ]
            ):

                canonical = (
                    definition[
                        relation
                        or "near"
                    ]
                )

                if (
                    canonical
                    not in result
                ):
                    result.append(
                        canonical
                    )

                break

    return result


def _detect_poi_constraints_from_text(
    text: str,
    existing: list | None = None,
) -> list[str]:

    result = (
        _canonicalize_existing_poi_constraints(
            existing
            or []
        )
    )

    for (
        relation,
        segment,
    ) in _poi_relation_segments(
        text
    ):

        for definition in POI_DEFINITIONS.values():

            if any(
                _contains_alias(
                    segment,
                    alias,
                )
                for alias
                in definition[
                    "aliases"
                ]
            ):

                canonical = (
                    definition[
                        relation
                    ]
                )

                if (
                    canonical
                    not in result
                ):
                    result.append(
                        canonical
                    )

    return result


def _normalize_llm_currency(
    value: Any,
) -> str | None:

    if not value:
        return None

    currency = (
        str(
            value
        )
        .strip()
        .upper()
    )

    mapping = {
        "DIRHAM":
            "AED",

        "DIRHAMS":
            "AED",

        "UAE DIRHAM":
            "AED",

        "UAE DIRHAMS":
            "AED",

        "درهم":
            "AED",

        "د.إ":
            "AED",

        "DOLLAR":
            "USD",

        "DOLLARS":
            "USD",

        "دولار":
            "USD",
    }

    return mapping.get(
        currency,
        currency,
    )


def _normalize_confidence(
    value: Any,
) -> float:

    try:
        confidence = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        confidence = 0.0

    return max(
        0.0,

        min(
            1.0,
            confidence,
        ),
    )


def _has_poi_conflict(
    values: list[str],
) -> bool:

    selected = set(
        values
    )

    for definition in POI_DEFINITIONS.values():

        if (
            definition[
                "near"
            ]
            in selected

            and

            definition[
                "far"
            ]
            in selected
        ):
            return True

    return False


def parse_query(
    request: QueryRequest,
) -> ParsedCriteria:

    search_text = (
        _normalize_text(
            request.raw_text
        )
    )

    explicit_property_type = (
        _detect_property_type_from_text(
            search_text
        )
    )

    explicit_action_type = (
        _detect_action_type_from_text(
            search_text
        )
    )

    (
        explicit_min_budget,
        explicit_max_budget,
    ) = (
        _extract_budget_from_text(
            search_text
        )
    )

    explicit_currency = (
        _detect_currency_from_text(
            search_text
        )
    )

    (
        explicit_min_bedrooms,
        explicit_max_bedrooms,
    ) = (
        _detect_bedrooms_from_text(
            search_text
        )
    )

    explicit_location = (
        _detect_location_from_text(
            search_text
        )
    )

    explicit_poi_constraints = (
        _detect_poi_constraints_from_text(
            search_text,
            [],
        )
    )

    explicit_filter_count = sum(
        [
            explicit_property_type
            is not None,

            explicit_action_type
            is not None,

            (
                explicit_min_budget
                is not None
                or
                explicit_max_budget
                is not None
            ),

            (
                explicit_min_bedrooms
                is not None
                or
                explicit_max_bedrooms
                is not None
            ),

            explicit_location
            is not None,

            bool(
                explicit_poi_constraints
            ),
        ]
    )

    explicit_conflict = (
        _has_poi_conflict(
            explicit_poi_constraints
        )
    )

    if (
        explicit_filter_count
        >= 2
    ):

        confidence = (
            0.95
            if explicit_filter_count
            >= 4
            else 0.90
        )

        return ParsedCriteria(
            property_type=
                explicit_property_type,

            action_type=
                explicit_action_type,

            min_budget=
                explicit_min_budget,

            max_budget=
                explicit_max_budget,

            budget_currency=
                explicit_currency,

            min_bedrooms=
                explicit_min_bedrooms,

            max_bedrooms=
                explicit_max_bedrooms,

            vibe_tags=
                [],

            required_amenities=
                explicit_poi_constraints,

            location_hint=
                explicit_location,

            confidence=
                confidence,

            needs_clarification=
                explicit_conflict,
        )

    raw: dict[
        str,
        Any,
    ] = {}

    try:

        llm_result = (
            call_json(
                SYSTEM_PROMPT,
                request.raw_text,
            )
        )

        if isinstance(
            llm_result,
            dict,
        ):
            raw = (
                llm_result
            )

    except DeepSeekUnavailableError:
        raw = {}

    property_type = (
        explicit_property_type
        or
        _canonical_property_type(
            raw.get(
                "property_type"
            )
        )
    )

    # Explicit-only:
    # Never allow the LLM to invent buy/rent/booking.
    action_type = (
        explicit_action_type
    )

    min_budget = (
        explicit_min_budget
    )

    max_budget = (
        explicit_max_budget
    )

    if (
        min_budget is None
        and
        max_budget is None
    ):

        min_budget = (
            _safe_float(
                raw.get(
                    "min_budget"
                )
            )
        )

        max_budget = (
            _safe_float(
                raw.get(
                    "max_budget"
                )
            )
        )

        if (
            min_budget
            is not None
            and
            max_budget
            is not None
            and
            min_budget
            > max_budget
        ):
            (
                min_budget,
                max_budget,
            ) = (
                max_budget,
                min_budget,
            )

    budget_currency = (
        explicit_currency
        or
        _normalize_llm_currency(
            raw.get(
                "budget_currency"
            )
        )
    )

    min_bedrooms = (
        explicit_min_bedrooms
    )

    max_bedrooms = (
        explicit_max_bedrooms
    )

    if (
        min_bedrooms is None
        and
        max_bedrooms is None
    ):

        min_bedrooms = (
            _safe_int(
                raw.get(
                    "min_bedrooms"
                )
            )
        )

        max_bedrooms = (
            _safe_int(
                raw.get(
                    "max_bedrooms"
                )
            )
        )

        if (
            min_bedrooms
            is not None
            and
            max_bedrooms
            is not None
            and
            min_bedrooms
            > max_bedrooms
        ):
            (
                min_bedrooms,
                max_bedrooms,
            ) = (
                max_bedrooms,
                min_bedrooms,
            )

    location_hint = (
        explicit_location
    )

    if (
        location_hint is None
        and
        raw.get(
            "location_hint"
        )
    ):

        location_hint = (
            _normalize_text(
                raw.get(
                    "location_hint"
                )
            )
            or None
        )

    poi_constraints = (
        _detect_poi_constraints_from_text(
            search_text,

            raw.get(
                "required_amenities"
            )
            or [],
        )
    )

    vibe_tags = [
        str(
            value
        ).strip()

        for value
        in _ensure_list(
            raw.get(
                "vibe_tags"
            )
        )

        if str(
            value
        ).strip()
    ]

    meaningful_filters = sum(
        [
            property_type
            is not None,

            action_type
            is not None,

            (
                min_budget
                is not None
                or
                max_budget
                is not None
            ),

            (
                min_bedrooms
                is not None
                or
                max_bedrooms
                is not None
            ),

            bool(
                location_hint
            ),

            bool(
                poi_constraints
            ),

            bool(
                vibe_tags
            ),
        ]
    )

    confidence = (
        _normalize_confidence(
            raw.get(
                "confidence",
                0.0,
            )
        )
    )

    if (
        meaningful_filters
        >= 4
    ):
        confidence = max(
            confidence,
            0.95,
        )

    elif (
        meaningful_filters
        >= 3
    ):
        confidence = max(
            confidence,
            0.90,
        )

    elif (
        meaningful_filters
        >= 2
    ):
        confidence = max(
            confidence,
            0.80,
        )

    elif (
        meaningful_filters
        == 1
    ):
        confidence = max(
            confidence,
            0.55,
        )

    needs_clarification = (
        meaningful_filters
        < 2

        or

        _has_poi_conflict(
            poi_constraints
        )
    )

    return ParsedCriteria(
        property_type=
            property_type,

        action_type=
            action_type,

        min_budget=
            min_budget,

        max_budget=
            max_budget,

        budget_currency=
            budget_currency,

        min_bedrooms=
            min_bedrooms,

        max_bedrooms=
            max_bedrooms,

        vibe_tags=
            vibe_tags,

        required_amenities=
            poi_constraints,

        location_hint=
            location_hint,

        confidence=
            confidence,

        needs_clarification=
            needs_clarification,
    )