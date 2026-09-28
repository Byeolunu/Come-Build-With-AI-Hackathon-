"""Profile extraction and persistence helpers for the CivicPilot demo."""

import re
from datetime import datetime, timezone

import certifi
from pymongo import MongoClient

from src.application.rag.models import UserProfile

# ---------------------------------------------------------------------------
# Country detection helpers
# ---------------------------------------------------------------------------

_COUNTRY_KEYWORDS: dict[str, str] = {
    # Morocco
    "morocco": "MA", "maroc": "MA", "المغرب": "MA", "mad": "MA", "dirham": "MA",
    # France
    "france": "FR", "français": "FR", "française": "FR",
    # Tunisia
    "tunisia": "TN", "tunisie": "TN", "تونس": "TN", "dinar": "TN",
    # Algeria
    "algeria": "DZ", "algérie": "DZ", "الجزائر": "DZ",
    # Senegal
    "senegal": "SN", "sénégal": "SN",
    # Generic
    "netherlands": "NL", "nederland": "NL",
    "germany": "DE", "allemagne": "DE",
    "spain": "ES", "espagne": "ES",
}

_CITY_TO_REGION: dict[str, tuple[str, str, str]] = {
    # (city_display, region, country_code)
    "casablanca": ("Casablanca", "Casablanca-Settat", "MA"),
    "rabat": ("Rabat", "Rabat-Salé-Kénitra", "MA"),
    "marrakech": ("Marrakech", "Marrakech-Safi", "MA"),
    "fes": ("Fès", "Fès-Meknès", "MA"),
    "fez": ("Fès", "Fès-Meknès", "MA"),
    "tanger": ("Tanger", "Tanger-Tétouan-Al Hoceïma", "MA"),
    "agadir": ("Agadir", "Souss-Massa", "MA"),
    "oujda": ("Oujda", "Oriental", "MA"),
    "tunis": ("Tunis", "Tunis", "TN"),
    "paris": ("Paris", "Île-de-France", "FR"),
    "lyon": ("Lyon", "Auvergne-Rhône-Alpes", "FR"),
    "algiers": ("Algiers", "Alger", "DZ"),
    "alger": ("Alger", "Alger", "DZ"),
    "dakar": ("Dakar", "Dakar", "SN"),
}

_CURRENCY_PATTERNS = [
    (r"(?:\b|\s)(\d[\d\s.,]*)\s*(?:mad|dh|dhs|dirhams?|درهم)", "MAD"),
    (r"(?:\b|\s)(\d[\d\s.,]*)\s*(?:euro?s?|€)", "EUR"),
    (r"(?:\b|\s)(\d[\d\s.,]*)\s*(?:dinars?|دينار)", "TND"),
    (r"(?:\b|\s)(\d[\d\s.,]*)\s*(?:fcfa|xof)", "XOF"),
]


