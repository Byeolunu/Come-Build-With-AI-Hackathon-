"""
CivicPilot — Person 2 : AI workflow & orchestration  (v2 — profil imbriqué de l'équipe)
Point d'entrée pour Person 4 :  analyze_case(message, profile=None, language=None) -> dict

Pipeline : langue + extraction -> validation/fusion -> question manquante
           -> find_programs (Person 3) -> réponse LLM -> vérification -> sortie JSON

pip install openai
export LLM_PROVIDER=groq  &&  export GROQ_API_KEY=...
(ou LLM_PROVIDER=nvidia + NVIDIA_API_KEY, ou LLM_PROVIDER=ollama en local)
"""
import os, json, re, time, copy
from openai import OpenAI

try:  # charge la clé API depuis le fichier .env (pip install python-dotenv)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ------------------------------------------------------------------ #
# 1. Config LLM — toute API compatible OpenAI. Vérifiez les noms de modèles.
# ------------------------------------------------------------------ #
PROVIDERS = {
    "groq":   {"base_url": "https://api.groq.com/openai/v1",      "key": "GROQ_API_KEY",   "model": "llama-3.3-70b-versatile"},
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "key": "NVIDIA_API_KEY", "model": "meta/llama-3.3-70b-instruct"},
    "ollama": {"base_url": "http://localhost:11434/v1",           "key": None,             "model": "llama3.1:8b"},
}
PROVIDER = os.getenv("LLM_PROVIDER", "groq")
_cfg = PROVIDERS[PROVIDER]
client = OpenAI(base_url=_cfg["base_url"],
                api_key=os.getenv(_cfg["key"]) if _cfg["key"] else "ollama")
MODEL = os.getenv("LLM_MODEL", _cfg["model"])
# Modèle de secours si le principal atteint sa limite de débit / quota (429)
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
# Les modèles gpt-oss "réfléchissent" avant de répondre : "low" réduit fortement la latence
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")

# ------------------------------------------------------------------ #
# 2. Contrat de données — format de l'équipe
# ------------------------------------------------------------------ #
EMPTY_PROFILE = {
    "personal":       {"age": None, "country": None, "region": None, "city": None},
    "employment":     {"status": None, "occupation": None},
    "goal":           {"type": None, "sector": None, "description": None, "stage": None},
    "financial_need": {"amount": None, "currency": None, "purpose": None},
    "business":       {"existing": None, "has_business_plan": None, "has_business_registration": None},
    "experience":     {"relevant_experience": None, "skills": []},
    "eligibility":    {"student": None, "low_income": None, "disability": None,
                       "refugee": None, "rural_resident": None},
    "constraints":    {"cannot_take_debt": None, "other": []},
    "missing_information": [],
}

# Valeurs autorisées : à partager avec Person 3 pour que ses règles utilisent les mêmes mots
ENUMS = {
    "employment.status": {"unemployed", "employed", "self_employed", "student", "informal"},
    "goal.type":         {"start_business", "grow_business", "training", "savings", "credit", "job_search"},
    "goal.stage":        {"idea", "planning", "operating"},
}
INT_PATHS  = {"personal.age"}
NUM_PATHS  = {"financial_need.amount"}
LIST_PATHS = {"experience.skills", "constraints.other"}
BOOL_PATHS = {"business.existing", "business.has_business_plan", "business.has_business_registration",
              "eligibility.student", "eligibility.low_income", "eligibility.disability",
              "eligibility.refugee", "eligibility.rural_resident", "constraints.cannot_take_debt"}
DEFAULTS   = {"personal.country": "MA", "financial_need.currency": "MAD"}
NEEDS_AMOUNT = {"start_business", "grow_business", "credit"}
CREDIT_TYPES = {"microcredit", "loan", "credit"}  # types de programmes qui créent une dette


def _paths(d, prefix=""):
    for k, v in d.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from _paths(v, p + ".")
        else:
            yield p

FIELD_PATHS = [p for p in _paths(EMPTY_PROFILE) if p != "missing_information"]


