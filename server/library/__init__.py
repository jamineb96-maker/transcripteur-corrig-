"""Module d'initialisation pour la librairie.

Ce package expose un blueprint Flask fournissant des endpoints
de consultation et de recherche de documents contenus dans le dossier
`server/library/store`.  Lorsqu'il est importé, l'index est construit
en mémoire grâce au module `indexer`.  Les routes sont définies dans
`routes.py` et exposées sous le préfixe `/api/library`.
"""

from .routes import bp

__all__ = ["bp"]