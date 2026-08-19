"""Passaggio 2 · che cosa si chiede al modello.

**Non un modulo da riempire: una lettura.**

La differenza non è stilistica. Chiedere «qual è la data di assunzione» è chiedere una riga
di una tabella che il modello deve comunque ricostruire per intero — e ogni riga che non si
pensa a chiedere è una riga persa. Chiedere «dimmi che cosa c'è dentro» la fa costruire una
volta sola, completa, e lascia a noi il compito di prenderne quello che ci serve.

Il contratto è questo:

    {
      "documento": {"natura": …, "verso": "chiaro"|"incerto", "spiegazione": …},
      "entita":    [{"tipo": …, "ruolo": …, "attributi": {…}}],
      "relazioni": [{"tipo": …, "attributi": {…}}]
    }

Il **ruolo** è la cosa che l'esempio esiste per mostrare. Un rilevatore di entità dà tipi:
due `FULLNAME`, tre `STREET`, cinque `DATE`, e ha ragione su tutti. Ma «qui ci sono due
persone» non è «questa è quella che stai assumendo». Il ruolo non sta nel dato, sta **nelle
parole intorno** — «Egr. Sig.», «con sede legale in», «in qualità di legale rappresentante»,
la firma in calce — e quelle parole non sono dati personali, quindi non vengono mascherate,
quindi restano leggibili nel testo che esce.

È tutto quello che serve al modello, ed è tutto quello che gli arriva.
"""

from __future__ import annotations

import json
import re

NATURE = (
    "contratto_lavoro", "lettera_assunzione", "contratto_affitto", "licenza", "visura",
    "certificazione", "assicurazione", "identita", "codice_fiscale", "permesso_soggiorno",
    "busta_paga", "altro",
)
"""Che documento è. Serve ad archiviarlo **già classificato**, invece di chiederlo a chi lo
ha appena letto."""

RUOLI = (
    "lavoratore", "datore", "legale_rappresentante", "locatore", "conduttore",
    "sede_di_lavoro", "immobile", "intestatario", "altro",
)

PAROLE_MASSIME = 2000
"""Una lettura completa sta in poche centinaia di parole. Il margine serve ai documenti con
molte parti — un contratto di locazione ne ha quattro fra locatore, conduttore, legale
rappresentante e immobile — e una risposta troncata è una lettura persa per intero."""


