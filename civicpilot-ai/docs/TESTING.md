# Tests et fiabilité

`test_person2.py` contient **21 tests** : 13 appellent le LLM, 8 non (LLM simulé, aucun appel réseau).

## Lancer

```powershell
venv\Scripts\activate
python test_person2.py --fast          # 8 tests sans LLM : instantané, aucun quota consommé
python test_person2.py --only 3,7,17   # seulement ces numéros
python test_person2.py                 # les 21 : consomme du quota Groq (voir l'incident ci-dessous)
```

Pour tester sur un autre modèle sans toucher à `.env` (la variable d'environnement est prioritaire) :

```powershell
$env:LLM_MODEL='openai/gpt-oss-20b'; $env:LLM_FALLBACK_MODEL='openai/gpt-oss-20b'; python test_person2.py --only 3,4; Remove-Item Env:LLM_MODEL, Env:LLM_FALLBACK_MODEL
```

## Résultats finaux : 21/21 ✅ (27 septembre 2026)

| # | Test | Résultat | Temps | Modèle |
|---|---|---|---|---|
| 1 | Français, infos manquantes | ✅ | 1 090 ms | gpt-oss-120b |
| 2 | Darija complet | ✅ | 1 087 ms | gpt-oss-120b |
| 3 | Arabe complet | ✅ | 1 881 ms | gpt-oss-20b |
| 4 | Anglais complet | ✅ | 2 350 ms | gpt-oss-20b |
| 5 | Âge impossible (150 ans) | ✅ | 1 242 ms | gpt-oss-20b |
| 6 | Montant manquant | ✅ | 565 ms | gpt-oss-20b |
| 7 | Refus de dette | ✅ | 6 981 ms | gpt-oss-20b |
| 8 | Formulation prudente | ✅ | 18 499 ms | gpt-oss-20b |
| 9 | Panne LLM → réponse de secours | ✅ | 7 535 ms | gpt-oss-20b |
| 10 | Réponse courte « 27 » au 2e tour | ✅ | 16 527 ms | gpt-oss-20b |
| 11 | Panne `rag.py` → erreur propre | ✅ | 8 702 ms | gpt-oss-20b |
| 12 | Programme mal formé ignoré | ✅ | 13 558 ms | gpt-oss-20b |
| 13 | Garde crédit (anti-dette + risque) | ✅ | 0 ms | sans LLM |
| 14 | Formulations interdites, 4 langues | ✅ | 15 ms | sans LLM |
| 15 | CIN / téléphone / RIB masqués | ✅ | 0 ms | sans LLM |
| 16 | Injection bloquée, 4 langues | ✅ | 1 ms | sans LLM |
| 17 | Hors-sujet recentré | ✅ | 7 473 ms | gpt-oss-20b |
| 18 | Contrat « complete » + chemin de secours | ✅ | 0 ms | sans LLM |
| 19 | Contrat « needs_info » / « error » | ✅ | 0 ms | sans LLM |
| 20 | Questions neutres et non sensibles | ✅ | 3 ms | sans LLM |
| 21 | Bascule vers le modèle de secours sur 429 | ✅ | 68 ms | sans LLM |

Temps moyen : **7,1 s** pour les tests avec LLM, **11 ms** pour les tests sans LLM.

**Transparence :**
- Les tests 3 à 12 et 17 ont été validés sur `gpt-oss-20b`, à cause de l'incident de quota ci-dessous. Les tests 3 à 12 étaient déjà passés sur `gpt-oss-120b` avant les derniers garde-fous (PII, injection, contrat).
- Le test 8 a échoué une fois sur le 120b, selon le texte généré par le LLM. Il est maintenant couvert aussi par le test 14, qui ne dépend pas du LLM.

## Latence : effort de raisonnement par défaut vs `low` (gpt-oss-120b)

Mesures sur le même prompt. Le temps de calcul vient du champ `usage.total_time` renvoyé par Groq.

| Étape | Calcul Groq (défaut) | Calcul Groq (`low`) | Tokens générés (défaut) | Tokens générés (`low`) |
|---|---|---|---|---|
| Extraction | 1,23 s / 1,35 s | **0,55 s / 0,57 s** | 551 / 555 | **248 / 258** |
| Rédaction | 2,18 s / 2,81 s | **1,21 s / 1,38 s** | 1 023 / 1 305 | **552 / 637** |

`low` divise par ~2 le temps de calcul et les tokens consommés. Le raccourci numérique supprime aussi un appel LLM sur les réponses du type « 27 ».

Moyenne de la suite de tests au fil des étapes :

| Moment | Tests | Temps moyen |
|---|---|---|
| Version initiale | 10 | 12 194 ms |
| + `build_checklist`, garde anti-dette, stabilité de langue | 10 | 12 770 ms |
| + erreur propre si `rag.py` plante | 11 | 14 041 ms |
| + `reasoning_effort=low`, JSON compact | 11 | 10 995 ms |
| + `validate_programs` | 12 | 9 247 ms |

## Incident : quota Groq épuisé

**Ce qui s'est passé.** Pendant la première exécution complète des 20 tests, 11 tests ont échoué en ~300 ms. L'erreur :

> `Rate limit reached for model openai/gpt-oss-120b … tokens per day (TPD): Limit 200000, Used 199756`

Le quota journalier du modèle de démo était atteint, après 7 exécutions complètes de la suite et 2 séries de mesures de latence dans la journée.

**Ce qu'on a appris.**
1. **La latence venait surtout de la limitation de débit, pas du modèle.** Les logs du SDK montraient `Retrying request in 6–10 seconds` : des 429 réessayés en silence. Le calcul réel est de 0,5 à 1,4 s par appel.
2. **Chaque test coûte du quota** : 7 suites complètes ont suffi à épuiser 200 000 tokens. D'où `--fast` (8 tests sans LLM) pendant le développement, et `--only` pour relancer uniquement ce qui manque.
3. **Une panne de quota en démo live doit être prévue** : ajout de la bascule automatique vers `LLM_FALLBACK_MODEL` (test 21), avec le modèle réellement utilisé affiché dans `trace.model_used`.
4. **Le modèle de démo est protégé** : les tests restants ont tourné sur `gpt-oss-20b`, qui a son propre quota.