def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def put(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def required_fields(p):
    """Le montant n'est obligatoire que si l'objectif implique un financement."""
    req = ["personal.city", "personal.age", "employment.status", "goal.type"]
    if get(p, "goal.type") in NEEDS_AMOUNT or get(p, "goal.type") is None:
        req.append("financial_need.amount")
    return req


LANGS = {"fr", "en", "ar", "darija"}
LANG_NAMES = {"fr": "français", "en": "English", "ar": "العربية الفصحى",
              "darija": "الدارجة المغربية (بالحروف العربية)"}

# Questions déterministes (on ne demande JAMAIS les champs "eligibility" sensibles)
# Formulations neutres en genre : noms plutôt que verbes/adjectifs accordés au masculin
QUESTIONS = {
    "fr": {"personal.city": "Dans quelle ville habitez-vous ?",
           "personal.age": "Quel âge avez-vous ?",
           "employment.status": "Quelle est votre situation actuelle (sans emploi, emploi salarié, études, activité indépendante) ?",
           "goal.type": "Quel est votre objectif : créer un projet, développer une activité, vous former, épargner ou obtenir un crédit ?",
           "financial_need.amount": "De combien avez-vous besoin environ (en dirhams) ?"},
    "en": {"personal.city": "Which city do you live in?",
           "personal.age": "How old are you?",
           "employment.status": "What is your current situation (unemployed, employed, student, self-employed)?",
           "goal.type": "What is your goal: start a business, grow one, get training, save, or get credit?",
           "financial_need.amount": "Roughly how much do you need (in MAD)?"},
    "ar": {"personal.city": "ما هي مدينة إقامتك؟",
           "personal.age": "كم عمرك؟",
           "employment.status": "ما هو وضعك المهني حالياً (بدون عمل، عمل مأجور، دراسة، عمل مستقل)؟",
           "goal.type": "ما هو هدفك: إنشاء مشروع، تطوير نشاط، تكوين، ادخار أو قرض؟",
           "financial_need.amount": "ما هو المبلغ التقريبي المطلوب بالدرهم؟"},
    "darija": {"personal.city": "شنو هي المدينة ديالك؟",
               "personal.age": "شحال فعمرك؟",
               "employment.status": "شنو هي الوضعية ديالك دابا: خدمة، بلا خدمة، قراية، ولا خدمة على الراس؟",
               "goal.type": "شنو هو الهدف ديالك: مشروع جديد، تكبير نشاط، تكوين، توفير ولا كريدي؟",
               "financial_need.amount": "شحال ديال الفلوس خاصك تقريبا بالدرهم؟"},
}
DISCLAIMERS = {
    "fr": "CivicPilot donne une orientation, pas une décision officielle. Confirmez toujours l'éligibilité auprès de l'organisme concerné.",
    "en": "CivicPilot provides guidance, not an official decision. Always confirm eligibility with the official provider.",
    "ar": "يقدم CivicPilot توجيهاً فقط وليس قراراً رسمياً. يرجى دائماً التأكد من الأهلية لدى الجهة المعنية.",
    "darija": "CivicPilot كيعطيك توجيه، ماشي قرار رسمي. ديما تأكد من الشروط عند الجهة المعنية.",
}
REPAY_RISK = {
    "fr": "Crédit : il faudra rembourser chaque mois, intérêts compris, même si l'activité ne rapporte pas encore.",
    "en": "Credit: it must be repaid every month, with interest, even if the activity is not yet profitable.",
    "ar": "قرض: يجب سداده شهرياً مع الفوائد، حتى لو لم يحقق النشاط أرباحاً بعد.",
    "darija": "كريدي: خاصو يترجع كل شهر مع الفوائد، واخا المشروع مازال ماكيربحش.",
}
# Réponse polie qui recentre (hors-sujet ou tentative d'injection)
REFOCUS = {
    "fr": "Je suis CivicPilot et je peux seulement vous aider à trouver des programmes officiels "
          "(subventions, microcrédit, formations) au Maroc. Décrivez-moi votre situation et votre projet.",
    "en": "I'm CivicPilot and I can only help you find official programs (grants, microcredit, training) "
          "in Morocco. Tell me about your situation and your project.",
    "ar": "أنا CivicPilot، ويمكنني فقط مساعدتك في إيجاد برامج رسمية (منح، قروض صغرى، تكوين) في المغرب. "
          "صف لي وضعك ومشروعك.",
    "darija": "أنا CivicPilot، نقدر غير نعاونك تلقى برامج رسمية (دعم، قروض صغرى، تكوين) فالمغرب. "
              "عاود ليا على الوضعية ديالك والمشروع ديالك.",
}
INJECTION_RE = re.compile(
    r"(ignore|oublie|forget|disregard|bypass)\W+(\w+\W+){0,3}(instructions?|règles|rules|prompt|consignes)"
    r"|system\s*prompt|prompt\s*système|developer\s*mode|jailbreak|\bDAN\b"
    r"|(you are|tu es) (now|maintenant|désormais)\b|act as|agis comme|fais comme si"
    r"|(تجاهل|انس|انسى|نسى)\S*\s+(\S+\s+){0,3}(التعليمات|الأوامر|القواعد|التوجيهات)",
    re.I)
DARIJA_HINTS = re.compile(r"\b(bghit|khass\w*|ma?khdam\w*|wach|dyal|3ndi)\b|بغيت|ديال|شنو|واش|خاصني|ماخدامش|فين", re.I)
EN_HINTS = re.compile(r"\b(the|you|your|i|my|and|is|are|what|please)\b", re.I)

def guess_language(message, fallback=None):
    """Langue sans LLM (pour les messages bloqués avant l'extraction)."""
    if DARIJA_HINTS.search(message):
        return "darija"
    if re.search(r"[؀-ۿ]", message):
        return "ar"
    if fallback in LANGS:
        return fallback
    return "en" if EN_HINTS.search(message) else "fr"


FALLBACK_SUMMARY = {
    "fr": "Voici les programmes qui semblent correspondre à votre profil, d'après les sources officielles.",
    "en": "Here are the programs that appear to match your profile, based on official sources.",
    "ar": "هذه البرامج التي يبدو أنها تناسب ملفك حسب المصادر الرسمية.",
    "darija": "هادو هوما البرامج اللي باين كيناسبو الملف ديالك حسب المصادر الرسمية.",
}

# ------------------------------------------------------------------ #
# 3. Prompts
# ------------------------------------------------------------------ #
EXTRACT_SYSTEM = """Tu es l'extracteur d'informations de CivicPilot, un assistant d'inclusion financière au Maroc.
Lis le message (arabe, darija, français ou anglais) et renvoie UNIQUEMENT un objet JSON valide, sans texte autour.

Format :
{"language": "fr"|"en"|"ar"|"darija",
 "on_topic": boolean,
 "profile": {
  "personal": {"age": integer|null, "country": string|null, "region": string|null, "city": string|null},
  "employment": {"status": "unemployed"|"employed"|"self_employed"|"student"|"informal"|null,
                 "occupation": string|null},
  "goal": {"type": "start_business"|"grow_business"|"training"|"savings"|"credit"|"job_search"|null,
           "sector": string|null, "description": string|null,
           "stage": "idea"|"planning"|"operating"|null},
  "financial_need": {"amount": number|null, "currency": string|null, "purpose": string|null},
  "business": {"existing": boolean|null, "has_business_plan": boolean|null,
               "has_business_registration": boolean|null},
  "experience": {"relevant_experience": string|null, "skills": [string]},
  "eligibility": {"student": boolean|null, "low_income": boolean|null, "disability": boolean|null,
                  "refugee": boolean|null, "rural_resident": boolean|null},
  "constraints": {"cannot_take_debt": boolean|null, "other": [string]}
 }}

Règles :
- null (ou liste vide) si l'information n'est PAS explicitement donnée. N'invente jamais.
- Bloc "eligibility" : remplis-le UNIQUEMENT si l'utilisateur le dit lui-même. Ne déduis jamais
  un faible revenu du chômage, ni un handicap, ni un statut de réfugié.
- Montants en nombre : "3000 dh", "3 000 MAD", "3k" -> 3000 ; currency "MAD" si dirhams.
- "je ne veux pas m'endetter", "pas de crédit" -> constraints.cannot_take_debt = true.
- Ville en français standard (ex. "Casa", "الدار البيضاء" -> "Casablanca").
- Darija (écriture arabe ou latine) -> language "darija".
- N'extrais jamais de numéro de CIN, de compte bancaire ou de téléphone.
- on_topic = false si le message n'a AUCUN rapport avec la situation de l'utilisateur, son emploi,
  ses études, un projet, une formation, l'argent ou un financement (ex. recette, météo, blague, code).
  Une réponse courte à une question ("27", "Casablanca", "3000") est on_topic = true."""

ANSWER_SYSTEM = """Tu es CivicPilot, un guide d'inclusion financière. Tu donnes une ORIENTATION, jamais une décision officielle.
Tu reçois un profil et des programmes déjà vérifiés, avec une éligibilité calculée par des règles.
Réponds UNIQUEMENT en JSON valide, entièrement rédigé en : {lang_name}.

Schéma :
{{"summary": string,
  "recommendations": [{{"program_id": string, "match_label": string, "why": string,
                        "missing": [string], "risks": [string]}}],
  "action_plan": [{{"step": string, "program_id": string|null, "source_url": string|null}}],
  "assumptions": [string]}}

Règles strictes :
- Utilise UNIQUEMENT les données fournies : aucun programme, montant, délai ou lien inventé.
- Ordre : "likely_match" puis "partial". Pour "no_match", une phrase max pour expliquer pourquoi.
- Si constraints.cannot_take_debt = true : ne recommande aucun crédit, signale-le simplement.
- Formulations prudentes : "semble correspondre", "à confirmer auprès de l'organisme".
  Jamais "approuvé", "accepté", "garanti", "vous êtes éligible".
- Pour tout crédit, mentionne le risque de remboursement.
- Ne commente jamais les informations sensibles (handicap, réfugié, revenus) au-delà de leur effet sur un programme.
- Sépare les faits (issus des sources) des suppositions (liste "assumptions").
- summary : 2-3 phrases simples. action_plan : 3 à 6 étapes concrètes."""

# ------------------------------------------------------------------ #
# 4. Connexion au module de Person 3 (mock tant qu'il n'est pas prêt)
#    Person 3 lit le profil imbriqué : profile["personal"]["city"], etc.
# ------------------------------------------------------------------ #
try:
    from rag import find_programs  # fourni par Person 3
except ImportError:
    def find_programs(profile):
        """MOCK — même format que le vrai find_programs. Données fictives."""
        src = lambda n: [{"url": f"https://example.org/program-{n}", "verified_on": "2026-09-27",
                          "excerpt": "Extrait officiel (MOCK)"}]
        return {"programs": [
            {"id": "grant_a", "name": "Subvention jeunes porteurs de projet (MOCK)", "type": "grant",
             "provider": "Organisme A", "amount_range": "jusqu'à 5 000 MAD",
             "match_status": "likely_match",
             "matched_requirements": ["Sans emploi", "Projet de création d'activité"],
             "missing_requirements": ["Attestation de résidence"],
             "failed_requirements": [], "warnings": ["Places limitées"],
             "documents": ["CIN", "Attestation de résidence", "Description du projet"],
             "deadline": "À vérifier", "contact": "Guichet local (MOCK)", "sources": src("a")},
            {"id": "micro_b", "name": "Microcrédit création (MOCK)", "type": "microcredit",
             "provider": "Association B", "amount_range": "1 000 – 50 000 MAD",
             "match_status": "partial",
             "matched_requirements": ["Montant dans la fourchette"],
             "missing_requirements": ["Justificatif de revenus ou garant"],
             "failed_requirements": [], "warnings": ["Remboursement mensuel avec intérêts"],
             "documents": ["CIN", "Plan de financement simple"],
             "deadline": "Continu", "contact": "Agence B (MOCK)", "sources": src("b")},
            {"id": "train_c", "name": "Formation entrepreneuriat (MOCK)", "type": "training",
             "provider": "Centre C", "amount_range": "Gratuit",
             "match_status": "likely_match",
             "matched_requirements": ["Tout public"], "missing_requirements": [],
             "failed_requirements": [], "warnings": [],
             "documents": ["CIN"], "deadline": "Session mensuelle",
             "contact": "Centre C (MOCK)", "sources": src("c")},
        ]}

# ------------------------------------------------------------------ #
# 5. Outils
# ------------------------------------------------------------------ #
def is_quota_error(e):
    """429 / limite de débit / quota épuisé : inutile de réessayer le même modèle."""
    msg = str(e).lower()
    return getattr(e, "status_code", None) == 429 or "rate limit" in msg or "quota" in msg


def llm_json(system, user, temperature=0.1, retries=2, meta=None):
    """Appel LLM qui renvoie toujours un dict, ou lève une erreur après retries.
    En cas de 429 sur le modèle principal, bascule sur FALLBACK_MODEL.
    meta["model"] reçoit le modèle réellement utilisé (pour trace.model_used)."""
    last = None
    models = [MODEL] + ([FALLBACK_MODEL] if FALLBACK_MODEL and FALLBACK_MODEL != MODEL else [])
    for model in models:
        extra = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT and "gpt-oss" in model else {}
        for _ in range(retries + 1):
            try:
                r = client.chat.completions.create(
                    model=model, temperature=temperature, **extra,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}])
                txt = re.sub(r"```(json)?", "", r.choices[0].message.content).strip()
                out = json.loads(txt)
                if meta is not None:
                    meta["model"] = model
                return out
            except Exception as e:
                last = e
                if is_quota_error(e):
                    break  # modèle suivant
        if not is_quota_error(last):
            break  # erreur hors quota : le modèle de secours n'y changera rien
    raise RuntimeError(f"LLM JSON failure: {last}")


