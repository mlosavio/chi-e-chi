"""I tre passaggi, in ordine — e il secondo è quello che l'esempio esiste per mostrare.

    1. RILEVATORE     tutto in locale: trova le entità e ne attribuisce quelle che sa
                      attribuire **da solo** — per aritmetica, non per ipotesi.
    2. MODELLO        sul testo **mascherato**: decide chi è chi. È l'unica cosa che un
                      rilevatore di entità non può fare.
    3. RICOMPOSIZIONE i valori tornano dai segnaposto, **in locale**, e poi si validano.

## Perché il passaggio 2 non è facoltativo

Un rilevatore di entità dà **tipi, non ruoli**. Su un contratto di assunzione trova due
`FULLNAME`, tre `STREET`, due `CF`, cinque `DATE` — e ha ragione su tutti. Ma «qui ci sono
due persone» non è «questa è quella che stai assumendo», e nessuna quantità di
riconoscimento di entità colma quella distanza: il ruolo non sta nel dato, sta **nelle
parole intorno**.

«Egr. Sig.», «con sede legale in», «nato a», «in qualità di legale rappresentante», la firma
in calce. Quelle parole non sono dati personali, quindi **non vengono mascherate**, quindi
restano leggibili nel testo che esce. Il modello legge

    Egr. Sig. [FULLNAME_1], nato a [CITY_2] il [DATE_1], residente in [STREET_3]

e capisce dal contesto che `[FULLNAME_1]` è il lavoratore e `[STREET_3]` è la sua residenza —
senza sapere che si chiama Karim Ben Salah e senza che nessuno glielo dica.

## Perché il passaggio 1 viene prima

Perché quando basta, il passaggio 2 non serve. Un codice fiscale con il checksum giusto
**contiene** la data di nascita e, con `coerente_con`, dice quale dei nomi trovati è il suo.
Non è un'euristica: è aritmetica, ed è più affidabile di qualunque lettura. Il modello si
chiama per quello che resta.

## La distinzione che regge tutto

**«Certo per costruzione» non è «ce n'era uno solo».** Il codice fiscale validato è
aritmetica. «C'era una sola email nel documento» è un'ipotesi — e su una carta intestata è
pure sbagliata, perché quell'unica email è la PEC dell'azienda. I primi non si toccano; i
secondi si sottopongono al modello, che ha il contesto davanti.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import dominio, pii, schema
from . import modello as mod


@dataclass
class Passo:
    """Una riga della traccia. L'esempio è fatto per essere **guardato mentre lavora**."""

    nome: str
    dettaglio: str
    durata_ms: int = 0


@dataclass
class Esito:
    campi: dict[str, str] = field(default_factory=dict)
    candidati: dict[str, list[str]] = field(default_factory=dict)
    """Quando di un tipo ce n'è più d'uno e nessuno sa quale sia, **non si indovina**: si
    propongono. Un campo riempito indovinando è peggio di un campo vuoto, perché nessuno lo
    rilegge."""
    non_trovati: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)
    certi: set[str] = field(default_factory=set)
    parti: dict[str, str] = field(default_factory=dict)
    """Chi è chi, come lo ha stabilito il modello. È il risultato che dà il nome al progetto."""
    fonte: str = "locale"
    traccia: list[Passo] = field(default_factory=list)

    def come_dizionario(self) -> dict:
        return {
            "campi": self.campi,
            "candidati": self.candidati,
            "non_trovati": self.non_trovati,
            "avvisi": self.avvisi,
            "parti": self.parti,
            "fonte": self.fonte,
        }


