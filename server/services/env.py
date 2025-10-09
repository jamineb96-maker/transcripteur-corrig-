"""Utilitaires d'accès aux variables d'environnement.

Ce module simplifie la récupération des variables avec des valeurs par défaut
et propose un helper pour interpréter les booléens.
"""

import os


def env(name: str, default=None):
    """Retourne la valeur d'une variable d'environnement ou une valeur par défaut.

    :param name: nom de la variable d'environnement
    :param default: valeur à retourner si la variable n'est pas définie
    :return: la chaîne lue dans l'environnement ou `default`
    """
    return os.getenv(name, default)


def is_true(name: str) -> bool:
    """Interprète une variable d'environnement comme un booléen.

    Les valeurs reconnues comme vraies sont '1', 'true', 'yes' (insensible à la casse).

    :param name: nom de la variable d'environnement
    :return: True si la variable est évaluée comme vraie, False sinon
    """
    value = os.getenv(name, '')
    return value.lower() in ('1', 'true', 'yes')