# Données personnelles interdites : jamais envoyées au LLM, jamais stockées dans le profil
PII_PATTERNS = [
    re.compile(r"(?<![\w+])(?:\+|00)?212[\s.-]?\(?0?\)?[5-7](?:[\s.-]?\d){8}\b"),  # téléphone +212 / 00212
    re.compile(r"(?<!\w)0[5-7](?:[\s.-]?\d){8}\b"),                                  # téléphone 06 12 34 56 78
    re.compile(r"\bMA\d{2}(?:\s?\w){20,26}\b", re.I),                                # IBAN marocain
    re.compile(r"(?<!\w)\d(?:[\s.-]?\d){8,}\b"),                                     # RIB / compte / long numéro
    re.compile(r"\b[A-Z]{1,2}\d{5,6}\b", re.I),                                      # CIN (ex. BK123456)
]
PII_MASK = "[masqué]"

def scrub_pii(text):
    """Remplace CIN, téléphone et numéros de compte par [masqué]."""
    if not isinstance(text, str):
        return text
    for pat in PII_PATTERNS:
        text = pat.sub(PII_MASK, text)
    return text


def normalize(raw):
    """Validation déterministe champ par champ : le LLM propose, le code dispose."""
    p = copy.deepcopy(EMPTY_PROFILE)
    for path in FIELD_PATHS:
        v = get(raw or {}, path)
        if path in LIST_PATHS:
            v = [scrub_pii(str(x).strip()) for x in v if str(x).strip()] if isinstance(v, list) else []
        elif path in BOOL_PATHS:
            v = v if isinstance(v, bool) else None
        elif path in INT_PATHS:
            try:
                v = int(v) if v is not None and not isinstance(v, bool) else None
            except (TypeError, ValueError):
                v = None
            if v is not None and not 15 <= v <= 99:
                v = None
        elif path in NUM_PATHS:
            try:
                v = float(v) if v is not None and not isinstance(v, bool) else None
            except (TypeError, ValueError):
                v = None
            if v is not None and v <= 0:
                v = None
        elif path in ENUMS:
            v = v if v in ENUMS[path] else None
        else:
            v = scrub_pii(v.strip()) if isinstance(v, str) and v.strip() else None
        put(p, path, v)
    return p


