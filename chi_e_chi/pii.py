"""Passaggio 1 · l'anonimizzatore: rizzo-pii, in locale.

Un servizio che gira **sulla propria macchina** — CPU, in un container — e che su un testo
italiano riconosce ventitré categorie di dati personali: nomi, codici fiscali, indirizzi,
IBAN, date, partite IVA. Restituisce:

* il **testo anonimizzato**, dove ogni valore è sostituito da un segnaposto `[TIPO_n]`;
* la **mappa** segnaposto → valore originale, che **non esce mai da questo processo**;
* le **entità**, con il tipo e la validazione dei codici strutturati.

## Che cosa fa, e che cosa non fa

**Fa una cosa sola: rende un documento spedibile.** È tutto il suo valore, ed è enorme: da
qui esce un testo che si può mandare a un modello remoto senza che ne esca un solo nome.

**Non estrae dati.** Dà **tipi, non ruoli**: su una lettera di assunzione trova due
`FULLNAME`, tre `STREET`, cinque `DATE`, e ha ragione su tutti. Ma «qui ci sono due persone»
non è «questa è quella che stai assumendo», e nessuna quantità di riconoscimento di entità
colma quella distanza.

Per un po' questo esempio ha provato a colmarla — attribuiva i campi che sapeva attribuire
da solo, «di email ce n'è una, sarà la sua» — e ogni volta bisognava aggiungere un pezzo per
correggere il risultato. Erano tutti lo stesso difetto, ed era architetturale.

## Il limite da conoscere

Legge **testo**: un PDF con il livello di testo va benissimo, la fotografia di una pagina
no — non fa OCR. Su quelle non c'è niente da mascherare, e mandarle fuori è una decisione
che va dichiarata a chi la subisce, non scoperta dopo.

Progetto: https://github.com/Rizzo-AI-Academy/rizzo-pii
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ATTESA_MASSIMA = 120
"""Un documento lungo su CPU non è istantaneo: il costo misurato è di circa 1,5 ms per
carattere, e un contratto di sei pagine sono venticinque secondi. Meglio aspettare che
dichiarare «non disponibile» un servizio che sta lavorando."""


def indirizzo() -> str:
    return os.environ.get("PII_URL", "http://127.0.0.1:5005").rstrip("/")


class PiiNonDisponibile(Exception):
    """Il servizio non risponde. Chi chiama **degrada**, non si rompe."""


@dataclass
class Entita:
    etichetta: str
    valore: str
    validato: bool = False
    """Per i codici strutturati: il checksum torna. Non è un'opinione, è aritmetica."""
    fonte: str = ""
    """`modello` o `regex`."""


@dataclass
class Analisi:
    entita: list[Entita] = field(default_factory=list)
    anonimizzato: str = ""
    mappa: dict[str, str] = field(default_factory=dict)
    """Da segnaposto a valore vero. **Resta qui.** È la metà del meccanismo che permette di
    usare un modello remoto senza mandargli un solo dato personale."""

    def per_etichetta(self, etichetta: str) -> list[str]:
        """I valori di un tipo, in ordine di apparizione e senza ripetizioni.

        Resta perché serve a **guardare** cosa ha trovato l'anonimizzatore — nella traccia
        dell'esempio e quando una lettura non torna. Non serve ad attribuire: quello lo fa
        il modello, che è l'unico che vede i ruoli.
        """
        visti: list[str] = []
        for e in self.entita:
            if e.etichetta == etichetta and e.valore not in visti:
                visti.append(e.valore)
        return visti


def analizza(testo: str, *, chiedi=None) -> Analisi:
    """Manda il testo al rilevatore e ne raccoglie entità, maschera e mappa.

    `chiedi` è iniettabile: un test non deve dipendere da un container acceso, o è un test
    che diventa rosso quando qualcuno spegne una macchina — e che nessuno prende più sul
    serio.
    """
    return _leggi((chiedi or _chiedi)("/analyze", {"text": testo, "include_mapping": True}))


def disponibile(*, chiedi=None) -> bool:
    """`/health` risponde 503 finché il modello non è in memoria: all'avvio ci mette qualche
    secondo, e chiederglielo prima darebbe «non disponibile» a un servizio che sta partendo."""
    try:
        return bool((chiedi or _chiedi)("/health").get("model_loaded"))
    except PiiNonDisponibile:
        return False


