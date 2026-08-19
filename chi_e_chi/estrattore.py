"""Il giro: **si maschera, si legge, si mappa**.

    1. ANONIMIZZARE   rizzo-pii, in locale, sostituisce ogni dato personale con un
                      segnaposto e tiene la mappa. La mappa **non esce da questo processo**.
    2. LEGGERE        il modello riceve il testo mascherato e risponde con che cosa c'è nel
                      documento: entità, ruoli, attributi, relazioni. Una domanda sola.
    3. MAPPARE        la lettura si traduce nelle schede, rimettendo i valori veri dalla
                      mappa. Qui, in locale.

## Perché il passaggio 2 esiste

Un rilevatore di entità dà **tipi, non ruoli**. Su un contratto di assunzione trova due
`FULLNAME`, tre `STREET`, due `CF`, cinque `DATE` — e ha ragione su tutti. Ma «qui ci sono
due persone» non è «questa è quella che stai assumendo», e nessuna quantità di
riconoscimento di entità colma quella distanza: il ruolo non sta nel dato, sta **nelle
parole intorno**, che non sono dati personali e quindi restano leggibili nel testo che esce.

## Perché non c'è un passaggio prima

C'era. Il rilevatore attribuiva quello che sapeva attribuire da solo — «di email ce n'è una,
sarà la sua» — e al modello si chiedeva solo il resto, campo per campo. Funzionava, e
perdeva dati nelle cuciture: la nazionalità mascherata come nome proprio, la PEC aziendale
nel campo del dipendente, i campi del contratto che nessuno pensava a chiedere.

Erano tutti lo stesso difetto, ed era architetturale. **Un anonimizzatore non è un
estrattore**, e ogni volta che gli si chiedeva un ruolo bisognava aggiungere un pezzo per
correggere la risposta. Ora il compito di capire è tutto del modello, il compito di
anonimizzare è tutto del rilevatore, e il compito di decidere se un dato è valido resta del
codice — dove è sempre stato.
"""

from __future__ import annotations

import time

from . import lettura as contratto
from . import modello as mod
from . import pii, scheda
from .scheda import Esito, Passo


def estrai(
    testo: str,
    tipo: str = "persona",
    *,
    cliente: mod.Cliente | None = None,
    servizio=pii,
) -> Esito:
    """Da un documento a una scheda. **Non salva niente**: torna una proposta.

    `tipo` è `persona` o `locale`. `servizio` e `cliente` sono iniettabili: un test che
    dipende da un container acceso è un test che diventa rosso quando qualcuno spegne una
    macchina, e che nessuno prende più sul serio.
    """
    if tipo not in scheda.TABELLE:
        raise ValueError(f"scheda sconosciuta: «{tipo}». Ci sono: {', '.join(scheda.TABELLE)}")

    avvio = time.monotonic()
    analisi = servizio.analizza(testo)
    tipi = sorted({e.etichetta for e in analisi.entita})
    traccia = [Passo(
        "1 · anonimizzazione (in locale)",
        f"{len(analisi.entita)} entità, {len(tipi)} tipi ({', '.join(tipi) or '—'}); "
        f"{len(analisi.mappa)} segnaposto. Da qui in poi esce solo il testo mascherato.",
        int((time.monotonic() - avvio) * 1000),
    )]

    anonimo = (analisi.anonimizzato or "").strip()
    if not anonimo:
        return _resa(
            tipo, traccia, "",
            "Il rilevatore non ha prodotto testo mascherato: senza quello non si manda "
            "niente fuori, e non c'è niente da leggere.",
        )

    avvio = time.monotonic()
    try:
        risposta = (cliente or mod.cliente()).genera(mod.Domanda(
            istruzione=contratto.ISTRUZIONE,
            fatti=f"{contratto.FATTI[tipo]}\n\n--- TESTO ANONIMIZZATO ---\n{anonimo}\n"
                  "--- FINE ---",
            parole_massime=contratto.PAROLE_MASSIME,
        ))
    except mod.ModelloNonDisponibile as errore:
        return _resa(
            tipo, traccia + [Passo("2 · lettura", f"non disponibile: {errore}")], anonimo,
            f"Il modello non è disponibile ({errore}). Senza di lui il documento resta "
            "leggibile solo da una persona: il rilevatore sa che lì c'è un nome, non di chi "
            "è.",
        )

    letto = contratto.json_di(risposta)
    traccia.append(Passo(
        "2 · lettura sul testo mascherato",
        _riassunto(letto),
        int((time.monotonic() - avvio) * 1000),
    ))

    # I valori tornano **prima** della mappatura: da lì in poi si lavora su dati veri, e la
    # divisione del nome, il checksum e le date hanno qualcosa da mordere.
    esito = scheda.TABELLE[tipo](scheda.ricomponi(letto, analisi.mappa))
    esito.traccia = traccia + [Passo(
        "3 · mappatura sulla scheda",
        f"{len(esito.campi)} campi compilati, {len(esito.non_trovati)} da scrivere a mano.",
    )]
    esito.anonimizzato = anonimo
    esito.valori_usciti = _sfuggiti(anonimo, analisi.mappa)
    return esito


def _sfuggiti(anonimo: str, mappa: dict[str, str]) -> list[str]:
    """I valori mascherati che nel testo uscito compaiono lo stesso.

    Va calcolato **qui**, dove la mappa è in mano. Dopo non si può più — e cercare i campi
    della scheda dentro il testo, che è l'unica cosa possibile a valle, trova «pizzaiolo» e
    «indeterminato»: parole che non sono mai state dati personali e che l'anonimizzatore ha
    lasciato lì di proposito. Un controllo che grida al lupo su quelle non lo guarda nessuno.

    I valori corti si saltano: un civico «9» o un CAP dentro una data darebbero un allarme
    per una coincidenza di cifre.
    """
    return [v for v in dict.fromkeys(mappa.values()) if v and len(v) > 4 and v in anonimo]


def _resa(tipo: str, traccia: list[Passo], anonimo: str, avviso: str) -> Esito:
    """Quando non si può leggere, si torna una scheda vuota **e si dice perché**.

    Vuota e non un'eccezione: il programma senza modello funziona, perde la compilazione
    automatica e non la scheda. La differenza la deve vedere chi guarda, non chi legge il
    codice a valle.
    """
    esito = scheda.TABELLE[tipo]({})
    esito.traccia = traccia
    esito.anonimizzato = anonimo
    esito.avvisi.append(avviso)
    return esito


def _riassunto(letto: dict) -> str:
    entita = letto.get("entita") if isinstance(letto.get("entita"), list) else []
    relazioni = letto.get("relazioni") if isinstance(letto.get("relazioni"), list) else []
    ruoli = [str(e.get("ruolo", "?")) for e in entita if isinstance(e, dict)]
    testa = letto.get("documento") if isinstance(letto.get("documento"), dict) else {}
    return (
        f"{testa.get('natura', '?')} · verso {testa.get('verso', '?')} · "
        f"{len(entita)} entità ({', '.join(ruoli) or '—'}), {len(relazioni)} relazioni. "
        "Il fornitore del modello non ha visto un solo dato personale."
    )