def merge(old, new):
    """Le nouveau message complète le profil sans effacer ce qui est déjà connu."""
    out = normalize(old)
    for path in FIELD_PATHS:
        v = get(new, path)
        if path in LIST_PATHS:
            put(out, path, list(dict.fromkeys(get(out, path) + v)))
        elif v is not None:
            put(out, path, v)
    for path, default in DEFAULTS.items():
        if get(out, path) is None:
            put(out, path, default)
    # Cohérence : un étudiant déclaré est aussi "student" côté éligibilité
    if get(out, "employment.status") == "student" and get(out, "eligibility.student") is None:
        put(out, "eligibility.student", True)
    out["missing_information"] = [f for f in required_fields(out) if get(out, f) is None]
    return out


_GARANTIR = {"garantir": "assurer", "garantit": "assure", "garantissent": "assurent", "garantissant": "assurant"}

# Ordre important : phrases complètes d'abord, puis mots isolés
SAFE_PATTERNS = [
    # Français
    (r"vous (êtes|serez|seriez) (approuvée?s?|acceptée?s?|éligibles?)", "votre profil semble correspondre"),
    (r"\b(une|la|les|des|de|sans|avec|votre|vos|aucune) (garanties?)\b",   # garantie = caution de crédit
     lambda m: f"{m.group(1)} caution{'s' if m.group(2).endswith('s') else ''}"),
    (r"\b(garantir|garantit|garantissent|garantissant)\b", lambda m: _GARANTIR[m.group(1).lower()]),
    (r"\b(pas|non) garantie?s?\b", r"\1 certain"),
    (r"\b(garantie?s?|approuvée?s?|acceptée?s?)\b", "à confirmer auprès de l'organisme"),
    # Anglais
    (r"you (are|will be|would be) (approved|accepted|eligible)", "your profile appears to match"),
    (r"\bnot guaranteed\b", "not certain"),
    (r"\b(guaranteed|approved|accepted)\b", "to be confirmed with the provider"),
    # Arabe / darija (مؤهلات = "qualifications" reste autorisé)
    (r"(أنت|انت|نتا|نتي) (مؤهل|مقبول)\w*", "ملفك يبدو مناسباً"),
    (r"غير مضمون\w*", "غير مؤكد"),
    (r"(مضمون|مقبول)\w*", "يحتاج إلى تأكيد"),
    (r"مؤهل(ة|ين)?\b", "يبدو مناسباً"),
]