ISTRUZIONE = """\
Leggi un documento amministrativo italiano e dì **che cosa c'è dentro**.

Il testo che ricevi è stato ANONIMIZZATO: ogni dato personale è sostituito da un segnaposto
della forma [TIPO_numero]. Non sai cosa nascondono e non devi indovinarlo — riportali tali
e quali. Le parole intorno NON sono mascherate: «Egr. Sig.», «con sede legale in», «nato a»,
«il conduttore», la firma in calce. Sono quelle che dicono a chi appartiene ogni segnaposto,
ed è tutto quello che ti serve.

Rispondi SOLO con un oggetto JSON, senza testo prima o dopo:

{
  "documento": {
    "natura": una fra: contratto_lavoro, lettera_assunzione, contratto_affitto, licenza,
              visura, certificazione, assicurazione, identita, codice_fiscale,
              permesso_soggiorno, busta_paga, altro,
    "verso": "chiaro" se distingui con certezza chi emette da chi riceve, "incerto" se no,
    "spiegazione": una riga sul perché, citando le parole del testo che te lo dicono
  },
  "entita": [
    { "tipo": "persona" | "organizzazione" | "luogo",
      "ruolo": che ruolo ha NEL DOCUMENTO — vedi sotto,
      "attributi": { ... vedi sotto ... } }
  ],
  "relazioni": [
    { "tipo": "rapporto_di_lavoro" | "locazione",
      "attributi": { ... vedi sotto ... } }
  ]
}

RUOLI possibili: lavoratore, datore, legale_rappresentante, locatore, conduttore,
sede_di_lavoro, immobile, intestatario, altro.

ATTRIBUTI di una **persona**: nome_completo, codice_fiscale, data_nascita, luogo_nascita,
sesso, nazionalita, via, civico, cap, citta, provincia, telefono, email.

ATTRIBUTI di una **organizzazione**: denominazione, partita_iva, codice_fiscale, via,
civico, cap, citta, provincia, telefono, email.

ATTRIBUTI di un **luogo**: denominazione, via, civico, cap, citta, provincia, superficie_mq,
posti.

ATTRIBUTI di un **rapporto_di_lavoro**: data_inizio, data_fine, tipo_contratto
(indeterminato, determinato, apprendistato, stagionale, somministrazione, intermittente),
ore_settimanali, mansione, livello_inquadramento, ccnl, retribuzione_oraria, sede.

ATTRIBUTI di una **locazione**: data_inizio, data_fine, canone_mensile, superficie_mq,
destinazione_uso, insegna.

REGOLE INDEROGABILI
- Metti un attributo solo se nel documento **c'è scritto**. Non dedurre, non completare, non
  indovinare: quello che manca si omette, e basta.
- Non mescolare le parti. La sede legale dell'azienda non è la residenza del dipendente, il
  centralino non è il suo telefono, la PEC aziendale non è la sua email, chi firma per
  l'azienda non è chi viene assunto. Ogni attributo va sull'entità a cui appartiene.
- Se "verso" è "incerto", metti "entita" e "relazioni" **vuote**. Mescolare le parti è peggio
  che non compilare: un campo vuoto si vede, un campo sbagliato no.
- I segnaposto si riportano tali e quali, anche quando ne servono due insieme
  («[STREET_2] [BUILDINGNUM_2]»). Non inventarne di nuovi.
- Numeri, date e importi si riportano come sono scritti. Le date anche per esteso:
  «1° settembre 2026» va bene così.
"""


FATTI = {
    "persona": (
        "Il documento riguarda una persona da assumere o già in organico, e di solito il suo "
        "rapporto di lavoro. Documenti tipici: lettera di assunzione, contratto individuale, "
        "carta d'identità, busta paga, permesso di soggiorno.\n"
        "Interessa il **lavoratore**: chi riceve la lettera, chi viene assunto, chi è "
        "intestatario del documento. Il datore e chi firma per lui vanno riportati come "
        "entità distinte, con il loro ruolo."
    ),
    "locale": (
        "Il documento riguarda un locale: un negozio, una filiale, una sede operativa. "
        "Documenti tipici: contratto di locazione, visura camerale, licenza commerciale.\n"
        "Interessa il **locale**: dove si trova, come si chiama l'insegna, quanto è grande. "
        "Locatore e conduttore vanno riportati come entità distinte, con il loro ruolo — "
        "l'indirizzo della sede legale di una società non è l'indirizzo del locale."
    ),
}


class LetturaIlleggibile(Exception):
    """La risposta non è JSON. Chi chiama lo dice a chi legge, con un messaggio che indica
    **cosa fare**, non cosa è successo dentro."""


def json_di(risposta: str) -> dict:
    """Il JSON della risposta, tolta la cornice che il modello a volte ci mette intorno.

    Rifiutare una risposta giusta per tre backtick sarebbe il modo più stupido di perdere
    una lettura.
    """
    grezzo = re.sub(r"^```(?:json)?\s*|\s*```$", "", (risposta or "").strip()).strip()
    try:
        dati = json.loads(grezzo)
    except json.JSONDecodeError as errore:
        # Due cause diverse, due messaggi diversi: una risposta troncata è un difetto nostro
        # — il tetto sulle parole — e mandare a rifare una scansione che andava benissimo
        # sposta la colpa sulla persona sbagliata.
        troncata = len(grezzo) > 200 and not grezzo.rstrip().endswith("}")
        raise LetturaIlleggibile(
            "la lettura si è interrotta a metà: la risposta non ci è entrata"
            if troncata else
            "il documento non ha prodotto dati utilizzabili"
        ) from errore
    return dati if isinstance(dati, dict) else {}