def ricomponi(testo: str, mappa: dict[str, str]) -> str:
    """Rimette i valori veri al posto dei segnaposto.

    È la seconda metà della strada: il modello vede `[FULLNAME_1]` e risponde `[FULLNAME_1]`,
    e il nome torna **qui**. Senza questa funzione l'anonimizzazione sarebbe solo una
    perdita di dati.
    """
    ricomposto = normalizza(testo, mappa)
    # Dal segnaposto più lungo al più corto: `[FULLNAME_10]` contiene `[FULLNAME_1]`, e
    # sostituendo prima il corto si rovinerebbe il lungo.
    for segnaposto in sorted(mappa, key=len, reverse=True):
        ricomposto = ricomposto.replace(segnaposto, mappa[segnaposto])
    return ricomposto


def normalizza(testo: str, mappa: dict[str, str]) -> str:
    """Rimette le parentesi quadre ai segnaposto che le hanno perse.

    **Il modello a volte risponde `FULLNAME_2` invece di `[FULLNAME_2]`**, e su una risposta
    composta — «via e numero civico» — le perde tutte e due: `STREET_2 BUILDINGNUM_2`. Senza
    parentesi la sostituzione non scatta e resta a video il nome del segnaposto, che è il
    modo più stupido di perdere una risposta giusta. E anche il controllo dei tipi smette di
    funzionare, perché cerca le parentesi.

    Si normalizza **una volta sola**, prima di tutto il resto: qui, e non in tre posti che
    poi divergono. Si rimettono solo ai nomi che esistono davvero nella mappa — non a una
    parola maiuscola qualsiasi.
    """
    pulito = (testo or "").strip()
    if not mappa:
        return pulito
    nudi = sorted((s[1:-1] for s in mappa if s.startswith("[")), key=len, reverse=True)
    for nome in nudi:
        pulito = re.sub(rf"(?<!\[){re.escape(nome)}(?!\])", f"[{nome}]", pulito)
    return pulito


# --------------------------------------------------------------------------


def _chiedi(percorso: str, corpo: dict | None = None) -> dict:
    if not indirizzo():
        raise PiiNonDisponibile("PII_URL non configurato")
    base = indirizzo()
    # L'indirizzo viene da una variabile d'ambiente: si pretende che sia HTTP e non, per
    # dire, `file:`. È una riga che qui non serve a niente e in un programma vero sì.
    if not base.startswith(("http://", "https://")):
        raise PiiNonDisponibile("PII_URL deve essere un indirizzo http(s)")
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta = urllib.request.Request(  # noqa: S310 — lo schema è appena stato verificato
        f"{base}{percorso}",
        data=dati,
        headers={"Content-Type": "application/json"} if dati else {},
        method="POST" if dati else "GET",
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=ATTESA_MASSIMA) as risposta:  # noqa: S310
            return json.loads(risposta.read().decode("utf-8"))
    except urllib.error.HTTPError as errore:
        raise PiiNonDisponibile(f"il servizio ha risposto {errore.code}") from errore
    except Exception as errore:  # noqa: BLE001 — rete: si degrada, non si rompe
        raise PiiNonDisponibile(f"{type(errore).__name__}") from errore


def _leggi(risposta: dict) -> Analisi:
    analisi = Analisi(
        anonimizzato=risposta.get("anonymized_text", ""),
        mappa=dict(risposta.get("mapping") or {}),
    )
    for segmento in risposta.get("segments") or []:
        etichetta = segmento.get("label")
        if not etichetta:
            continue          # è testo normale fra un'entità e l'altra
        valore = (segmento.get("t") or "").strip()
        if not valore:
            # Senza `include_mapping` torna il segnaposto e non il valore: a noi serve il
            # valore, ed è tutto il motivo per cui il rilevatore gira in locale.
            continue
        analisi.entita.append(Entita(
            etichetta=etichetta,
            valore=valore,
            validato=bool(segmento.get("validated")),
            fonte=segmento.get("src", ""),
        ))
    return analisi