def sanitize(obj):
    """Filet de sécurité : réécrit les formulations interdites partout dans la réponse."""
    if isinstance(obj, str):
        for pat, rep in SAFE_PATTERNS:
            obj = re.sub(pat, rep, obj, flags=re.IGNORECASE)
        return obj
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    return obj


def verify(answer, programs, profile=None, lang="fr"):
    """Anti-hallucination : on garde seulement les programmes et liens qui existent vraiment."""
    by_id = {p["id"]: p for p in programs}
    urls = {s["url"] for p in programs for s in p.get("sources", [])}
    # Contrat garanti même si le LLM oublie un champ ou se trompe de type
    lst = lambda v: v if isinstance(v, list) else []
    if not isinstance(answer, dict):
        answer = {}
    if not (isinstance(answer.get("summary"), str) and answer["summary"].strip()):
        answer["summary"] = FALLBACK_SUMMARY[lang]
    answer["action_plan"] = [s for s in lst(answer.get("action_plan"))
                             if isinstance(s, dict) and isinstance(s.get("step"), str)]
    answer["assumptions"] = [str(a) for a in lst(answer.get("assumptions"))]
    recs = [r for r in lst(answer.get("recommendations"))
            if isinstance(r, dict) and r.get("program_id") in by_id]
    for r in recs:
        p = by_id[r["program_id"]]
        r["match_label"] = r.get("match_label") if isinstance(r.get("match_label"), str) else p["match_status"]
        r["why"] = r.get("why") if isinstance(r.get("why"), str) else "; ".join(p["matched_requirements"])
        r["missing"] = r["missing"] if isinstance(r.get("missing"), list) else p["missing_requirements"]
        r["risks"] = lst(r.get("risks"))
    # Garde anti-dette dans le code (pas seulement dans le prompt) : recommandations ET plan d'action
    if get(profile or {}, "constraints.cannot_take_debt") is True:
        credit_ids = {p["id"] for p in programs if p.get("type") in CREDIT_TYPES}
        recs = [r for r in recs if r["program_id"] not in credit_ids]
        answer["action_plan"] = [s for s in answer["action_plan"] if s.get("program_id") not in credit_ids]
    # Nom, type et sources recopiés depuis find_programs, jamais depuis le LLM
    for r in recs:
        p = by_id[r["program_id"]]
        r["program_name"] = p.get("name")
        r["type"] = p.get("type")
        r["sources"] = p.get("sources", [])
        # Tout crédit affiche ses avertissements officiels + le risque de remboursement
        if p.get("type") in CREDIT_TYPES:
            r["risks"] += [w for w in p.get("warnings", []) + [REPAY_RISK[lang]] if w not in r["risks"]]
    answer["recommendations"] = recs
    for step in answer["action_plan"]:
        if step.get("program_id") not in by_id:
            step["program_id"] = None
        if step.get("source_url") not in urls:
            step["source_url"] = None
    return answer


