# IA responsable — garde-fous, code et preuves

Principe : quand une règle compte, elle est **appliquée par le code**, pas seulement demandée au LLM dans le prompt. Chaque ligne indique où se trouve la règle dans `civicpilot_orchestrator.py` et quel test de `test_person2.py` la vérifie.

| Garde-fou | Où dans le code | Prouvé par |
|---|---|---|
| **Orientation, pas décision** : jamais « approuvé », « accepté », « garanti », « vous êtes éligible » (fr, en, ar, darija) | `sanitize` + `SAFE_PATTERNS` (réécriture), `ANSWER_SYSTEM` (consigne) | tests 8 et 14 |
| **Avertissement systématique** « à confirmer auprès de l'organisme » | `DISCLAIMERS`, ajouté dans `analyze_case` | test 18 |
| **Éligibilité calculée par des règles**, pas par le LLM | `find_programs` (Person 3) fournit `programs[].match_status` ; le tri et la checklist en dépendent | par construction (voir les limites) |
| **Aucun programme, lien ou nom inventé** | `verify` (ids et URLs réels uniquement ; `program_name`, `type`, `sources` recopiés depuis `find_programs`) | tests 12 et 18 |
| **Sortie de `rag.py` contrôlée** | `validate_programs` | test 12 |
| **Pas de crédit si l'utilisateur refuse la dette** (recommandations et plan d'action) | `verify`, `fallback_answer`, `CREDIT_TYPES` | tests 7 et 13 |
| **Risque de remboursement** toujours affiché pour un crédit | `verify` + `REPAY_RISK` | tests 13 et 18 |
| **CIN, téléphone, compte jamais envoyés au LLM ni stockés** | `scrub_pii` + `PII_PATTERNS`, appelé au début de `analyze_case` et dans `normalize` | test 15 |
| **Critères sensibles jamais demandés** (handicap, statut de réfugié, revenus) | `QUESTIONS` et `required_fields` ne les contiennent pas | test 20 |
| **Aucune supposition de genre** dans les questions (ar, darija, fr) | `QUESTIONS` (noms plutôt que verbes ou adjectifs accordés au masculin) | test 20 |
| **Résistance aux injections** (« ignore tes instructions… »), sans appel au LLM | `INJECTION_RE`, `guess_language`, `refocus` dans `analyze_case` | test 16 |
| **Recentrage poli hors-sujet**, sans recherche de programmes | champ `on_topic` + condition « aucun champ extrait » dans `analyze_case`, `REFOCUS` | test 17 |
| **Profil validé** (âge impossible refusé, valeurs hors liste rejetées) | `normalize` (`ENUMS`, bornes 15–99, montant > 0) | tests 5 et 19 |
| **Continuité de service** si le LLM ou `rag.py` tombe | `fallback_answer`, `try/except` autour de `find_programs`, bascule `FALLBACK_MODEL` | tests 9, 11 et 21 |
| **Transparence sur le modèle utilisé** | `trace.model_used`, rempli par `llm_json(meta=…)` | test 21 |

## Limites honnêtes

- **Les regex ne sont pas exhaustives.**
  - `PII_PATTERNS` couvre les formats marocains courants (06/07/05, +212, CIN du type `BK123456`, RIB de 24 chiffres), pas tous les formats.
  - `INJECTION_RE` ne reconnaît que des tournures connues : une injection reformulée peut passer.
  - `SAFE_PATTERNS` réécrit des mots et peut produire une phrase maladroite (« votre dossier sera à confirmer auprès de l'organisme »).
- **La non-déduction des critères sensibles repose sur le prompt.** Le code ne demande jamais le handicap, le statut de réfugié ou les revenus. En revanche, qu'ils ne soient pas *déduits* d'un message (par exemple un faible revenu déduit du chômage) est seulement une consigne de `EXTRACT_SYSTEM`, sans vérification dans le code.
- **`recommendations[].match_label` est rédigé par le LLM.** Il n'est remplacé par `match_status` que s'il est absent. La valeur qui fait foi est `programs[].match_status`, calculée par les règles. Amélioration possible : forcer `match_label = match_status` dans `verify`.
- **La neutralité de genre n'est garantie que pour les questions fixes.** Le texte rédigé par le LLM (étape 2) peut encore accorder au masculin en arabe ou en darija.
- **Le hors-sujet dépend du LLM** (`on_topic`). Le code limite le risque : on ne recentre que si le LLM dit « hors-sujet » **et** qu'aucune information de profil n'a été extraite.
- **Programmes fictifs** : tant que `rag.py` (Person 3) est absent, `find_programs` est un mock dont les programmes et liens sont marqués `(MOCK)` et `example.org`. Ils ne doivent pas être présentés comme réels.
- **Données envoyées à un tiers** : le message, après masquage, est traité par l'API Groq.
- **Validation partielle sur le modèle de démo** : 11 tests LLM ont été validés sur `gpt-oss-20b` après l'épuisement du quota de `gpt-oss-120b` (voir [TESTING.md](TESTING.md)).
- **Non-déterminisme** : le test 8 a échoué une fois sur le 120b. Le correctif est dans le code (`sanitize`), vérifié par le test 14 sans LLM, mais le texte d'un LLM reste imprévisible.
