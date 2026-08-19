"""Passaggio 3 · dalla lettura alle schede.

Qui non c'è interpretazione: c'è una **tabella**. La lettura del modello dice che nel
documento c'è una persona con ruolo `lavoratore` e questi attributi; questa tabella dice in
quale campo della scheda va ciascuno. Nient'altro.

Tenere separati i due passaggi è il motivo per cui, quando qualcosa non torna, si sa quale
dei due ha sbagliato. Se il modello ha messo la PEC aziendale sull'entità sbagliata, si vede
nella lettura. Se il campo è finito nel posto sbagliato, si vede qui. Mescolarli — chiedere
al modello direttamente i campi della scheda — rende le due cose indistinguibili, ed è
esattamente com'era prima.

Due casi, e sono la prova che la stessa lettura serve schede diverse:

    persona  →  il lavoratore, il suo rapporto di lavoro
    locale   →  l'immobile, che è l'**oggetto** dell'atto e non una delle parti
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import dominio, pii

VUOTI_TRAVESTITI = {
    "", "-", "--", "–", "—", "n/a", "n.a.", "na", "null", "none", "nessuno",
    "non disponibile", "non indicato", "non specificato", "non presente", "sconosciuto",
    "assente", "vuoto",
}
"""L'istruzione dice di omettere quello che manca, e quasi sempre il modello obbedisce. Ma
«non indicato» dentro un campo **è peggio di un campo vuoto**: un campo vuoto si vede e si
compila, un campo che contiene una scusa sembra un dato e resta lì."""


@dataclass
class Passo:
    """Una riga della traccia. L'esempio è fatto per essere **guardato mentre lavora**."""

    nome: str
    dettaglio: str
    durata_ms: int = 0


@dataclass
class Esito:
    campi: dict[str, str] = field(default_factory=dict)
    non_trovati: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)
    parti: dict[str, str] = field(default_factory=dict)
    """Chi è chi, come lo ha stabilito il modello, con la sua spiegazione. È il risultato che
    dà il nome al progetto."""
    tipo_documento: str = ""
    fonte: str = "anonimizzato"
    anonimizzato: str = ""
    """Il testo così com'è uscito. **Si conserva per poterlo guardare**: la promessa «non è
    uscito niente» va mostrata, non raccontata."""
    valori_usciti: list[str] = field(default_factory=list)
    """I valori personali che l'anonimizzatore aveva mascherato e che nel testo uscito
    compaiono comunque. **Deve essere vuota**, e si calcola dove la mappa è in mano — non a
    valle, dove ci si ridurrebbe a cercare i campi della scheda nel testo e a trovarci
    «pizzaiolo», che non è un dato personale e non lo è mai stato."""
    nome_completo: str = ""
    """Il nome come lo scrive il documento, prima di dividerlo. Serve al codice fiscale, che
    l'ordine lo calcola — e per calcolarlo gli servono le parole nell'ordine originale."""
    traccia: list[Passo] = field(default_factory=list)

    def come_dizionario(self) -> dict:
        return {
            "campi": self.campi,
            "non_trovati": self.non_trovati,
            "avvisi": self.avvisi,
            "parti": self.parti,
            "tipo_documento": self.tipo_documento,
            "fonte": self.fonte,
        }


CAMPI_ATTESI = {
    "persona": ("cognome", "nome", "codice_fiscale", "data_nascita", "nazionalita",
                "telefono", "email", "via", "cap", "citta", "provincia", "datore",
                "data_assunzione", "tipo_contratto", "monte_ore_settimanale", "mansione"),
    "locale": ("nome", "via", "cap", "citta", "provincia", "telefono", "email", "capienza"),
}


# --------------------------------------------------------------------------
# Le due tabelle


