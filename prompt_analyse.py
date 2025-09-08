#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_analyse.py — Générateur de prompt Lyra GPI v5.1

But : produire une consigne complète et structurée pour l’analyse automatique
des courses hippiques selon la stratégie GPI v5.1 (budget cap 5 €, EV ≥ +40 %,
ROI ≥ +20 %, maximum 2 tickets par course).
"""

import datetime

def build_prompt(reunion: str, course: str, hippodrome: str,
                 discipline: str, distance: str, partants: int,
                 conditions: str, liens: dict) -> str:
    """
    Construit un prompt optimisé pour l’analyse GPI v5.1.

    Args:
        reunion (str): Réunion ex: "R1"
        course (str): Course ex: "C3"
        hippodrome (str): Hippodrome ex: "Vincennes"
        discipline (str): Plat / Attelé / Monté
        distance (str): Distance de la course
        partants (int): Nombre de chevaux
        conditions (str): Ex: "Bon terrain, corde à gauche"
        liens (dict): Liens utiles (partants, cotes H-30, cotes H-5, stats J/E, chronos)

    Returns:
        str: prompt complet prêt à être passé à l’analyse
    """
    date_str = datetime.date.today().strftime("%d/%m/%Y")

    header = f"""### Analyse Hippique — {reunion}{course} ({hippodrome})
Date : {date_str}
Discipline : {discipline} — Distance : {distance} — Partants : {partants}
Conditions : {conditions}

#### Liens de référence :
- Partants : {liens.get('partants')}
- Cotes H-30 : {liens.get('cotes_h30')}
- Cotes H-5 : {liens.get('cotes_h5')}
- Stats J/E : {liens.get('stats')}
- Chronos : {liens.get('chronos')}
"""

    checklist = """#### ✅ Checklist GPI v5.1
- [ ] Cotes H-30 et H-5 récupérées
- [ ] Drifts iden
