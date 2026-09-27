"""
Person 2 — ADAPTATEUR entre le backend de Person 4 (app.py, schemas.Case, contracts.py)
et l'orchestrateur civicpilot_orchestrator.py, réutilisé SANS modification.

    extract_profile(text, language=None, case=None)        -> dict au format schemas.Case
    generate_final_response(profile, rag_result, language)  -> final_response (contracts.py) + "question"

Mêmes garde-fous que analyze_case : masquage CIN/téléphone, blocage des injections, hors-sujet,
validation du profil, anti-hallucination, garde anti-dette, formulations prudentes, réponse de secours.
"""
import os, sys, json, re, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # racine du projet
import civicpilot_orchestrator as o

logger = logging.getLogger("case_analyzer.ai_workflow")

NO_PROGRAMS = {
    "fr": "Aucun programme ne semble correspondre pour l'instant. Précisez votre situation ou contactez un guichet d'accompagnement.",
    "en": "No program appears to match for now. Add details about your situation or contact a local support office.",
    "ar": "لا يبدو أن أي برنامج يناسب ملفك حالياً. أضف تفاصيل عن وضعك أو تواصل مع شباك المواكبة.",
    "darija": "حتى برنامج ما باين مناسب دابا. زيد شي تفاصيل على الوضعية ديالك ولا تواصل مع شي شباك ديال المواكبة.",
}
# Réponses négatives -> experience.relevant_experience = False (schemas.py exige un booléen)
NEG_EXPERIENCE = re.compile(r"^\s*(non|no|none|nothing|aucune?|pas\b|sans\b|jamais|never|لا|بدون|ما عندي|ماعندي|والو|walou|ma3ndi)", re.I)