def persona(lettura: dict) -> Esito:
    """Il lavoratore e il suo rapporto di lavoro."""
    esito = _testa(lettura)
    if esito.parti.get("verso") == "incerto":
        return esito

    persone = _entita(lettura, "persona")
    lavoratore = (
        _con_ruolo(persone, "lavoratore", "intestatario")
        # Un documento con una persona sola — una carta d'identità — non ha ruoli da
        # distinguere: quella è la persona, e chiederle un ruolo sarebbe pedanteria.
        or (persone[0] if len(persone) == 1 else None)
    )
    if lavoratore is None:
        if len(persone) > 1:
            esito.avvisi.append(
                f"Il documento parla di {len(persone)} persone e non dice quale sia il "
                "lavoratore: i campi restano da compilare."
            )
        return _chiudi(esito, "persona")

    attributi = lavoratore.get("attributi") or {}
    _porta(esito, attributi, {
        "codice_fiscale": "codice_fiscale",
        "data_nascita": "data_nascita",
        "nazionalita": "nazionalita",
        "telefono": "telefono",
        "email": "email",
        "cap": "cap",
        "citta": "citta",
        "provincia": "provincia",
    })
    esito.campi["via"] = _via(attributi)
    _nome(esito, attributi.get("nome_completo"))

    rapporto = _relazione(lettura, "rapporto_di_lavoro")
    _porta(esito, rapporto, {
        "data_inizio": "data_assunzione",
        "tipo_contratto": "tipo_contratto",
        "ore_settimanali": "monte_ore_settimanale",
        "mansione": "mansione",
        "livello_inquadramento": "livello_inquadramento",
        "retribuzione_oraria": "retribuzione_oraria",
    })

    datore = _con_ruolo(_entita(lettura, "organizzazione"), "datore")
    if datore:
        esito.campi["datore"] = _valore((datore.get("attributi") or {}).get("denominazione"))
    sede = _con_ruolo(_entita(lettura, "luogo", "organizzazione"), "sede_di_lavoro")
    if sede:
        suoi = sede.get("attributi") or {}
        esito.campi["sede_lavoro"] = _valore(suoi.get("denominazione")) or _valore(
            suoi.get("citta")
        )
    return _chiudi(esito, "persona")


def locale(lettura: dict) -> Esito:
    """L'immobile: **l'oggetto dell'atto, non una delle parti**.

    In un contratto di locazione ci sono tre indirizzi — la sede del locatore, quella del
    conduttore e l'immobile — e solo il terzo è il locale. È la distinzione che una ricerca
    per tipo di entità non può fare, e che il ruolo rende banale.
    """
    esito = _testa(lettura)
    if esito.parti.get("verso") == "incerto":
        return esito

    luoghi = _entita(lettura, "luogo")
    immobile = (
        _con_ruolo(luoghi, "immobile", "sede_di_lavoro")
        or (luoghi[0] if len(luoghi) == 1 else None)
    )
    if immobile is None:
        esito.avvisi.append(
            "Il documento non identifica un locale: i campi restano da compilare."
        )
        return _chiudi(esito, "locale")

    attributi = immobile.get("attributi") or {}
    _porta(esito, attributi, {
        "denominazione": "nome",
        "cap": "cap",
        "citta": "citta",
        "provincia": "provincia",
        "telefono": "telefono",
        "email": "email",
        "posti": "capienza",
    })
    esito.campi["via"] = _via(attributi)

    locazione = _relazione(lettura, "locazione")
    # L'insegna sta nel contratto, non sull'immobile: «per esercitarvi l'attività con
    # l'insegna X» è la frase che dà il nome al locale.
    if _valore(locazione.get("insegna")) and not esito.campi.get("nome"):
        esito.campi["nome"] = _valore(locazione["insegna"])
    if _valore(locazione.get("superficie_mq")) and not esito.campi.get("capienza"):
        esito.avvisi.append(
            f"Il contratto dà la superficie ({locazione['superficie_mq']} mq), non i posti: "
            "la capienza va scritta a mano."
        )
    return _chiudi(esito, "locale")


TABELLE = {"persona": persona, "locale": locale}


# --------------------------------------------------------------------------
# Gli attrezzi


def _testa(lettura: dict) -> Esito:
    from . import lettura as contratto

    testa = lettura.get("documento") if isinstance(lettura.get("documento"), dict) else {}
    natura = str(testa.get("natura") or "").strip().lower()
    esito = Esito(
        tipo_documento=natura if natura in contratto.NATURE else "",
        parti={
            "verso": str(testa.get("verso") or "chiaro").strip().lower(),
            "spiegazione": str(testa.get("spiegazione") or ""),
        },
    )
    if esito.parti["verso"].startswith("incert"):
        esito.parti["verso"] = "incerto"
        esito.avvisi.append(
            "Non si capisce il verso del documento: chi lo emette e chi lo riceve. Senza "
            "quello i dati delle due parti si mescolano — la sede legale finisce nel "
            "domicilio — e una scheda mescolata è peggio di una vuota."
        )
    return esito


