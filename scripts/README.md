# Guide d'Utilisation des Scripts

Ce document a pour but de clarifier le niveau de fiabilité et l'usage de chaque script présent dans ce répertoire.

## Statut des Scripts

Chaque script est classé selon l'un des trois niveaux de confiance suivants :

-   ✅ **Prêt pour la Production :** Le script est couvert par des tests unitaires et d'intégration (>70%), son comportement est prévisible.
-   ⚠️ **À Risque / Non Testé :** Le script n'a pas ou peu de tests. Son utilisation en production doit être faite avec une extrême prudence et sous surveillance.
-   ❌ **Obsolète / Ne Pas Utiliser :** Le script est considéré comme dépassé ou dangereux. Ne pas utiliser.

---

## Inventaire des Scripts

| Script | Statut | Couverture | Description |
| :--- | :---: | :---: | :--- |
| `monitor_roi.py` | ✅ | **88%** | Calcule et affiche des statistiques de performance (ROI, P&L, etc.) à partir des fichiers d'analyse. |
| `smoke_prod.sh` | ✅ | N/A | Script de validation post-déploiement pour vérifier la santé des endpoints critiques. |
| | | | |
| `concat_je_month.py` | ⚠️ | 0% | Concatène et résume les statistiques mensuelles du "Journal de l'Écurie". |
| `cron_decider.py` | ⚠️ | 0% | Logique (legacy?) pour décider de déclencher un cron. |
| `fetch_je_chrono.py` | ⚠️ | 0% | Script pour récupérer les statistiques de chrono depuis "Journal de l'Écurie". |
| `fetch_je_stats.py` | ⚠️ | 0% | Script générique pour récupérer les statistiques depuis "Journal de l'Écurie". |
| `online_fetch_zeturf.py` | ⚠️ | 60% | Script principal (legacy?) de scraping pour Zeturf. Contient une logique complexe. |
| `p_finale_export.py` | ⚠️ | 56% | Exporte les probabilités finales. |
| `resolve_course_id.py` | ⚠️ | 59% | Logique pour résoudre les identifiants de course. |
| `update_excel_planning.py`| ⚠️ | 86% | Met à jour un planning Excel avec les données des courses. **Risque élevé de corruption de fichier si des erreurs surviennent.** |
| `update_excel_with_results.py` | ⚠️ | 37% | Met à jour un fichier Excel avec les résultats finaux. **Risque élevé de corruption de fichier.** |
| | | | |
| `drive_sync.py` | ❌ | 0% | Semble synchroniser des fichiers avec Google Drive, probablement obsolète. |
| `restore_from_drive.py`| ❌ | 0% | Semble restaurer une sauvegarde depuis Google Drive, probablement obsolète. |

---
*Il est **fortement recommandé** d'ajouter des tests pour les scripts marqués `⚠️` avant toute utilisation régulière en production.*
