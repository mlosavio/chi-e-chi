"""Chi è chi — estrarre dati da un contratto senza mandarlo fuori.

Un rilevatore di dati personali locale trova le entità; un modello linguistico, leggendo il
testo **mascherato**, decide quale entità ha quale ruolo. I valori tornano al loro posto qui,
in locale.
"""

from .estrattore import Esito, estrai

__all__ = ["Esito", "estrai"]