def _experience_bool(v):
    """L'orchestrateur décrit l'expérience en texte ; le schéma de Person 4 veut True/False/None."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, str) and v.strip():
        return not NEG_EXPERIENCE.search(v)
    return None


def _essential_missing(profile):
    """Nos 5 champs essentiels encore vides (pas la liste complète de schemas.Case.compute_missing,
    qui contient aussi des champs sensibles qu'on ne demande jamais)."""
    return [f for f in o.required_fields(profile) if o.get(profile, f) is None]


def _empty(lang):
    p = o.merge(None, o.normalize({}))
    p["personal"]["language"] = lang
    return p


def extract_profile(text, language=None, case=None):
    """Texte libre -> profil au format schemas.Case. Ne lève pas d'exception sur une injection
    ou un hors-sujet (profil vide) ; lève une exception si le LLM est indisponible (app.py la gère)."""
    case = case or {}
    prev_lang = o.get(case, "personal.language") if o.get(case, "personal.language") in o.LANGS else None
    hint = prev_lang or (language if language in o.LANGS else None)
    message = o.scrub_pii(text or "")

    # Tentative d'injection : bloquée avant tout appel au LLM
    if o.INJECTION_RE.search(message):
        logger.warning("extract_profile: tentative d'injection bloquée")
        return _empty(o.guess_language(message, hint))

    # Réponse courte ("27") : contexte = question posée, c.-à-d. le 1er champ essentiel manquant du case
    extracted = o.quick_number(message, {"missing_information": _essential_missing(case)}, hint) if case else None
    if extracted is None:
        extracted = o.llm_json(o.EXTRACT_SYSTEM, message)
    lang = extracted.get("language") or hint or "fr"
    # Stabilité de langue pour les réponses courtes : seulement la langue du tour précédent (case),
    # pas le paramètre language, qu'app.py met à "en" par défaut
    if prev_lang and len(message.split()) < 3:
        lang = prev_lang
    lang = lang if lang in o.LANGS else "fr"

    raw = extracted.get("profile") or {}
    new = o.normalize(raw)
    if extracted.get("on_topic") is False and not any(o.get(new, f) not in (None, []) for f in o.FIELD_PATHS):
        logger.info("extract_profile: message hors-sujet")
        return _empty(lang)

    merged = o.merge(case, new)
    # Champs propres au schéma de Person 4, perdus par normalize : on les recalcule
    exp = _experience_bool(o.get(raw, "experience.relevant_experience"))
    merged["experience"]["relevant_experience"] = exp if exp is not None else _experience_bool(
        o.get(case, "experience.relevant_experience"))
    merged["personal"]["language"] = lang
    return merged


# --------------------------------------------------------------------------- #
# rag_result de Person 3 -> format de programmes de l'orchestrateur
# --------------------------------------------------------------------------- #
def _to_programs(rag_result):
    matches = {m.get("program_id"): m for m in rag_result.get("matches", []) if isinstance(m, dict)}
    evidence = {}
    for e in rag_result.get("evidence", []):
        if isinstance(e, dict) and e.get("source_url"):
            evidence.setdefault(e.get("program_id"), []).append(
                {"url": e["source_url"], "verified_on": e.get("verification_date"), "excerpt": e.get("snippet")})
    out = []
    for p in rag_result.get("programs", []):
        if not isinstance(p, dict):
            out.append(p)  # sera rejeté et journalisé par validate_programs
            continue
        m = matches.get(p.get("id"))
        failed = (m or {}).get("failed_requirements") or []
        missing = (m or {}).get("missing_requirements") or []
        # Sans résultat des règles pour ce programme, on ne prétend jamais qu'il correspond : "partial"
        status = "no_match" if failed else "partial" if (m is None or missing) else "likely_match"
        amount = f"{p['max_amount']} {p.get('currency') or ''}".strip() if p.get("max_amount") else None
        out.append({"id": p.get("id"), "name": p.get("name"), "type": p.get("type"),
                    "provider": p.get("official_contact"), "amount_range": amount, "match_status": status,
                    "score": (m or {}).get("score") or 0,
                    "matched_requirements": (m or {}).get("matched_requirements") or [],
                    "missing_requirements": missing, "failed_requirements": failed, "warnings": [],
                    "documents": p.get("required_documents") or [], "deadline": p.get("deadline"),
                    "contact": p.get("official_contact"), "sources": evidence.get(p.get("id"), [])})
    return out


def generate_final_response(profile, rag_result, language=None):
    """Sortie selon contracts.py : {language, summary, ranked_programs, checklist, disclaimer} + question."""
    profile = profile or {}
    lang = o.get(profile, "personal.language")
    lang = lang if lang in o.LANGS else language if language in o.LANGS else "fr"

    programs, invalid = o.validate_programs({"programs": _to_programs(rag_result or {})})
    if invalid:
        logger.warning(f"generate_final_response: programmes ignorés {invalid}")
    # Tri déterministe : statut calculé par les règles, puis score de Person 3
    programs.sort(key=lambda p: (o.ORDER[p["match_status"]], -(p.get("score") or 0)))

    if not programs:
        answer = {"summary": NO_PROGRAMS[lang], "recommendations": [], "action_plan": [], "assumptions": []}
    else:
        try:
            answer = o.llm_json(o.ANSWER_SYSTEM.format(lang_name=o.LANG_NAMES[lang]),
                                json.dumps({"profile": profile, "programs": programs}, ensure_ascii=False,
                                           separators=(",", ":"), default=str),
                                temperature=0.3)
        except Exception as e:
            logger.warning(f"generate_final_response: LLM indisponible, réponse de secours ({e})")
            answer = o.fallback_answer(programs, lang, profile)
    answer = o.verify(o.sanitize(answer), programs, profile, lang)
    # Même ordre (déterministe) pour ranked_programs et checklist, quel que soit l'ordre du LLM
    order = {p["id"]: i for i, p in enumerate(programs)}
    answer["recommendations"].sort(key=lambda r: order[r["program_id"]])
    recs = answer["recommendations"]
    checklist = o.build_checklist(answer, programs)
    missing = _essential_missing(profile)
    return {
        "language": lang,
        "summary": answer["summary"],
        "ranked_programs": [{"program_id": r["program_id"], "why": r["why"],
                             "risk_notes": " ; ".join(str(x) for x in r["risks"])} for r in recs],
        "checklist": [{"program_id": c["program_id"], "documents": c["documents"],
                       "deadline": c["deadline"], "official_contact": c["contact"]} for c in checklist["programs"]],
        "disclaimer": o.DISCLAIMERS[lang],
        "question": o.QUESTIONS[lang][missing[0]] if missing else None,
    }