def _entita(lettura: dict, *tipi: str) -> list[dict]:
    voci = lettura.get("entita")
    if not isinstance(voci, list):
        return []
    return [v for v in voci if isinstance(v, dict) and str(v.get("tipo", "")).lower() in tipi]


def _con_ruolo(voci: list[dict], *ruoli: str) -> dict | None:
    for ruolo in ruoli:
        for v in voci:
            if str(v.get("ruolo", "")).lower() == ruolo:
                return v
    return None


def _relazione(lettura: dict, tipo: str) -> dict:
    voci = lettura.get("relazioni")
    if not isinstance(voci, list):
        return {}
    for v in voci:
        if isinstance(v, dict) and str(v.get("tipo", "")).lower() == tipo:
            attributi = v.get("attributi")
            return attributi if isinstance(attributi, dict) else {}
    return {}


def _valore(grezzo) -> str:
    """Il testo di un attributo, o stringa vuota se è un modo di dire «non c'è»."""
    pulito = str(grezzo if grezzo is not None else "").strip()
    return "" if pulito.lower().rstrip(".") in VUOTI_TRAVESTITI else pulito


def _porta(esito: Esito, sorgente: dict, corrispondenze: dict[str, str]) -> None:
    for da, a in corrispondenze.items():
        valore = _valore(sorgente.get(da))
        if valore:
            esito.campi[a] = valore


def _via(attributi: dict) -> str:
    """Via e civico sono due attributi e un campo solo. Unirli qui è più affidabile che
    chiedere al modello di unirli: due segnaposto separati si ricompongono senza ambiguità."""
    via = _valore(attributi.get("via"))
    civico = _valore(attributi.get("civico"))
    return f"{via} {civico}".strip() if via else ""


def _nome(esito: Esito, completo) -> None:
    """Il nome intero si divide **dopo** averlo ricomposto.

    Il modello non può dividerlo: vede `[FULLNAME_1]`. Qui il valore è già vero, e la
    divisione è un problema di lingua italiana — che risolve il dominio, e meglio ancora il
    codice fiscale, se c'è.
    """
    testo = _valore(completo)
    if not testo:
        return
    esito.nome_completo = testo
    cognome, nome = dominio.dividi_nome(testo)
    if cognome:
        esito.campi["cognome"] = cognome
    if nome:
        esito.campi["nome"] = nome


def _chiudi(esito: Esito, tipo: str) -> Esito:
    """Il codice fiscale certifica, il dominio valida, e quello che manca si dice."""
    esito.campi = {c: v for c, v in esito.campi.items() if str(v).strip()}
    _certifica_col_codice_fiscale(esito)
    _controlla(esito)
    esito.non_trovati = [c for c in CAMPI_ATTESI[tipo] if c not in esito.campi]
    esito.avvisi = list(dict.fromkeys(esito.avvisi))
    return esito


# --------------------------------------------------------------------------
# Quello che decide il codice, e il modello non tocca


def _certifica_col_codice_fiscale(esito: Esito) -> None:
    """**Il modello dice chi, l'aritmetica dice come si scrive.**

    È il passaggio in cui i due mondi si incontrano e ognuno fa quello che sa fare. Il
    modello ha detto che il lavoratore è «Karim Ben Salah»; dividere quella stringa in
    cognome e nome è un indovinello, perché in italiano si scrivono entrambi gli ordini. Ma
    se c'è un codice fiscale coerente con quel nome, l'ordine **non si indovina più: si
    calcola** — le prime sei lettere sono consonanti di cognome e nome, in quest'ordine.

    E da lì discendono la data di nascita e il sesso, che nel codice ci sono già. Nessuna
    rilettura li migliora: sono aritmetica.
    """
    fiscale = (esito.campi.get("codice_fiscale") or "").replace(" ", "").upper()
    if not fiscale or not dominio.valido(fiscale):
        return
    esito.campi["codice_fiscale"] = fiscale

    completo = esito.nome_completo or (
        f"{esito.campi.get('cognome', '')} {esito.campi.get('nome', '')}".strip()
    )
    scelto = dominio.nome_dal_codice([completo], fiscale) if completo else None
    if scelto:
        esito.campi["cognome"], esito.campi["nome"] = scelto

    anagrafe = dominio.data_e_sesso(fiscale)
    if not anagrafe:
        return
    atteso = anagrafe[0].isoformat()
    letta = esito.campi.get("data_nascita")
    # Si confronta **dopo** aver normalizzato: «16 febbraio 1997» e «1997-02-16» sono la
    # stessa data, e segnalarle come discordanti insegnerebbe a ignorare gli avvisi.
    if letta and dominio.leggi_data(letta) not in ("", atteso):
        esito.avvisi.append(
            f"La data di nascita letta ({letta}) non è quella che dà il codice fiscale "
            f"({atteso}): vale il codice fiscale."
        )
    esito.campi["data_nascita"] = atteso