ISTRUZIONE = """\
Sei un assistente che legge documenti amministrativi italiani.

Il testo che ricevi è stato ANONIMIZZATO: ogni dato personale è stato sostituito da un
segnaposto della forma [TIPO_numero]. Non sai cosa nascondono, e non devi indovinarlo.
Le parole intorno NON sono mascherate: sono quelle che dicono a chi appartiene ogni
segnaposto, ed è tutto quello che ti serve.

PRIMA DI ESTRARRE, STABILISCI IL VERSO DEL DOCUMENTO.
Ogni atto ha due parti: chi lo emette (il dante causa: l'azienda che assume, il locatore) e
chi lo riceve (l'avente causa: la persona assunta, il conduttore). I dati che servono sono
di norma quelli dell'avente causa. Le formule che lo dicono sono nel testo: «Egr. Sig.»,
«Spett.le», «in qualità di legale rappresentante», «con sede legale in», la firma in calce.

Rispondi SOLO con un oggetto JSON, senza testo prima o dopo:
  "parti": {
      "soggetto": il segnaposto della persona di cui parla il documento,
      "controparte": il segnaposto di chi lo emette,
      "verso": "chiaro" se le distingui con certezza, "incerto" altrimenti,
      "spiegazione": una riga sul perché, citando le parole del testo che te lo dicono
  }
  "estranei": i segnaposto che appartengono alla controparte e non al soggetto
  "campi": i campi richiesti, con il SEGNAPOSTO come valore quando il dato è mascherato
  "non_trovati": i campi che nel documento non ci sono, o che sono della controparte

REGOLE INDEROGABILI
- Riporta i segnaposto tali e quali. Non inventarne di nuovi.
- Un dato della controparte NON è un dato del soggetto: la sede legale dell'azienda non è la
  residenza del dipendente, il centralino non è il suo telefono, la PEC aziendale non è la
  sua email. Vanno in "estranei", e il campo va in "non_trovati".
- Se "verso" è "incerto", lascia "campi" vuoto. Mescolare le due parti è peggio che non
  compilare: un campo vuoto si vede, un campo sbagliato no.
"""


def estrai(testo: str, *, cliente: mod.Cliente | None = None, servizio=pii) -> Esito:
    """Il giro completo. `servizio` e `cliente` sono iniettabili per i test."""
    import time

    esito = Esito()

    avvio = time.monotonic()
    analisi = servizio.analizza(testo)
    tipi = sorted({e.etichetta for e in analisi.entita})
    esito.traccia.append(Passo(
        "1 · rilevatore locale",
        f"{len(analisi.entita)} entità, {len(tipi)} tipi ({', '.join(tipi)}); "
        f"{len(analisi.mappa)} segnaposto. Niente è uscito da questa macchina.",
        int((time.monotonic() - avvio) * 1000),
    ))

    _quello_che_si_sa_da_soli(esito, analisi)
    esito.traccia.append(Passo(
        "2 · attribuzione deterministica",
        _riassunto_deterministico(esito),
    ))

    da_sciogliere = _cosa_resta(esito)
    if not da_sciogliere:
        esito.traccia.append(Passo("3 · modello", "non serve: non è rimasto niente di ambiguo"))
        return esito

    avvio = time.monotonic()
    _chi_e_chi(esito, analisi, da_sciogliere, cliente or mod.cliente())
    esito.traccia.append(Passo(
        "3 · modello sul testo mascherato",
        _riassunto_modello(esito),
        int((time.monotonic() - avvio) * 1000),
    ))
    return esito


# --------------------------------------------------------------------------
# Passaggio 1 · quello che il codice sa da solo


def _quello_che_si_sa_da_soli(esito: Esito, analisi: pii.Analisi) -> None:
    """Il codice fiscale è la chiave: **contiene** gli altri dati e li scioglie.

    Fra tre nomi in un contratto, quello giusto non si indovina — si calcola.
    """
    fiscali = [c.replace(" ", "").upper() for c in analisi.per_etichetta("CF")]
    validi = [c for c in fiscali if dominio.valido(c)]
    if len(validi) == 1:
        esito.campi["codice_fiscale"] = validi[0]
        esito.certi.add("codice_fiscale")
    elif len(validi) > 1:
        esito.candidati["codice_fiscale"] = validi
    elif fiscali:
        esito.avvisi.append(
            f"Il codice fiscale letto («{fiscali[0]}») non supera il controllo del carattere "
            "finale: non è stato usato."
        )

    fiscale = esito.campi.get("codice_fiscale", "")
    anagrafe = dominio.data_e_sesso(fiscale) if fiscale else None

    nomi = analisi.per_etichetta("FULLNAME")
    scelto = dominio.nome_dal_codice(nomi, fiscale) if fiscale else None
    if scelto:
        esito.campi["cognome"], esito.campi["nome"] = scelto
        # Scelti dal checksum: è aritmetica, non un'ipotesi.
        esito.certi.update({"cognome", "nome"})
    elif nomi:
        cognomi = [dominio.dividi_nome(n)[0] for n in nomi]
        propri = [p for p in (dominio.dividi_nome(n)[1] for n in nomi) if p]
        if cognomi:
            esito.candidati["cognome"] = list(dict.fromkeys(cognomi))
        if propri:
            esito.candidati["nome"] = list(dict.fromkeys(propri))

    if anagrafe:
        esito.campi["data_nascita"] = anagrafe[0].isoformat()
        esito.certi.add("data_nascita")
    else:
        date_trovate = [d for d in (dominio.leggi_data(v)
                                    for v in analisi.per_etichetta("DATE")) if d]
        if date_trovate:
            esito.candidati["data_nascita"] = list(dict.fromkeys(date_trovate))

    # Il resto: uno solo lo si **propone** comunque, perché «ce n'era uno solo» è
    # un'ipotesi — e su una carta intestata è quasi sempre sbagliata.
    for etichetta, campo in (
        ("EMAIL", "email"), ("TELEPHONENUM", "telefono"), ("ZIPCODE", "cap"),
        ("CITY", "citta"), ("PROVINCE", "provincia"), ("STREET", "via"), ("ORG", "datore"),
    ):
        valori = analisi.per_etichetta(etichetta)
        if valori:
            esito.candidati[campo] = valori

    esito.non_trovati = [
        c for c in sorted(schema.NOMI)
        if c not in esito.campi and c not in esito.candidati
    ]


