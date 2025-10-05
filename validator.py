#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data validation utilities for the GPI v5.1 pipeline."""

from typing import Any, Dict


def validate_snapshot_data(data: Dict[str, Any], filename: str) -> None:
    """Validate the structure and content of a snapshot data file."""
    if not isinstance(data, dict):
        raise ValueError(f"Le fichier de snapshot {filename} n'est pas un dictionnaire JSON valide.")

    runners = data.get("runners")
    if not isinstance(runners, list) or not runners:
        raise ValueError(f"La clé 'runners' est manquante ou vide dans {filename}.")

    for i, runner in enumerate(runners):
        if not isinstance(runner, dict):
            raise ValueError(f"L'élément #{i} dans 'runners' de {filename} n'est pas un dictionnaire.")

        if "id" not in runner or "odds" not in runner:
            raise ValueError(f"L'élément #{i} dans 'runners' de {filename} n'a pas les clés 'id' et 'odds'.")

        odds = runner["odds"]
        if not isinstance(odds, (int, float)) or odds <= 0:
            raise ValueError(
                f"Les cotes pour le cheval #{runner.get('id', 'inconnu')} dans {filename} sont invalides: {odds}. "
                f"Elles doivent être un nombre supérieur à zéro."
            )

def validate_partants_data(data: Dict[str, Any], filename: str) -> None:
    """Validate the structure and content of a partants data file."""
    if not isinstance(data, dict):
        raise ValueError(f"Le fichier de partants {filename} n'est pas un dictionnaire JSON valide.")

    partants = data.get("runners") or data.get("participants")
    if not isinstance(partants, list) or not partants:
        raise ValueError(f"La clé 'runners' ou 'participants' est manquante ou vide dans {filename}.")

    for i, partant in enumerate(partants):
        if not isinstance(partant, dict):
            raise ValueError(f"L'élément #{i} dans 'partants' de {filename} n'est pas un dictionnaire.")

        if "id" not in partant and "numPmu" not in partant:
            raise ValueError(f"L'élément #{i} dans 'partants' de {filename} n'a pas les clés 'id' ou 'numPmu'.")

def validate_stats_je_data(data: Dict[str, Any], filename: str) -> None:
    """Validate the structure and content of a jockey/trainer stats file."""
    if not isinstance(data, dict):
        raise ValueError(f"Le fichier de statistiques J/E {filename} n'est pas un dictionnaire JSON valide.")