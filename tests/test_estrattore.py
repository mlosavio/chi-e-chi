"""Le prove girano **senza rete**: né rilevatore né modello.

Non è una comodità: un test che dipende da un container acceso diventa rosso quando qualcuno
spegne una macchina, e un test che diventa rosso per ragioni sue smette di essere letto.
Qui il rilevatore e il modello sono due oggetti che rispondono quello che dice la prova — ed
è anche il modo di dire **quale caso** si sta esercitando.
"""

from __future__ import annotations

import json

from chi_e_chi import dominio, estrattore, modello, pii, schema

# Codici fiscali veri nel senso che contano: il carattere di controllo torna.
CF_LAVORATORE = "BNSKRM94C12Z352D"   # Ben Salah Karim, 12 marzo 1994
CF_TITOLARE = "SRNDNC82L03F839Y"     # Sarnataro Domenico, 3 luglio 1982


class Rilevatore:
    """rizzo-pii, con una risposta decisa dalla prova."""

    def __init__(self, entita, anonimizzato="", mappa=None):
        self.analisi = pii.Analisi(
            entita=[pii.Entita(e, v) for e, v in entita],
            anonimizzato=anonimizzato,
            mappa=mappa or {},
        )

    def analizza(self, testo):
        return self.analisi

    ricomponi = staticmethod(pii.ricomponi)


def risposta(campi=None, parti=None, estranei=(), non_trovati=()):
    return json.dumps({
        "parti": parti or {"soggetto": "[FULLNAME_1]", "controparte": "[ORG_1]",
                           "verso": "chiaro", "spiegazione": "prova"},
        "estranei": list(estranei),
        "campi": campi or {},
        "non_trovati": list(non_trovati),
    })


# --------------------------------------------------------------------------
# Il dominio: quello che si decide senza chiedere a nessuno


def test_il_checksum_non_e_un_opinione():
    assert dominio.valido(CF_LAVORATORE)
    assert not dominio.valido("BNSKRM94C12Z352A")


def test_dal_codice_fiscale_si_ricava_la_data_di_nascita():
    """Non è una delle date del documento: è **quella giusta**, calcolata."""
    nato, sesso = dominio.data_e_sesso(CF_LAVORATORE)
    assert nato.isoformat() == "1994-03-12"
    assert sesso == "M"


def test_il_codice_fiscale_dice_quale_dei_nomi_e_la_persona():
    """Fra due nomi in un contratto non si indovina: si calcola. Le prime sei lettere del
    codice sono consonanti di cognome e nome, in quest'ordine."""
    nomi = ["Domenico Sarnataro", "Ben Salah Karim"]
    assert dominio.nome_dal_codice(nomi, CF_LAVORATORE) == ("Ben Salah", "Karim")
    assert dominio.nome_dal_codice(nomi, CF_TITOLARE) == ("Sarnataro", "Domenico")


def test_le_date_italiane_si_scrivono_per_esteso():
    assert dominio.leggi_data("12 agosto 1994") == "1994-08-12"
    assert dominio.leggi_data("1° settembre 2026") == "2026-09-01"
    assert dominio.leggi_data("01/09/2026") == "2026-09-01"
    assert dominio.leggi_data("il giorno dopo") == ""


# --------------------------------------------------------------------------
# Il giro completo


