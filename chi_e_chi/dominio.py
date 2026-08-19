"""Quello che il codice sa decidere da solo, senza chiedere a nessuno.

È la parte che conta più di quanto sembri. Un modello linguistico **propone**; qui si
**decide** — e su un codice fiscale non c'è niente da proporre: o il carattere di controllo
torna, o quel codice è sbagliato, e nessuna rilettura lo migliora.

Le cose che stanno qui sono aritmetica, elenchi chiusi e lingua italiana:

* il **checksum** del codice fiscale, e i dati che se ne ricavano (data di nascita, sesso);
* la **coerenza** fra un codice fiscale e un nome — che è ciò che permette di scegliere,
  fra tre nomi in un contratto, quello che quel codice genera;
* le **date come le scrivono i documenti**: «12 agosto 1994», «1° settembre 2026»;
* i **nomi dei paesi e delle province**, che un documento scrive a parole — «di nazionalità
  nigeriana», «provincia di Bari» — e una scheda vuole in codice.

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
# Elenchi chiusi: paesi e province
#
# **Perché elenchi e non campi liberi.** Un documento scrive «di nazionalità nigeriana» e la
# scheda vuole `NG`; scrive «provincia di Bari» e la scheda vuole `BA`. Se ci finisce la
# parola così com'è, il campo da due lettere la tronca o la rifiuta — e l'errore arriva
# lontano da qui, dove nessuno lo collega al documento che lo ha causato.
#
# Sono **dati**, e i dati stanno in un posto solo. Scritti in forma compatta perché sono
# elenchi da leggere, non codice da seguire.

_PAESI_GREZZI = """
IT:Italia:italia|italiana|italiano|ita; AL:Albania:albania|albanese;
AT:Austria:austria|austriaca|austriaco; BE:Belgio:belgio|belga;
BG:Bulgaria:bulgaria|bulgara|bulgaro; BR:Brasile:brasile|brasiliana|brasiliano;
CN:Cina:cina|cinese; CO:Colombia:colombia|colombiana|colombiano;
HR:Croazia:croazia|croata|croato; CU:Cuba:cuba|cubana|cubano;
CZ:Cechia:cechia|repubblica ceca|ceca|ceco; DK:Danimarca:danimarca|danese;
EC:Ecuador:ecuador|ecuadoriana|ecuadoriano; EG:Egitto:egitto|egiziana|egiziano;
SV:El Salvador:el salvador|salvadoregna|salvadoregno;
PH:Filippine:filippine|filippina|filippino; FI:Finlandia:finlandia|finlandese;
FR:Francia:francia|francese; DE:Germania:germania|tedesca|tedesco;
GH:Ghana:ghana|ghanese; GR:Grecia:grecia|greca|greco; IN:India:india|indiana|indiano;
IE:Irlanda:irlanda|irlandese; MA:Marocco:marocco|marocchina|marocchino;
MD:Moldavia:moldavia|moldova|moldava|moldavo; MK:Macedonia del Nord:macedonia|macedone;
NG:Nigeria:nigeria|nigeriana|nigeriano; NL:Paesi Bassi:paesi bassi|olanda|olandese;
PK:Pakistan:pakistan|pakistana|pakistano; PE:Perù:peru|perù|peruviana|peruviano;
PL:Polonia:polonia|polacca|polacco; PT:Portogallo:portogallo|portoghese;
RO:Romania:romania|rumena|rumeno|romena|romeno; RS:Serbia:serbia|serba|serbo;
SN:Senegal:senegal|senegalese; ES:Spagna:spagna|spagnola|spagnolo;
LK:Sri Lanka:sri lanka|srilankese|cingalese; SE:Svezia:svezia|svedese;
CH:Svizzera:svizzera|svizzero; TN:Tunisia:tunisia|tunisina|tunisino;
TR:Turchia:turchia|turca|turco; UA:Ucraina:ucraina|ucraino;
HU:Ungheria:ungheria|ungherese;
GB:Regno Unito:regno unito|gran bretagna|britannica|britannico|inglese|uk;
US:Stati Uniti:stati uniti|statunitense|americana|americano|usa;
VE:Venezuela:venezuela|venezuelana|venezuelano; BD:Bangladesh:bangladesh|bengalese
"""
"""Codice ISO : nome : le forme in cui la lingua italiana lo declina.

