#!/bin/bash
# Continuer la session de débogage.
# Étape actuelle : Valider que les tests passent après les corrections.

# Nettoyer le cache de pytest pour éviter les erreurs d'importation périmées
pytest --cache-clear

# Lancer les tests
pytest
