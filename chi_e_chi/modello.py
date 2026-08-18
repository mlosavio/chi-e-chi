"""Il modello linguistico: un punto solo, e si può spegnere.

Tre proprietà, e sono di progetto:

1. **Un solo punto di accesso.** Nessun'altra parte del programma importa il fornitore. Si
   può sostituire, spegnere o simulare cambiando una riga.
2. **Si spegne.** Senza chiave il cliente è `Spento` e solleva `ModelloNonDisponibile`. Chi
   chiama degrada — tiene quello che il rilevatore ha già trovato — e lo dichiara.
3. **Riceve testo, non un database.** Il modello non ha accesso a niente: gli si passa una
   stringa e si legge una stringa. Qui quella stringa è **mascherata**.

Il costo si annota per chiamata, perché un componente che spende va misurato.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("chi-e-chi")


class ModelloNonDisponibile(Exception):
    """Nessuna chiave, nessuna libreria, o la chiamata è fallita. **Non è un errore fatale**:
    è la condizione normale di un'installazione senza AI, e il programma deve funzionare."""


@dataclass(frozen=True)
class Domanda:
    istruzione: str
    """Il sistema: chi è il modello e con quali regole risponde."""
    fatti: str
    """L'unica fonte che ha. Qui dentro c'è il testo **mascherato**."""
    parole_massime: int = 900


@dataclass
class Uso:
    modello: str = ""
    token_ingresso: int = 0
    token_uscita: int = 0
    latenza_ms: int = 0


class Cliente(Protocol):
    def genera(self, domanda: Domanda) -> str: ...


class Spento:
    """Il cliente predefinito, ed è una scelta: senza chiave non si chiama nessuno."""

    ultimo_uso = Uso()

    def genera(self, domanda: Domanda) -> str:
        raise ModelloNonDisponibile("chiave assente")


@dataclass
class Finto:
    """Il cliente dei test: risposta decisa dal test, nessuna rete.

    Registra le domande, perché **metà di quello che c'è da provare** è che al modello sia
    arrivato il testo mascherato e non quello vero.
    """

    risposta: str = "{}"
    domande: list[Domanda] = field(default_factory=list)
    ultimo_uso: Uso = field(default_factory=Uso)

    def genera(self, domanda: Domanda) -> str:
        self.domande.append(domanda)
        return self.risposta


@dataclass
class ViaAnthropic:
    """Il cliente vero. La libreria si importa **quando serve**: se non è installata, il
    programma parte lo stesso e degrada, esattamente come farebbe senza chiave."""

    chiave: str
    modello: str = "claude-sonnet-5"
    ultimo_uso: Uso = field(default_factory=Uso)
    _sdk: object | None = None

    def genera(self, domanda: Domanda) -> str:
        client = self._client()
        avvio = time.monotonic()
        try:
            risposta = client.messages.create(
                model=self.modello,
                max_tokens=max(256, domanda.parole_massime * 3),
                system=domanda.istruzione,
                messages=[{"role": "user", "content": domanda.fatti}],
            )
        except Exception as errore:  # noqa: BLE001 — qualunque guasto degrada, non rompe
            log.warning("chiamata al modello fallita: %s", errore)
            raise ModelloNonDisponibile(
                f"chiamata fallita: {type(errore).__name__}"
            ) from errore

        self.ultimo_uso = Uso(
            modello=self.modello,
            token_ingresso=getattr(risposta.usage, "input_tokens", 0),
            token_uscita=getattr(risposta.usage, "output_tokens", 0),
            latenza_ms=int((time.monotonic() - avvio) * 1000),
        )
        return "".join(b.text for b in risposta.content if getattr(b, "type", "") == "text")

    def _client(self):
        if self._sdk is None:
            try:
                import anthropic
            except ImportError as errore:
                raise ModelloNonDisponibile("libreria anthropic non installata") from errore
            self._sdk = anthropic.Anthropic(api_key=self.chiave)
        return self._sdk


def cliente() -> Cliente:
    """Il cliente configurato. Senza chiave è `Spento`, e va benissimo."""
    chiave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chiave:
        return Spento()
    return ViaAnthropic(chiave=chiave, modello=os.environ.get("LLM_MODEL", "claude-sonnet-5"))