PROGRAM_LISTS = ("matched_requirements", "missing_requirements", "failed_requirements", "warnings", "documents")

def validate_programs(result):
    """Contrôle la sortie de find_programs (Person 3). Un programme mal formé est écarté et signalé,
    au lieu de faire planter la démo. Renvoie (programmes_valides, [{id, reason}])."""
    if not isinstance(result, dict) or not isinstance(result.get("programs"), list):
        raise ValueError("find_programs doit renvoyer {'programs': [...]}")
    valid, invalid, seen = [], [], set()
    for i, p in enumerate(result["programs"]):
        pid = p.get("id") if isinstance(p, dict) else None
        if not isinstance(p, dict):
            reason = "programme non dict"
        elif not all(isinstance(p.get(k), str) and p[k].strip() for k in ("id", "name", "type")):
            reason = "id, name ou type manquant"
        elif p.get("match_status") not in ORDER:
            reason = f"match_status invalide : {p.get('match_status')!r}"
        elif not (isinstance(p.get("sources"), list) and p["sources"] and all(
                isinstance(s, dict) and str(s.get("url", "")).startswith("http") for s in p["sources"])):
            reason = "sources absentes ou sans url"
        elif pid in seen:
            reason = "id en double"
        else:
            reason = None
        if reason:
            invalid.append({"index": i, "id": pid, "reason": reason})
            continue
        seen.add(pid)
        p = dict(p)
        for k in PROGRAM_LISTS:  # listes optionnelles : [] par défaut pour ne pas planter plus loin
            p[k] = p[k] if isinstance(p.get(k), list) else []
        valid.append(p)
    return valid, invalid