def extract_profile(message: str) -> UserProfile:  # noqa: PLR0912, PLR0915
    """Extract high-confidence fields from a user message without inventing unknown values."""
    text = message.lower()
    profile = UserProfile()

    # Employment
    if any(w in text for w in ("unemployed", "sans emploi", "chômeur", "chômeuse", "عاطل", "بدون عمل")):
        profile.employment["status"] = "unemployed"
    elif any(w in text for w in ("employed", "salarié", "employee", "موظف")):
        profile.employment["status"] = "employed"
    elif any(w in text for w in ("student", "étudiant", "étudiante", "طالب", "طالبة")):
        profile.employment["status"] = "student"

    # Business goal
    if any(w in text for w in ("start", "ouvrir", "créer", "launch", "افتتاح", "بدء", "فتح")):
        profile.goal["type"] = "start_business"
    elif any(w in text for w in ("expand", "grow", "développer", "agrandir", "توسيع")):
        profile.goal["type"] = "grow_business"
    elif any(w in text for w in ("training", "formation", "تكوين", "تدريب")):
        profile.goal["type"] = "training"

    # Sector detection (generic, not just bakery)
    sectors = {
        "food": ("bakery", "boulangerie", "restaurant", "food", "alimentaire", "café", "patisserie", "خباز", "مخبزة", "مطعم"),
        "tech": ("tech", "software", "app", "it", "digital", "web", "startup", "تقنية"),
        "retail": ("shop", "boutique", "commerce", "magasin", "متجر", "محل"),
        "agriculture": ("farm", "agriculture", "ferme", "زراعة", "فلاحة"),
        "handicraft": ("artisan", "craft", "artisanat", "handmade", "حرفي", "صناعة تقليدية"),
        "transport": ("transport", "taxi", "logistique", "نقل"),
    }
    for sector, keywords in sectors.items():
        if any(k in text for k in keywords):
            profile.goal["sector"] = sector
            break

    # Country detection
    for keyword, country_code in _COUNTRY_KEYWORDS.items():
        if keyword in text:
            profile.personal["country"] = country_code
            break

    # City/region detection (overrides country if more specific)
    for city_key, (city_display, region, country_code) in _CITY_TO_REGION.items():
        if city_key in text:
            profile.personal["city"] = city_display
            profile.personal["region"] = region
            profile.personal["country"] = country_code
            break

    # Debt constraint
    if any(w in text for w in (
        "cannot take a loan", "can't take a loan", "no loan", "sans prêt", "sans emprunt",
        "لا أستطيع الاقتراض", "don't want a loan", "not a loan", "pas de prêt",
    )):
        profile.constraints["cannot_take_debt"] = True
    elif any(w in text for w in (
        "can repay", "accept a loan", "willing to repay", "j'accepte un prêt",
        "je peux rembourser", "أستطيع سداد", "ok with loan", "open to loan",
    )):
        profile.constraints["cannot_take_debt"] = False

    # Amount extraction (try multiple currencies)
    for pattern, currency in _CURRENCY_PATTERNS:
        amount_match = re.search(pattern, text)
        if amount_match:
            raw_amount = re.sub(r"[^0-9]", "", amount_match.group(1))
            if raw_amount:
                profile.financial_need["amount"] = float(raw_amount)
                profile.financial_need["currency"] = currency
                break

    # Age extraction
    age_patterns = [
        r"(?:i(?:'m| am|m)|im)\s+(\d{1,2})\s*(?:years?\s*old)?",  # I'm 21, im 21, I am 21 years old
        r"(\d{1,2})\s*years?\s*old",  # 21 years old
        r"age\s*[:=]?\s*(\d{1,2})",  # age: 21, age 21
        r"j'ai\s+(\d{1,2})\s*ans",  # j'ai 21 ans
        r"(\d{1,2})\s*ans",  # 21 ans
        r"عمري\s*(\d{1,2})",  # عمري 21
        r"(\d{1,2})\s*سنة",  # 21 سنة
        r"عندي\s*(\d{1,2})\s*(?:سنة|عام)",  # عندي 21 سنة
    ]
    for pattern in age_patterns:
        age_match = re.search(pattern, text)
        if age_match:
            age = int(age_match.group(1))
            if 14 <= age <= 99:  # reasonable age range  # noqa: PLR2004
                profile.personal["age"] = age
                break

    # Gender detection
    if any(w in text for w in ("female", "woman", "femme", "امرأة", "أنثى", "بنت")):
        profile.personal["gender"] = "female"
    elif any(w in text for w in ("male", "man", "homme", "رجل", "ذكر")):
        profile.personal["gender"] = "male"

    # Business stage
    if any(w in text for w in ("idea", "idée", "فكرة", "just an idea", "planning")):
        profile.goal["stage"] = "idea"
    elif any(w in text for w in ("registered", "enregistré", "auto-entrepreneur", "مسجل", "سجل تجاري")):
        profile.goal["stage"] = "registered"
    elif any(w in text for w in ("operating", "running", "existing business", "en activité", "نشاط قائم")):
        profile.goal["stage"] = "operating"

    # Compute missing fields
    missing = []
    if profile.personal.get("age") is None:
        missing.append("personal.age")
    if profile.personal.get("country") is None:
        missing.append("personal.country")
    if profile.personal.get("region") is None:
        missing.append("personal.region")
    if profile.financial_need.get("amount") is None:
        missing.append("financial_need.amount")
    if profile.constraints.get("cannot_take_debt") is None:
        missing.append("constraints.cannot_take_debt")
    profile.missing_information = missing
    return profile


def merge_profiles(old: UserProfile | None, new: UserProfile) -> UserProfile:
    if old is None:
        return new
    data = old.model_dump()
    incoming = new.model_dump()
    for section, values in incoming.items():
        if isinstance(values, dict):
            for key, value in values.items():
                if value is not None and value != []:
                    data[section][key] = value
    missing = []
    if data["personal"].get("age") is None:
        missing.append("personal.age")
    if data["personal"].get("country") is None:
        missing.append("personal.country")
    if data["personal"].get("region") is None:
        missing.append("personal.region")
    if data["financial_need"].get("amount") is None:
        missing.append("financial_need.amount")
    if data["constraints"].get("cannot_take_debt") is None:
        missing.append("constraints.cannot_take_debt")
    data["missing_information"] = missing
    return UserProfile.model_validate(data)


def missing_questions(profile: UserProfile) -> list[str]:
    questions = {
        "personal.age": "How old are you? / Quel âge avez-vous ? / كم عمرك؟",
        "personal.country": "Which country are you located in? / Dans quel pays êtes-vous situé(e) ? / في أي بلد أنت موجود(ة)؟",
        "personal.region": "Which city or region are you in? / Dans quelle ville ou région êtes-vous ? / في أي مدينة أو منطقة أنت؟",
        "financial_need.amount": (
            "How much funding do you need, and in which currency? / "
            "De combien avez-vous besoin, et en quelle devise ? / "
            "كم المبلغ الذي تحتاجه وبأي عملة؟"
        ),
        "constraints.cannot_take_debt": (
            "Can you repay a loan, or do you only want grants and non-repayable support? / "
            "Pouvez-vous rembourser un prêt, ou souhaitez-vous uniquement des subventions ? / "
            "هل يمكنك سداد قرض، أم تريد دعماً غير قابل للسداد فقط؟"
        ),
    }
    return [questions[field] for field in profile.missing_information if field in questions]


class ProfileRepository:
    def __init__(self, mongodb_uri: str, database_name: str = "come_build_with_ai"):
        # tlsCAFile=certifi.where() provides proper CA verification.
        # tlsAllowInvalidCertificates is intentionally NOT set (defaults to False)
        # to maintain a secure TLS connection to MongoDB Atlas.
        self.collection = MongoClient(
            mongodb_uri,
            tlsCAFile=certifi.where(),
        )["come_build_with_ai"]["user_profiles"]

    def get(self, session_id: str) -> UserProfile | None:
        document = self.collection.find_one({"session_id": session_id})
        return UserProfile.model_validate(document["profile"]) if document else None

    def save(self, session_id: str, profile: UserProfile) -> None:
        now = datetime.now(timezone.utc)
        self.collection.update_one(
            {"session_id": session_id},
            {"$set": {"profile": profile.model_dump(), "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
