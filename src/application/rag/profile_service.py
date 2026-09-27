"""Profile extraction and persistence helpers for the CivicPilot demo."""

import re
from datetime import datetime, timezone

from pymongo import MongoClient

from src.application.rag.models import UserProfile


def extract_profile(message: str) -> UserProfile:
    """Extract high-confidence fields without inventing unknown values."""
    text = message.lower()
    profile = UserProfile()
    if any(word in text for word in ("unemployed", "sans emploi", "chômeur", "عاطل")):
        profile.employment["status"] = "unemployed"
    if any(word in text for word in ("bakery", "boulangerie", "خباز", "مخبزة")):
        profile.goal.update({"type": "start_business", "sector": "food", "description": "bakery"})
    if any(word in text for word in ("morocco", "maroc", "المغرب", "mad")):
        profile.personal["country"] = "MA"
    regions = {
        "casablanca": "Casablanca-Settat",
        "rabat": "Rabat-Salé-Kénitra",
        "marrakech": "Marrakech-Safi",
        "fes": "Fès-Meknès",
        "fez": "Fès-Meknès",
        "tanger": "Tanger-Tétouan-Al Hoceïma",
    }
    for city, region in regions.items():
        if city in text:
            profile.personal["city"] = city.title()
            profile.personal["region"] = region
            profile.personal["country"] = "MA"
            break
    if any(word in text for word in ("cannot take a loan", "can't take a loan", "no loan", "sans prêt", "sans emprunt", "لا أستطيع الاقتراض")):
        profile.constraints["cannot_take_debt"] = True
    elif any(word in text for word in ("can repay", "accept a loan", "willing to repay", "j'accepte un prêt", "je peux rembourser", "أستطيع سداد")):
        profile.constraints["cannot_take_debt"] = False
    amount = re.search(r"(?:\b|\s)(\d[\d\s.,]*)\s*(?:mad|dh|dhs|dirhams?|دراهم?)", text)
    if amount:
        raw_amount = re.sub(r"[^0-9]", "", amount.group(1))
        profile.financial_need.update({"amount": float(raw_amount), "currency": "MAD"})
    missing = []
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
        "personal.country": "Which country are you located in? / Dans quel pays êtes-vous situé(e) ?",
        "personal.region": "Which city or region are you located in? / Dans quelle ville ou région êtes-vous situé(e) ?",
        "financial_need.amount": "How much funding do you need, and in which currency?",
        "constraints.cannot_take_debt": "Can you repay a loan, or do you only want grants and non-repayable support?",
    }
    return [questions[field] for field in profile.missing_information if field in questions]


class ProfileRepository:
    def __init__(self, mongodb_uri: str, database_name: str = "come_build_with_ai"):
        self.collection = MongoClient(mongodb_uri)[database_name]["user_profiles"]

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
