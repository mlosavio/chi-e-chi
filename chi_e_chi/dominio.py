"""Quello che il codice sa decidere da solo, senza chiedere a nessuno.

È la parte che conta più di quanto sembri. Un modello linguistico **propone**; qui si
**decide** — e su un codice fiscale non c'è niente da proporre: o il carattere di controllo
torna, o quel codice è sbagliato, e nessuna rilettura lo migliora.

Le tre cose che stanno qui sono aritmetica e lingua italiana:

* il **checksum** del codice fiscale, e i dati che se ne ricavano (data di nascita, sesso);
* la **coerenza** fra un codice fiscale e un nome — che è ciò che permette di scegliere,
  fra tre nomi in un contratto, quello che quel codice genera;
* le **date come le scrivono i documenti**: «12 agosto 1994», «1° settembre 2026».

Ogni riga qui è una riga che non si chiede a un modello.
"""

from __future__ import annotations

import re
from datetime import date

# --------------------------------------------------------------------------
# Codice fiscale

FORMATO = re.compile(r"^[A-Z]{6}\d{2}[ABCDEHLMPRST]\d{2}[A-Z]\d{3}[A-Z]$")
MESI_CF = "ABCDEHLMPRST"
VOCALI = set("AEIOU")

_DISPARI = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}
_PARI = {c: i for i, c in enumerate("0123456789")}
_PARI.update({c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")})
_RESTO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def pulisci(grezzo: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (grezzo or "").upper())


def carattere_di_controllo(primi15: str) -> str:
    somma = sum(
        _DISPARI[c] if posto % 2 == 0 else _PARI[c]
        for posto, c in enumerate(primi15)
    )
    return _RESTO[somma % 26]


def valido(grezzo: str) -> bool:
    """**L'unico controllo che non è un'euristica.**

    Sedici caratteri con la forma giusta e il carattere finale che torna: un codice fiscale
    letto male da una scansione lo si scopre qui, non a valle.
    """
    codice = pulisci(grezzo)
    if len(codice) != 16 or not FORMATO.match(codice):
        return False
    return carattere_di_controllo(codice[:15]) == codice[15]


def data_e_sesso(grezzo: str) -> tuple[date, str] | None:
    """Dal codice fiscale, la data di nascita e il sesso. **Sono dentro il codice.**

    È il dato che *contiene* gli altri: quando in un documento ci sono quattro date e non si
    sa quale sia la nascita, questa non è una fra le quattro — è quella giusta, calcolata.
    """
    codice = pulisci(grezzo)
    if not valido(codice):
        return None
    anno_due = int(codice[6:8])
    mese = MESI_CF.index(codice[8]) + 1
    giorno = int(codice[9:11])
    sesso = "F" if giorno > 40 else "M"
    if sesso == "F":
        giorno -= 40

    # **Il secolo non è nel codice fiscale.** Due cifre per l'anno, e chi le ha scelte nel
    # 1973 non pensava al 2000. Si prende la più recente delle due date che non sia nel
    # futuro: `94` è il 1994, `06` è il 2006, e nessuno dei due nasce domani.
    possibili = []
    for secolo in (1900, 2000):
        try:
            nato = date(secolo + anno_due, mese, giorno)
        except ValueError:
            continue
        if nato <= date.today():
            possibili.append(nato)
    return (max(possibili), sesso) if possibili else None


def _tre_lettere(pezzo: str, e_nome: bool) -> str:
    testo = re.sub(r"[^A-Z]", "", (pezzo or "").upper())
    consonanti = [c for c in testo if c not in VOCALI]
    vocali = [c for c in testo if c in VOCALI]
    # Regola del nome: con quattro o più consonanti si prendono la prima, la terza e la
    # quarta. È una stranezza vera della norma, e senza di essa metà dei nomi non torna.
    if e_nome and len(consonanti) >= 4:
        consonanti = [consonanti[0], consonanti[2], consonanti[3]]
    tutte = consonanti + vocali
    return (("".join(tutte) + "XXX")[:3]) if tutte else "XXX"


def coerente_con(codice: str, cognome: str, nome: str) -> bool:
    """**Questo codice fiscale è di questa persona?**

    Le prime sei lettere si ricavano da cognome e nome con una regola deterministica: si
    ricalcolano e si confrontano. È la funzione che, fra tre nomi in un contratto di
    assunzione, dice quale è il dipendente — senza chiederlo a nessuno.
    """
    pulito = pulisci(codice)
    if len(pulito) < 6:
        return False
    return pulito[:6] == _tre_lettere(cognome, False) + _tre_lettere(nome, True)


def dividi_nome(completo: str) -> tuple[str, str]:
    """Senza codice fiscale si tira a indovinare, e lo si dichiara: l'ultima parola come
    cognome è la convenzione più diffusa fuori dai documenti ufficiali."""
    pezzi = (completo or "").split()
    if len(pezzi) < 2:
        return completo, ""
    return pezzi[-1], " ".join(pezzi[:-1])


def nome_dal_codice(nomi: list[str], codice: str) -> tuple[str, str] | None:
    """Quale dei nomi trovati genera quel codice fiscale, e **in quale ordine**.

    Provare entrambi gli ordini scioglie anche l'ambiguità di «ROSSI Mario» contro «Mario
    Rossi», che in italiano non si risolve guardando la stringa.
    """
    for completo in nomi:
        pezzi = completo.split()
        if len(pezzi) < 2:
            continue
        for taglio in range(1, len(pezzi)):
            for cognome, nome in (
                (" ".join(pezzi[:taglio]), " ".join(pezzi[taglio:])),
                (" ".join(pezzi[taglio:]), " ".join(pezzi[:taglio])),
            ):
                if coerente_con(codice, cognome, nome):
                    return cognome, nome
    return None


# --------------------------------------------------------------------------
# Date come le scrivono i documenti

MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def leggi_data(testo: str) -> str:
    """«12 agosto 1994» → «1994-08-12». Stringa vuota se non è una data.

    Sui documenti ufficiali le date si scrivono **per esteso**, quasi sempre. Leggere solo
    `12/08/1994` significa perdere la data di nascita su ogni lettera di assunzione scritta
    come si scrivono le lettere di assunzione — cioè su tutte.
    """
    grezzo = (testo or "").strip().replace("°", "").replace("º", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", grezzo):
        return grezzo

    numerica = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", grezzo)
    if numerica:
        giorno, mese, anno = (int(x) for x in numerica.groups())
        return _componi(anno, mese, giorno)

    esteso = re.fullmatch(
        r"(\d{1,2})\s*(?:di\s+)?([A-Za-zàèéìòù]+)\s+(\d{4})", grezzo, re.IGNORECASE
    )
    if esteso:
        giorno, mese_testo, anno = esteso.groups()
        mese_testo = mese_testo.lower()
        for indice, nome in enumerate(MESI, 1):
            if nome.startswith(mese_testo[:3]) and mese_testo.startswith(nome[:3]):
                return _componi(int(anno), indice, int(giorno))
    return ""


def _componi(anno: int, mese: int, giorno: int) -> str:
    try:
        return date(anno, mese, giorno).isoformat()
    except ValueError:
        return ""