Non è il mondo intero: è un elenco di esempio. Quello che manca si scrive a mano in due
lettere; quello che c'è si riconosce in tutte le sue forme, che è il punto — un documento
non dice mai «TN», dice «di nazionalità tunisina».
"""

_PROVINCE_GREZZE = """
AG:Agrigento; AL:Alessandria; AN:Ancona; AO:Aosta; AR:Arezzo; AP:Ascoli Piceno; AT:Asti;
AV:Avellino; BA:Bari; BT:Barletta-Andria-Trani; BL:Belluno; BN:Benevento; BG:Bergamo;
BI:Biella; BO:Bologna; BZ:Bolzano; BS:Brescia; BR:Brindisi; CA:Cagliari; CL:Caltanissetta;
CB:Campobasso; CE:Caserta; CT:Catania; CZ:Catanzaro; CH:Chieti; CO:Como; CS:Cosenza;
CR:Cremona; KR:Crotone; CN:Cuneo; EN:Enna; FM:Fermo; FE:Ferrara; FI:Firenze; FG:Foggia;
FC:Forlì-Cesena; FR:Frosinone; GE:Genova; GO:Gorizia; GR:Grosseto; IM:Imperia; IS:Isernia;
SP:La Spezia; AQ:L'Aquila; LT:Latina; LE:Lecce; LC:Lecco; LI:Livorno; LO:Lodi; LU:Lucca;
MC:Macerata; MN:Mantova; MS:Massa-Carrara; MT:Matera; ME:Messina; MI:Milano; MO:Modena;
MB:Monza e della Brianza; NA:Napoli; NO:Novara; NU:Nuoro; OR:Oristano; PD:Padova;
PA:Palermo; PR:Parma; PV:Pavia; PG:Perugia; PU:Pesaro e Urbino; PE:Pescara; PC:Piacenza;
PI:Pisa; PT:Pistoia; PN:Pordenone; PZ:Potenza; PO:Prato; RG:Ragusa; RA:Ravenna;
RC:Reggio Calabria; RE:Reggio Emilia; RI:Rieti; RN:Rimini; RM:Roma; RO:Rovigo; SA:Salerno;
SS:Sassari; SV:Savona; SI:Siena; SR:Siracusa; SO:Sondrio; SU:Sud Sardegna; TA:Taranto;
TE:Teramo; TR:Terni; TO:Torino; TP:Trapani; TN:Trento; TV:Treviso; TS:Trieste; UD:Udine;
VA:Varese; VE:Venezia; VB:Verbano-Cusio-Ossola; VC:Vercelli; VR:Verona; VV:Vibo Valentia;
VI:Vicenza; VT:Viterbo
"""
"""Le 107 province e città metropolitane in vigore. Cambiano di rado, e quando cambiano si
tocca questa stringa."""


def _voci(grezzo: str) -> list[list[str]]:
    return [v.strip().split(":") for v in grezzo.replace("\n", " ").split(";") if v.strip()]


PAESI: dict[str, str] = {c: n for c, n, _ in _voci(_PAESI_GREZZI)}
_DA_PAROLA: dict[str, str] = {
    parola: codice
    for codice, _, varianti in _voci(_PAESI_GREZZI)
    for parola in varianti.split("|")
}
PROVINCE: dict[str, str] = dict(_voci(_PROVINCE_GREZZE))  # type: ignore[arg-type]
_DA_NOME: dict[str, str] = {n.lower(): s for s, n in PROVINCE.items()}


def nazionalita(grezzo: str) -> str:
    """«di nazionalità nigeriana» → `NG`. Stringa vuota se non si riconosce.

    Vuota, e non la parola così com'era: un campo da due lettere che ne contiene nove rompe
    da qualche altra parte, e lì nessuno lo collega al documento.

    **Le due lettere non si traducono**: `TN` resta `TN`, anche se non è nell'elenco. La
    funzione è idempotente perché la chiamano sia la lettura sia il salvataggio, e un dato
    già a posto non deve peggiorare.
    """
    testo = (grezzo or "").strip()
    if not testo:
        return ""
    if len(testo) == 2 and testo.isalpha():
        return testo.upper()
    piatto = " ".join(testo.lower().replace("-", " ").split())
    parole = piatto.split()
    # «di nazionalità tunisina», «cittadino marocchino»: la parola che conta è l'ultima.
    for chiave in (piatto, parole[-1] if parole else ""):
        if chiave in _DA_PAROLA:
            return _DA_PAROLA[chiave]
    return ""


def provincia(grezzo: str) -> str:
    """«Bari» → `BA`, e `BA` → `BA`. Stringa vuota se non è una provincia italiana.

    Due lettere si sbagliano: «TO» e «TA» sono una consonante di distanza, e una provincia
    sbagliata non dà nessun errore — dà un indirizzo che il geocodificatore non trova.
    """
    testo = (grezzo or "").strip()
    if not testo:
        return ""
    if testo.upper() in PROVINCE:
        return testo.upper()
    return _DA_NOME.get(testo.lower(), "")


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