def build_checklist(answer, programs):
    """Checklist déterministe : documents des programmes recommandés, sans doublons."""
    by_id = {p["id"]: p for p in programs}
    items, all_docs = [], []
    for r in answer.get("recommendations", []):
        p = by_id[r["program_id"]]
        docs = p.get("documents", [])
        items.append({"program_id": p["id"], "program_name": p.get("name"), "documents": docs,
                      "deadline": p.get("deadline"), "contact": p.get("contact"),
                      "source_url": p["sources"][0]["url"] if p.get("sources") else None})
        all_docs += [d for d in docs if d not in all_docs]
    return {"programs": items, "all_documents": all_docs}


NUM_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(k)?\s*(dhs?|mad|dirhams?|درهم|ans?|years?|سنة|عام)?\s*$", re.I)

def quick_number(message, profile, language):
    """Raccourci sans LLM : réponse purement numérique juste après une question sur l'âge ou le montant."""
    asked = (profile or {}).get("missing_information") or []
    if not asked or asked[0] not in ("personal.age", "financial_need.amount"):
        return None
    m = NUM_RE.match(re.sub(r"(?<=\d)[\s ](?=\d{3}\b)", "", message))  # "3 000" -> "3000"
    if not m:
        return None
    n = float(m.group(1).replace(",", ".")) * (1000 if m.group(2) else 1)
    extracted = {"language": language, "profile": {}}
    put(extracted["profile"], asked[0], n)
    return extracted


def fallback_answer(programs, lang, profile):
    """Réponse sans LLM si l'API tombe : la démo continue de marcher."""
    no_debt = get(profile, "constraints.cannot_take_debt") is True
    recs, plan = [], []
    for p in programs:
        if p["match_status"] == "no_match":
            continue
        if no_debt and p.get("type") in CREDIT_TYPES:
            continue
        recs.append({"program_id": p["id"], "match_label": p["match_status"],
                     "why": "; ".join(p["matched_requirements"]),
                     "missing": p["missing_requirements"], "risks": p["warnings"]})
        url = p["sources"][0]["url"] if p.get("sources") else None
        for doc in p.get("documents", []):
            plan.append({"step": doc, "program_id": p["id"], "source_url": url})
    return {"summary": FALLBACK_SUMMARY[lang], "recommendations": recs,
            "action_plan": plan, "assumptions": []}

# ------------------------------------------------------------------ #
# 6. Orchestration — LA fonction à donner à Person 4
# ------------------------------------------------------------------ #
ORDER = {"likely_match": 0, "partial": 1, "no_match": 2}