def _cosa_resta(esito: Esito) -> list[str]:
    """Quello che il modello deve sciogliere: i menù, i buchi, e i campi riempiti per ipotesi.

    I campi **certi per costruzione** restano fuori: nessuna rilettura migliora un checksum.
    """
    incerti = set(esito.campi) - esito.certi
    return sorted(set(esito.candidati) | set(esito.non_trovati) | incerti)


# --------------------------------------------------------------------------
# Passaggio 2 · chi è chi


def _chi_e_chi(esito, analisi, da_sciogliere, cliente) -> None:
    anonimo = (analisi.anonimizzato or "").strip()
    if not anonimo:
        return

    # Il nome intero come campo a sé: il modello **non può** dividere `[FULLNAME_1]` in
    # cognome e nome, perché non lo vede. Sa dire quale dei nomi è il lavoratore; a
    # dividerlo si pensa dopo, con il nome vero davanti.
    ponte = bool({"cognome", "nome"} & set(da_sciogliere))
    if ponte:
        da_sciogliere = [c for c in da_sciogliere if c not in ("cognome", "nome")]
        da_sciogliere.append("nome_completo")

    domanda = mod.Domanda(
        istruzione=ISTRUZIONE,
        fatti=(
            "Il documento è un contratto o una lettera di assunzione.\n\n"
            f"Campi da attribuire: {', '.join(da_sciogliere)}.\n"
            f"{schema.elenco()}\n"
            + ("- nome_completo: il segnaposto del nome del LAVORATORE — non quello di chi "
               "firma per l'azienda\n" if ponte else "")
            + f"\n--- TESTO ---\n{anonimo}\n--- FINE ---"
        ),
    )
    try:
        risposta = cliente.genera(domanda)
    except mod.ModelloNonDisponibile as errore:
        esito.avvisi.append(
            f"Il modello non è disponibile ({errore}): restano i campi del rilevatore, e "
            "quelli ambigui restano da scegliere a mano."
        )
        return

    dati = _json_di(risposta)
    parti = dati.get("parti") if isinstance(dati.get("parti"), dict) else {}
    esito.parti = {
        chiave: pii.ricomponi(str(parti.get(chiave, "")), analisi.mappa)
        for chiave in ("soggetto", "controparte", "verso", "spiegazione")
    }

    if str(parti.get("verso", "")).lower().startswith("incert"):
        # **Meglio non far nulla.** Una scheda mescolata è peggio di una vuota: un campo
        # vuoto si vede e si compila, un campo pieno del dato sbagliato attraversa la
        # revisione e finisce in una busta paga.
        esito.campi = {c: v for c, v in esito.campi.items() if c in esito.certi}
        esito.candidati = {}
        esito.avvisi.append(
            "Il verso del documento non è chiaro: non si attribuisce niente che non sia "
            "certo per costruzione."
        )
        return

    _scarta_gli_estranei(esito, dati, analisi)
    _applica(esito, dati, analisi, ponte)
    esito.fonte = "anonimizzato"