def test_il_modello_vede_i_segnaposto_e_non_i_nomi():
    """**La prova che vale l'intero progetto.** Nel testo che esce non c'è un solo dato
    personale, e il modello riesce comunque a dire chi è chi."""
    finto = modello.Finto(risposta({"nome_completo": "[FULLNAME_1]"}))
    rilevatore = Rilevatore(
        [("FULLNAME", "Ben Salah Karim"), ("FULLNAME", "Domenico Sarnataro"),
         ("CF", CF_LAVORATORE), ("CF", CF_TITOLARE)],
        anonimizzato="Egr. Sig. [FULLNAME_1] — firma il legale rappresentante [FULLNAME_2]",
        mappa={"[FULLNAME_1]": "Ben Salah Karim", "[FULLNAME_2]": "Domenico Sarnataro",
               "[CF_1]": CF_LAVORATORE, "[CF_2]": CF_TITOLARE},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    visto = finto.domande[0].fatti
    assert "Ben Salah" not in visto and "Sarnataro" not in visto
    assert "[FULLNAME_1]" in visto
    # E le parole che dicono il ruolo ci sono ancora: non sono dati personali.
    assert "Egr. Sig." in visto and "legale rappresentante" in visto
    assert esito.campi["cognome"] == "Ben Salah"


def test_il_modello_dice_chi_e_l_aritmetica_dice_come_si_scrive():
    """Due codici fiscali entrambi validi: il rilevatore non poteva sceglierne uno — uno è
    del lavoratore, l'altro di chi firma. Il modello dice quale nome conta, il checksum dice
    quale codice è il suo, e da lì discende la data di nascita."""
    finto = modello.Finto(risposta({"nome_completo": "[FULLNAME_1]"}))
    rilevatore = Rilevatore(
        [("FULLNAME", "Ben Salah Karim"), ("FULLNAME", "Domenico Sarnataro"),
         ("CF", CF_LAVORATORE), ("CF", CF_TITOLARE)],
        anonimizzato="Egr. Sig. [FULLNAME_1]",
        mappa={"[FULLNAME_1]": "Ben Salah Karim"},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    assert esito.campi["codice_fiscale"] == CF_LAVORATORE
    assert esito.campi["data_nascita"] == "1994-03-12"
    assert {"cognome", "nome", "codice_fiscale", "data_nascita"} <= esito.certi
    assert any("calcolat" in a for a in esito.avvisi)


def test_i_dati_della_controparte_non_sono_quelli_del_soggetto():
    """Il rilevatore trova una sola email e la propone; il modello, che ha davanti la carta
    intestata, sa che è la PEC dell'azienda."""
    finto = modello.Finto(risposta(
        {}, estranei=["[EMAIL_1]"], non_trovati=["email"],
    ))
    rilevatore = Rilevatore(
        [("EMAIL", "ristorazionemediterranea@pec.it")],
        anonimizzato="PEC: [EMAIL_1]",
        mappa={"[EMAIL_1]": "ristorazionemediterranea@pec.it"},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    assert "email" not in esito.campi
    assert "email" in esito.non_trovati


def test_se_il_verso_non_e_chiaro_non_si_attribuisce_niente():
    """Una scheda mescolata è **peggio** di una vuota: un campo vuoto si vede e si compila,
    un campo pieno del dato sbagliato attraversa la revisione."""
    finto = modello.Finto(risposta(
        {"citta": "[CITY_1]"},
        parti={"soggetto": "?", "controparte": "?", "verso": "incerto"},
    ))
    rilevatore = Rilevatore(
        [("CITY", "Bari"), ("CITY", "Napoli"), ("CF", CF_LAVORATORE)],
        anonimizzato="[CITY_1] e [CITY_2]",
        mappa={"[CITY_1]": "Bari", "[CITY_2]": "Napoli"},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    # Resta solo l'aritmetica: il codice fiscale col checksum giusto, e la data che ne
    # discende. Quelle non dipendono dal verso dell'atto.
    assert esito.campi == {
        "codice_fiscale": CF_LAVORATORE, "data_nascita": "1994-03-12",
    }
    assert esito.candidati == {}
    assert any("verso" in a for a in esito.avvisi)


def test_il_tipo_di_un_dato_lo_decide_il_rilevatore():
    """Alla domanda «quale segnaposto è la via» può arrivare `[ORG_1]`, e nel campo
    comparirebbe una ragione sociale: il nome giusto nel posto sbagliato, che sembra un dato
    e non lo rilegge nessuno. Il rilevatore aveva già deciso che è un'organizzazione."""
    finto = modello.Finto(risposta({"via": "[ORG_1]"}))
    rilevatore = Rilevatore(
        [("ORG", "Ristorazione Mediterranea S.r.l."),
         ("STREET", "Via Petroni"), ("STREET", "Via Matarrese")],
        anonimizzato="[ORG_1] in [STREET_1], oppure [STREET_2]",
        mappa={"[ORG_1]": "Ristorazione Mediterranea S.r.l.",
               "[STREET_1]": "Via Petroni", "[STREET_2]": "Via Matarrese"},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)
    assert "Ristorazione" not in esito.campi.get("via", "")
    assert any("altro tipo" in a for a in esito.avvisi)
    # Le due vie restano un menù da cui scegliere: non si è indovinato al posto di nessuno.
    assert len(esito.candidati["via"]) == 2


def test_via_e_numero_civico_sono_due_entita_e_si_uniscono():
    """Il caso opposto, e va **ammesso**: una via e il suo numero sono due entità distinte
    per il rilevatore, e unirle è la cosa corretta. Controllare solo il primo segnaposto
    lascerebbe passare anche `[STREET_1] [ORG_1]`."""
    assert schema.tipo_compatibile("via", "[STREET_2] [BUILDINGNUM_2]")
    assert not schema.tipo_compatibile("via", "[STREET_2] [ORG_1]")
    assert schema.tipo_compatibile("mansione", "pizzaiolo"), "in chiaro: nessun tipo da dire"


def test_senza_modello_non_si_perde_quello_che_il_rilevatore_aveva_trovato():
    """Un raffinamento che fallisce lascia in piedi ciò che raffinava. Senza chiave il
    programma funziona: dà meno, e lo dichiara."""
    rilevatore = Rilevatore(
        [("CF", CF_LAVORATORE), ("FULLNAME", "Ben Salah Karim")],
        anonimizzato="[FULLNAME_1]",
        mappa={"[FULLNAME_1]": "Ben Salah Karim"},
    )
    esito = estrattore.estrai("x", cliente=modello.Spento(), servizio=rilevatore)

    assert esito.campi["codice_fiscale"] == CF_LAVORATORE
    assert esito.campi["data_nascita"] == "1994-03-12"
    assert esito.fonte == "locale"
    assert any("non è disponibile" in a for a in esito.avvisi)


def test_senza_testo_mascherato_non_si_manda_niente_a_nessuno():
    """Se il rilevatore non ha prodotto una maschera — servizio a metà, documento senza
    testo — **non si chiama il modello**: non ci sarebbe niente da mandargli che non sia il
    documento in chiaro, ed è precisamente la cosa che questo progetto evita."""
    finto = modello.Finto(risposta({}))
    rilevatore = Rilevatore([("CF", CF_LAVORATORE)])   # nessun `anonimizzato`
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    assert finto.domande == [], "senza maschera non esce niente"
    assert esito.campi["codice_fiscale"] == CF_LAVORATORE
    assert esito.fonte == "locale"


def test_la_traccia_racconta_i_tre_passaggi():
    """L'esempio è fatto per essere guardato mentre lavora: i passaggi si vedono, con i
    tempi. Senza, resta una scatola che sputa un JSON e non insegna niente."""
    finto = modello.Finto(risposta({"citta": "[CITY_1]"}))
    rilevatore = Rilevatore(
        [("CITY", "Bari"), ("CITY", "Napoli")],
        anonimizzato="[CITY_1] e [CITY_2]",
        mappa={"[CITY_1]": "Bari", "[CITY_2]": "Napoli"},
    )
    esito = estrattore.estrai("x", cliente=finto, servizio=rilevatore)

    nomi = [p.nome for p in esito.traccia]
    assert any("rilevatore" in n for n in nomi)
    assert any("determinist" in n for n in nomi)
    assert any("modello" in n for n in nomi)
    assert esito.campi["citta"] == "Bari"