def _controlla(esito: Esito) -> None:
    """Gli stessi controlli che si farebbero su un dato scritto a mano.

    Il modello propone, il codice esatto decide. Un codice fiscale con il carattere di
    controllo sbagliato non entra nella scheda con l'aria di essere giusto: è esattamente il
    dato che nessuno riverifica dopo che «l'ha letto il computer».
    """
    fiscale = esito.campi.get("codice_fiscale")
    if fiscale and not dominio.valido(fiscale):
        del esito.campi["codice_fiscale"]
        esito.avvisi.append(
            f"Il codice fiscale letto («{fiscale}») non supera il controllo del carattere "
            "finale: non è stato messo nella scheda. Ricopialo dal documento."
        )

    grezza = esito.campi.get("nazionalita")
    if grezza:
        codice = dominio.nazionalita(grezza)
        if codice:
            esito.campi["nazionalita"] = codice
        else:
            del esito.campi["nazionalita"]
            esito.avvisi.append(
                f"«{grezza}» non l'ho saputa tradurre in un codice paese di due lettere: "
                "il campo è rimasto vuoto."
            )

    provincia = esito.campi.get("provincia")
    if provincia:
        sigla = dominio.provincia(provincia)
        if sigla:
            esito.campi["provincia"] = sigla
        else:
            del esito.campi["provincia"]
            esito.avvisi.append(
                f"«{provincia}» non è una provincia italiana: il campo è rimasto vuoto."
            )

    cap = esito.campi.get("cap")
    if cap and not re.fullmatch(r"\d{5}", cap.strip()):
        del esito.campi["cap"]

    # I numeri arrivano come li scrive il documento: «40 ore settimanali», «9,50 euro».
    for campo in ("monte_ore_settimanale", "capienza", "retribuzione_oraria"):
        grezzo = esito.campi.get(campo)
        if not grezzo:
            continue
        numero = re.search(r"\d+(?:[.,]\d+)?", str(grezzo))
        if numero:
            esito.campi[campo] = numero.group(0).replace(",", ".")
        else:
            del esito.campi[campo]

    # Le date come le scrivono i documenti: «1° settembre 2026».
    for campo in ("data_nascita", "data_assunzione"):
        grezza_data = esito.campi.get(campo)
        if not grezza_data:
            continue
        iso = dominio.leggi_data(grezza_data)
        if iso:
            esito.campi[campo] = iso
        else:
            del esito.campi[campo]


# --------------------------------------------------------------------------
# La ricomposizione: i segnaposto tornano valori, **qui**


def ricomponi(dati, mappa: dict[str, str]):
    """Cammina la lettura e rimette i valori veri **ovunque**.

    Ricorsiva di proposito: i segnaposto compaiono negli attributi, nelle relazioni e nella
    spiegazione del modello, e una funzione che ne conoscesse la forma si romperebbe alla
    prima chiave aggiunta — in silenzio, lasciando a video il nome di un segnaposto.

    La mappa non è mai uscita da questo processo, e qui rientra tutto quello che serve.
    """
    if isinstance(dati, dict):
        return {c: ricomponi(v, mappa) for c, v in dati.items()}
    if isinstance(dati, list):
        return [ricomponi(v, mappa) for v in dati]
    if isinstance(dati, str):
        vero = pii.ricomponi(dati, mappa)
        # Un segnaposto che nella mappa non c'è resta tale e quale: non è un dato, e nella
        # scheda non ci entra.
        return "" if _e_un_segnaposto(vero) else vero
    return dati


def _e_un_segnaposto(testo: str) -> bool:
    pulito = (testo or "").strip()
    return bool(pulito) and bool(re.fullmatch(r"(\[[A-Z_]+_\d+\]\s*)+", pulito))