def _scarta_gli_estranei(esito: Esito, dati: dict, analisi: pii.Analisi) -> None:
    """Toglie dai menù i valori che sono **della controparte**.

    È la potatura che fa sparire dal campo «nome» i due amministratori che firmano, e dal
    campo «email» la PEC aziendale. Sono dati veri, e sono di qualcun altro.
    """
    grezzi = dati.get("estranei")
    if not isinstance(grezzi, list):
        return
    estranei = {
        _piatto(pii.ricomponi(str(v), analisi.mappa)) for v in grezzi
    } - {""}
    if not estranei:
        return

    def suo(valore: str) -> bool:
        p = _piatto(valore)
        return bool(p) and any(p == e or (len(p) > 2 and p in e) for e in estranei)

    for chiave in list(esito.campi):
        if chiave not in esito.certi and suo(esito.campi[chiave]):
            esito.campi.pop(chiave)
            esito.non_trovati.append(chiave)
    for chiave in list(esito.candidati):
        esito.candidati[chiave] = [v for v in esito.candidati[chiave] if not suo(v)]


def _applica(esito: Esito, dati: dict, analisi: pii.Analisi, ponte: bool) -> None:
    """Passaggio 3: i segnaposto tornano valori, **qui**, e poi si controllano."""
    campi = dati.get("campi") if isinstance(dati.get("campi"), dict) else {}
    if ponte and "nome_completo" not in campi:
        trovata = re.search(r'"nome_completo"\s*:\s*"([^"]+)"', str(dati))
        if trovata:
            campi = {**campi, "nome_completo": trovata.group(1)}

    for chiave, valore in campi.items():
        if chiave in esito.certi or not valore:
            continue
        if chiave != "nome_completo" and chiave not in schema.NOMI:
            continue
        # **Una volta sola, prima di tutto il resto**: se il modello ha perso le parentesi
        # quadre gliele si rimette, o il controllo dei tipi non le trova e la ricomposizione
        # non scatta.
        grezzo = pii.normalizza(str(valore), analisi.mappa)
        # **Il tipo lo ha già deciso il rilevatore.** Se arriva `[ORG_1]` per «via», si
        # scarta: nel campo comparirebbe la ragione sociale, che sembra un dato.
        if not schema.tipo_compatibile(chiave, str(grezzo), analisi.etichetta_di):
            esito.avvisi.append(
                f"Per «{chiave}» il modello ha indicato {grezzo}, che è di un altro tipo: "
                "scartato."
            )
            continue
        vero = pii.ricomponi(str(grezzo), analisi.mappa).strip()
        # Un segnaposto che non esiste resta tale e quale: non è un dato.
        if not vero or (vero.startswith("[") and vero.endswith("]")):
            continue

        if chiave == "nome_completo":
            _il_nome_e_il_suo_codice(esito, vero)
            continue

        if chiave in ("data_nascita", "data_assunzione"):
            vero = dominio.leggi_data(vero) or vero
        esito.campi[chiave] = vero
        esito.candidati.pop(chiave, None)

    # Quello che il modello dichiara assente si **svuota**, se era solo un'ipotesi locale.
    for grezza in dati.get("non_trovati") or []:
        chiave = str(grezza).split(":", 1)[0].strip()
        if chiave in esito.certi or chiave not in schema.NOMI:
            continue
        esito.campi.pop(chiave, None)
        esito.candidati.pop(chiave, None)
        esito.non_trovati.append(chiave)

    _controlla(esito)
    _pulisci(esito)


