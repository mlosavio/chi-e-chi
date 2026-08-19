"""Chi è chi — leggere un contratto senza mandarlo fuori.

Un anonimizzatore locale maschera ogni dato personale; un modello linguistico, leggendo il
testo **mascherato**, dice che cosa c'è nel documento — entità, ruoli, attributi, relazioni.
I valori tornano al loro posto qui, in locale, e il dominio decide quali sono validi.

    documento  →  pii.analizza          anonimizza, e tiene la mappa
               →  lettura.ISTRUZIONE    che cosa si chiede al modello
               →  scheda.TABELLE        dalla lettura ai campi
"""

from .estrattore import estrai
from .scheda import Esito

__all__ = ["Esito", "estrai"]