def analyze_case(message, profile=None, language=None):
    trace, t = {}, time.time()
    # Modèle réellement utilisé à chaque étape (None = aucun LLM : raccourci, garde ou secours sans IA)
    trace["model_used"] = {"extraction": None, "answer": None}

    # 6.0 Vie privée : CIN / téléphone / compte masqués AVANT tout appel au LLM
    clean = scrub_pii(message)
    trace["pii_redacted"] = clean != message
    message = clean

    def refocus(lang, reason):
        """Recentre poliment, sans find_programs, en gardant le profil déjà connu."""
        trace["guard"] = reason
        return {"status": "needs_info", "language": lang, "user_profile": merge(profile, normalize({})),
                "question": REFOCUS[lang], "trace": trace}

    # 6.0 bis Tentative d'injection : bloquée avant tout appel au LLM
    if INJECTION_RE.search(message):
        return refocus(guess_language(message, language), "injection")

    # 6.1 Langue + extraction (raccourci sans LLM pour une réponse purement numérique)
    extracted = quick_number(message, profile, language)
    trace["extract_shortcut"] = extracted is not None
    if extracted is None:
        meta = {}
        try:
            extracted = llm_json(EXTRACT_SYSTEM, message, meta=meta)
            trace["model_used"]["extraction"] = meta.get("model")
        except Exception as e:
            trace["error_stage"] = "extraction"
            return {"status": "error", "error": str(e), "language": language or "fr",
                    "user_profile": profile or copy.deepcopy(EMPTY_PROFILE), "trace": trace}
    lang = extracted.get("language") or language or "fr"
    # Stabilité : une réponse de moins de 3 mots garde la langue du tour précédent
    if language in LANGS and len(message.split()) < 3:
        lang = language
    lang = lang if lang in LANGS else "fr"
    trace["extract_ms"] = int((time.time() - t) * 1000)

    # 6.2 Validation + fusion (calcule aussi missing_information)
    new = normalize(extracted.get("profile", {}))

    # Hors-sujet : seulement si le LLM le dit ET qu'aucune info de profil n'a été extraite
    if extracted.get("on_topic") is False and not any(get(new, f) not in (None, []) for f in FIELD_PATHS):
        return refocus(lang, "off_topic")

    merged = merge(profile, new)

    # 6.3 Une seule question à la fois
    if merged["missing_information"]:
        return {"status": "needs_info", "language": lang, "user_profile": merged,
                "question": QUESTIONS[lang][merged["missing_information"][0]],
                "trace": trace}

    # 6.4 Recherche + éligibilité (Person 3)
    # Si le module de Person 3 plante, on renvoie une erreur propre au lieu de faire tomber l'API
    t = time.time()
    try:
        programs, invalid = validate_programs(find_programs(merged))
        programs.sort(key=lambda p: ORDER[p["match_status"]])
        if invalid:
            trace["invalid_programs"] = invalid
    except Exception as e:
        trace["error_stage"] = "retrieval"
        trace["retrieval_ms"] = int((time.time() - t) * 1000)
        return {"status": "error", "error": f"find_programs failure: {e}", "language": lang,
                "user_profile": merged, "trace": trace}
    trace["retrieval_ms"] = int((time.time() - t) * 1000)

    # 6.5 Réponse finale + vérification
    t = time.time()
    trace["llm_fallback_used"] = False
    meta = {}
    try:
        answer = llm_json(ANSWER_SYSTEM.format(lang_name=LANG_NAMES[lang]),
                          # JSON compact : moins de tokens -> moins de limitations de débit (429)
                          json.dumps({"profile": merged, "programs": programs}, ensure_ascii=False,
                                     separators=(",", ":")),
                          temperature=0.3, meta=meta)
        trace["model_used"]["answer"] = meta.get("model")
    except Exception:
        answer = fallback_answer(programs, lang, merged)
        trace["llm_fallback_used"] = True
    answer = verify(sanitize(answer), programs, merged, lang)
    answer["checklist"] = build_checklist(answer, programs)
    answer["disclaimer"] = DISCLAIMERS[lang]
    trace["answer_ms"] = int((time.time() - t) * 1000)

    return {"status": "complete", "language": lang, "user_profile": merged,
            "programs": programs, "final_response": answer, "trace": trace}

# ------------------------------------------------------------------ #
# 7. Test rapide du scénario de démo (2 tours)
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    r1 = analyze_case("Je suis au chômage et je veux ouvrir une petite boulangerie. "
                      "J'ai besoin d'environ 3000 MAD.")
    print(json.dumps(r1, ensure_ascii=False, indent=2))
    r2 = analyze_case("J'habite à Casablanca et j'ai 27 ans.",
                      profile=r1["user_profile"], language=r1["language"])
    print(json.dumps(r2, ensure_ascii=False, indent=2))