def _il_nome_e_il_suo_codice(esito: Esito, completo: str) -> None:
    """**Il modello dice chi, l'aritmetica dice come si scrive.**

    È il passaggio in cui i due mondi si incontrano, e ognuno fa quello che sa fare.

    Il modello ha appena detto che il lavoratore è «Ben Salah Karim». Dividere quella
    stringa in cognome e nome è un indovinello — in italiano «Ben Salah Karim» e «Karim Ben
    Salah» si scrivono entrambe, e prendere l'ultima parola come cognome sbaglia. Ma se in
    documento c'è **un codice fiscale coerente con quel nome**, l'ordine non si indovina più:
    si calcola, perché le prime sei lettere del codice sono consonanti di cognome e nome in
    quest'ordine.

    E il codice fiscale giusto è quello del lavoratore anche quando ce n'erano due — l'altro
    è del legale rappresentante che firma. Un rilevatore non poteva sceglierlo: sono due
    codici entrambi validi. Insieme, il modello e il checksum sì.

    Da qui discendono anche la data di nascita e il sesso, che nel codice ci sono già.
    """
    fiscali = esito.candidati.get("codice_fiscale") or []
    if esito.campi.get("codice_fiscale"):
        fiscali = [esito.campi["codice_fiscale"], *fiscali]

    for fiscale in fiscali:
        scelto = dominio.nome_dal_codice([completo], fiscale)
        if not scelto:
            continue
        esito.campi["cognome"], esito.campi["nome"] = scelto
        esito.campi["codice_fiscale"] = fiscale
        esito.certi.update({"cognome", "nome", "codice_fiscale"})
        esito.candidati.pop("codice_fiscale", None)
        anagrafe = dominio.data_e_sesso(fiscale)
        if anagrafe:
            esito.campi["data_nascita"] = anagrafe[0].isoformat()
            esito.certi.add("data_nascita")
            esito.candidati.pop("data_nascita", None)
        esito.avvisi.append(
            f"Il codice fiscale {fiscale} è coerente con «{completo}»: cognome, nome e data "
            "di nascita non sono stati letti, sono stati calcolati."
        )
        break
    else:
        # Nessun codice coerente: si divide come si può, e **lo si dichiara**.
        cognome, nome = dominio.dividi_nome(completo)
        if cognome:
            esito.campi["cognome"] = cognome
        if nome:
            esito.campi["nome"] = nome
        esito.avvisi.append(
            f"«{completo}»: senza un codice fiscale coerente non si sa quale sia il cognome. "
            "Controlla che non siano invertiti."
        )
    for chiave in ("cognome", "nome"):
        esito.candidati.pop(chiave, None)


def _controlla(esito: Esito) -> None:
    """Gli stessi controlli che si farebbero su un dato scritto a mano.

    Il modello propone, il codice esatto decide.
    """
    fiscale = esito.campi.get("codice_fiscale")
    if fiscale and not dominio.valido(fiscale):
        del esito.campi["codice_fiscale"]
        esito.avvisi.append(
            f"«{fiscale}» non supera il controllo del carattere finale: scartato."
        )
    cap = esito.campi.get("cap")
    if cap and not re.fullmatch(r"\d{5}", cap.strip()):
        del esito.campi["cap"]
    ore = esito.campi.get("monte_ore_settimanale")
    if ore:
        numero = re.search(r"\d+(?:[.,]\d+)?", str(ore))
        if numero:
            esito.campi["monte_ore_settimanale"] = numero.group(0).replace(",", ".")
        else:
            del esito.campi["monte_ore_settimanale"]


def _pulisci(esito: Esito) -> None:
    """Niente menù vuoti, niente doppioni, niente menù con una voce sola."""
    for chiave in list(esito.candidati):
        valori = [v for v in dict.fromkeys(esito.candidati[chiave]) if str(v).strip()]
        if len(valori) > 1:
            esito.candidati[chiave] = valori
            continue
        esito.candidati.pop(chiave)
        if len(valori) == 1 and chiave not in esito.campi:
            esito.campi[chiave] = valori[0]
    esito.non_trovati = sorted({
        c for c in esito.non_trovati
        if c not in esito.campi and c not in esito.candidati
    })
    esito.avvisi = list(dict.fromkeys(esito.avvisi))


# --------------------------------------------------------------------------


def _json_di(risposta: str) -> dict:
    grezzo = re.sub(r"^```(?:json)?\s*|\s*```$", "", (risposta or "").strip()).strip()
    try:
        dati = json.loads(grezzo)
    except json.JSONDecodeError:
        return {}
    return dati if isinstance(dati, dict) else {}


def _piatto(valore: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(valore or "").lower())


def _riassunto_deterministico(esito: Esito) -> str:
    if esito.certi:
        return (
            f"risolti dal checksum del codice fiscale: {', '.join(sorted(esito.certi))}. "
            f"Restano ambigui: {', '.join(sorted(esito.candidati)) or '—'}."
        )
    return (
        "nessun codice fiscale valido: non c'è niente da calcolare. "
        f"Ambigui: {', '.join(sorted(esito.candidati)) or '—'}."
    )


def _riassunto_modello(esito: Esito) -> str:
    if not esito.parti:
        return "non ha risposto, o non era disponibile"
    return (
        f"soggetto: {esito.parti.get('soggetto') or '—'} · "
        f"controparte: {esito.parti.get('controparte') or '—'} · "
        f"verso: {esito.parti.get('verso') or '—'}"
    )
