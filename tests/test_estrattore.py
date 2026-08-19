"""Il giro completo, **senza rete**: né anonimizzatore né modello.

Non è una comodità: un test che dipende da un container acceso diventa rosso quando qualcuno
spegne una macchina, e un test che diventa rosso per ragioni sue smette di essere letto. Qui
i due servizi sono oggetti che rispondono quello che dice la prova — ed è anche il modo di
dire **quale caso** si sta esercitando.

Quattro cose da provare, e sono le quattro promesse dell'esempio:

* **non esce niente** — al modello arriva il testo mascherato, e nella scheda tornano i
  valori veri dalla mappa, che qui non è mai uscita;
* **i ruoli contano** — la sede legale dell'azienda non è la residenza del dipendente, e in
  un contratto di locazione il locale non è nessuna delle due parti;
* **il dominio decide** — il modello propone, il codice fiscale e le province decidono;
* **si degrada** — senza modello resta una scheda vuota che dice perché, non un'eccezione.
"""

from __future__ import annotations

import json

import pytest

from chi_e_chi import dominio, estrattore, lettura, modello, pii, scheda

# --------------------------------------------------------------------------
# I due servizi, finti


class Anonimizzatore:
    """rizzo-pii, con il mascherato e la mappa decisi dal test."""

    def __init__(self, anonimizzato: str = "Egr. Sig. [FULLNAME_1], …", mappa=None):
        self.anonimizzato = anonimizzato
        self.mappa = mappa or {}
        self.visti: list[str] = []

    def analizza(self, testo: str) -> pii.Analisi:
        self.visti.append(testo)
        entita = [
            pii.Entita(etichetta=s[1:-1].rsplit("_", 1)[0], valore=v)
            for s, v in self.mappa.items()
        ]
        return pii.Analisi(entita=entita, anonimizzato=self.anonimizzato, mappa=self.mappa)


class Modello:
    """Risponde quello che gli si dice, e **registra la domanda**: metà di quello che c'è da
    provare è cosa gli è arrivato."""

    def __init__(self, risposta):
        self.risposta = risposta if isinstance(risposta, str) else json.dumps(risposta)
        self.domande: list[modello.Domanda] = []

    def genera(self, domanda: modello.Domanda) -> str:
        self.domande.append(domanda)
        return self.risposta


# --------------------------------------------------------------------------
# Gli attrezzi


def _lettura(entita=None, relazioni=None, **testa) -> dict:
    return {
        "documento": {"natura": "contratto_lavoro", "verso": "chiaro",
                      "spiegazione": "«Egr. Sig.» in apertura", **testa},
        "entita": entita or [],
        "relazioni": relazioni or [],
    }


def _persona(ruolo="lavoratore", **attributi) -> dict:
    return {"tipo": "persona", "ruolo": ruolo, "attributi": attributi}


def _org(ruolo="datore", **attributi) -> dict:
    return {"tipo": "organizzazione", "ruolo": ruolo, "attributi": attributi}


def _luogo(ruolo="immobile", **attributi) -> dict:
    return {"tipo": "luogo", "ruolo": ruolo, "attributi": attributi}


def _estrai(risposta, tipo="persona", servizio=None):
    return estrattore.estrai(
        "testo del documento", tipo,
        cliente=Modello(risposta), servizio=servizio or Anonimizzatore(),
    )


# --------------------------------------------------------------------------
# 1 · Non esce niente


def test_al_modello_arriva_il_mascherato_e_i_valori_tornano_qui():
    """**Il test che vale l'intero esempio.**

    Il modello vede `[FULLNAME_1]`, risponde `[FULLNAME_1]`, e il nome torna in locale dalla
    mappa. Senza la seconda metà, l'anonimizzazione sarebbe solo una perdita di dati.
    """
    servizio = Anonimizzatore(
        "Egr. Sig. [FULLNAME_1], [CF_1], residente in [STREET_1] [BUILDINGNUM_1].",
        {"[FULLNAME_1]": "Karim Ben Salah", "[CF_1]": "BNSKRM90A01Z352P",
         "[STREET_1]": "Via Bologna", "[BUILDINGNUM_1]": "7"},
    )
    cliente = Modello(_lettura([_persona(
        nome_completo="[FULLNAME_1]", codice_fiscale="[CF_1]",
        via="[STREET_1]", civico="[BUILDINGNUM_1]",
    )]))
    esito = estrattore.estrai("testo", cliente=cliente, servizio=servizio)

    arrivato = cliente.domande[0].fatti
    assert "Ben Salah" not in arrivato and "Via Bologna" not in arrivato
    assert "[FULLNAME_1]" in arrivato
    assert esito.campi["via"] == "Via Bologna 7"
    assert esito.campi["cognome"] == "Ben Salah"


def test_i_valori_tornano_anche_dove_nessuno_li_aspettava():
    """La ricomposizione cammina **tutta** la lettura — attributi, relazioni, spiegazione.
    Una funzione che ne conoscesse la forma si romperebbe alla prima chiave aggiunta, e si
    romperebbe in silenzio: resterebbe a video il nome di un segnaposto."""
    servizio = Anonimizzatore("…", {"[ORG_1]": "La Bruschetta Srl"})
    esito = _estrai(
        _lettura([_persona(nome_completo="Ada Rossi"),
                  _org("datore", denominazione="[ORG_1]")],
                 spiegazione="la lettera è intestata a [ORG_1]"),
        servizio=servizio,
    )
    assert esito.campi["datore"] == "La Bruschetta Srl"
    assert "La Bruschetta Srl" in esito.parti["spiegazione"]


def test_un_segnaposto_inventato_dal_modello_si_scarta():
    """Se il modello risponde con un segnaposto che nella mappa non c'è, la ricomposizione
    non scatta e resterebbe a video `[EMAIL_9]`. Non è un dato."""
    esito = _estrai(_lettura([_persona(nome_completo="Ada Rossi", email="[EMAIL_9]")]))
    assert "email" not in esito.campi
    assert "email" in esito.non_trovati


def test_il_testo_uscito_si_conserva_per_poterlo_guardare():
    """La promessa «non è uscito niente» va **mostrata**. L'esito porta con sé esattamente
    ciò che è stato spedito, e chiedere una seconda scansione per stamparlo costerebbe altri
    venticinque secondi per una cosa che si aveva già in mano."""
    esito = _estrai(_lettura([_persona(nome_completo="Ada Rossi")]))
    assert esito.anonimizzato.startswith("Egr. Sig.")


# --------------------------------------------------------------------------
# 2 · I ruoli contano


def test_i_dati_di_chi_manda_il_documento_non_sono_quelli_di_chi_lo_riceve():
    """**Il caso vero.** Una lettera di assunzione su carta intestata contiene due indirizzi,
    due telefoni e due email, e quelli in alto — più visibili, più completi — sono
    dell'azienda. Un campo sbagliato non si vede: la scheda sembra piena."""
    esito = _estrai(_lettura([
        _org("datore", denominazione="La Bruschetta Srl", via="Corso Italia", civico="1",
             citta="Milano", cap="20100", telefono="02 1234567",
             email="amministrazione@labruschetta.it"),
        _persona("legale_rappresentante", nome_completo="Stefano Griva"),
        _persona("lavoratore", nome_completo="Ada Rossi", via="Via Bologna", civico="7",
                 citta="Torino", cap="10152", email="ada.rossi@gmail.com"),
    ]))
    assert esito.campi["via"] == "Via Bologna 7"
    assert esito.campi["cap"] == "10152"
    assert esito.campi["email"] == "ada.rossi@gmail.com"
    assert "telefono" not in esito.campi, "il centralino non è il suo telefono"
    assert esito.campi["datore"] == "La Bruschetta Srl"


def test_se_non_si_capisce_il_verso_meglio_non_far_nulla():
    """Quando non si distingue chi emette da chi riceve, i dati delle due parti si mescolano.
    **Un campo vuoto si vede, un campo sbagliato no.**"""
    esito = _estrai(_lettura(
        [_persona(nome_completo="Ada Rossi", codice_fiscale="RSSDAA90A41H501K")],
        verso="incerto",
    ))
    assert esito.campi == {}
    assert any("mescolano" in a for a in esito.avvisi)


def test_due_persone_senza_ruolo_non_si_scelgono_a_caso():
    esito = _estrai(_lettura([
        _persona("altro", nome_completo="Ada Rossi"),
        _persona("altro", nome_completo="Karim Ben Salah"),
    ]))
    assert esito.campi == {}
    assert any("2 persone" in a for a in esito.avvisi)


def test_una_persona_sola_non_ha_ruoli_da_distinguere():
    """Una carta d'identità parla di una persona e basta: pretendere il ruolo lascerebbe
    vuota una scheda che si poteva riempire."""
    esito = _estrai(_lettura([_persona("altro", nome_completo="Ada Rossi", citta="Torino")],
                             natura="identita"))
    assert esito.campi["cognome"] == "Rossi"
    assert esito.tipo_documento == "identita"


def test_del_rapporto_di_lavoro_si_prende_tutto_quello_che_c_e():
    """In un contratto ci sono la data, l'orario, la mansione, il livello e la paga.
    Chiederli uno per uno significava dimenticarne sempre qualcuno."""
    esito = _estrai(_lettura(
        [_persona(nome_completo="Ada Rossi")],
        [{"tipo": "rapporto_di_lavoro", "attributi": {
            "data_inizio": "1° settembre 2026", "tipo_contratto": "determinato",
            "ore_settimanali": "24 ore settimanali", "mansione": "cameriere",
            "retribuzione_oraria": "9,50 euro",
        }}],
    ))
    assert esito.campi["data_assunzione"] == "2026-09-01"
    assert esito.campi["monte_ore_settimanale"] == "24"
    assert esito.campi["mansione"] == "cameriere"
    assert esito.campi["retribuzione_oraria"] == "9.50"


def test_su_un_locale_conta_l_immobile_non_le_parti():
    """In un contratto di locazione ci sono **tre indirizzi** — la sede del locatore, quella
    del conduttore e l'immobile — e solo il terzo è il locale."""
    esito = _estrai(
        _lettura(
            [
                _org("locatore", denominazione="Immobiliare Sud Srl", via="Via Argiro",
                     civico="30", citta="Bari", cap="70121"),
                _org("conduttore", denominazione="La Bruschetta Srl", via="Corso Italia",
                     civico="1", citta="Milano", cap="20100"),
                _luogo("immobile", via="Via Matarrese", civico="9", citta="Bari",
                       cap="70124", provincia="Bari"),
            ],
            [{"tipo": "locazione", "attributi": {"insegna": "La Bruschetta 3"}}],
            natura="contratto_affitto",
        ),
        tipo="locale",
    )
    assert esito.campi["via"] == "Via Matarrese 9"
    assert esito.campi["cap"] == "70124"
    assert esito.campi["provincia"] == "BA"
    assert esito.campi["nome"] == "La Bruschetta 3"


def test_i_metri_quadri_non_sono_i_posti():
    esito = _estrai(
        _lettura([_luogo("immobile", via="Via Matarrese", civico="9")],
                 [{"tipo": "locazione", "attributi": {"superficie_mq": "120"}}],
                 natura="contratto_affitto"),
        tipo="locale",
    )
    assert "capienza" not in esito.campi
    assert any("120 mq" in a for a in esito.avvisi)


def test_la_stessa_lettura_serve_due_schede():
    """**È il punto dell'architettura.** La domanda al modello è la stessa; cambia la tabella
    che traduce la lettura in campi. Un campo nuovo si aggiunge lì, non nel prompt."""
    letto = _lettura(
        [_persona(nome_completo="Ada Rossi", citta="Torino"),
         _luogo("immobile", via="Via Matarrese", civico="9", citta="Bari")],
        natura="contratto_affitto",
    )
    assert _estrai(letto, "persona").campi["cognome"] == "Rossi"
    assert _estrai(letto, "locale").campi["via"] == "Via Matarrese 9"


# --------------------------------------------------------------------------
# 3 · Il dominio decide


def test_il_codice_fiscale_decide_come_si_scrive_il_nome():
    """**Il modello dice chi, l'aritmetica dice come si scrive.**

    «Ben Salah Karim» e «Karim Ben Salah» si scrivono entrambi, e la convenzione sbaglia una
    volta su due. Le prime sei lettere del codice sono consonanti di cognome e nome in
    quest'ordine: l'ordine non si indovina, si **calcola**.
    """
    esito = _estrai(_lettura([_persona(
        nome_completo="Karim Ben Salah", codice_fiscale="BNSKRM90A01Z352P",
    )]))
    assert (esito.campi["cognome"], esito.campi["nome"]) == ("Ben Salah", "Karim")
    assert esito.campi["data_nascita"] == "1990-01-01", "sta già dentro il codice"


def test_una_data_di_nascita_discorde_dal_codice_si_segnala_ma_vince_il_codice():
    esito = _estrai(_lettura([_persona(
        nome_completo="Karim Ben Salah", codice_fiscale="BNSKRM90A01Z352P",
        data_nascita="3 marzo 1988",
    )]))
    assert esito.campi["data_nascita"] == "1990-01-01"
    assert any("vale il codice fiscale" in a for a in esito.avvisi)


def test_la_stessa_data_scritta_in_due_modi_non_e_una_discordanza():
    """Segnalarle come discordanti insegna a ignorare gli avvisi, e un avviso ignorato tanto
    vale non scriverlo."""
    esito = _estrai(_lettura([_persona(
        nome_completo="Karim Ben Salah", codice_fiscale="BNSKRM90A01Z352P",
        data_nascita="1 gennaio 1990",
    )]))
    assert esito.avvisi == []


def test_il_codice_fiscale_letto_male_non_entra_nella_scheda():
    """**Il test che conta.** È il dato che nessuno riverifica dopo che «l'ha letto il
    computer», ed è la chiave con cui l'anagrafica si riconcilia con le paghe."""
    esito = _estrai(_lettura([_persona(
        nome_completo="Ada Rossi", codice_fiscale="RSSDAA90A41H501Z",
    )]))
    assert "codice_fiscale" not in esito.campi
    assert any("carattere finale" in a for a in esito.avvisi)


def test_la_nazionalita_diventa_un_codice_di_due_lettere():
    """Un documento non scrive mai «NG»: scrive «di nazionalità nigeriana»."""
    esito = _estrai(_lettura([_persona(nome_completo="Ada Rossi", nazionalita="nigeriana")]))
    assert esito.campi["nazionalita"] == "NG"


def test_una_nazionalita_che_non_si_riconosce_lascia_il_campo_vuoto_e_lo_dice():
    esito = _estrai(_lettura([_persona(nome_completo="Ada Rossi", nazionalita="cittadino")]))
    assert "nazionalita" not in esito.campi
    assert any("cittadino" in a for a in esito.avvisi)


def test_una_provincia_inventata_si_scarta_e_un_nome_diventa_una_sigla():
    inventata = _estrai(_lettura([_persona(nome_completo="A Rossi", provincia="Piemonte")]))
    assert "provincia" not in inventata.campi
    per_esteso = _estrai(_lettura([_persona(nome_completo="A Rossi", provincia="Torino")]))
    assert per_esteso.campi["provincia"] == "TO"


def test_un_cap_che_non_e_un_cap_si_scarta():
    assert "cap" not in _estrai(_lettura([_persona(nome_completo="A R", cap="101")])).campi


def test_un_vuoto_travestito_non_e_un_dato():
    """«non indicato» dentro un campo è peggio di un campo vuoto: un campo vuoto si vede e
    si compila, un campo con una scusa dentro sembra un dato e resta lì."""
    esito = _estrai(_lettura([_persona(
        nome_completo="Ada Rossi", email="N/A", telefono="non disponibile", citta="—",
    )]))
    assert set(esito.campi) == {"cognome", "nome"}


def test_quello_che_manca_si_dice():
    esito = _estrai(_lettura([_persona(nome_completo="Ada Rossi", citta="Torino")]))
    assert "codice_fiscale" in esito.non_trovati
    assert "citta" not in esito.non_trovati


# --------------------------------------------------------------------------
# 4 · Degradare, non rompere


def test_senza_modello_resta_una_scheda_vuota_che_dice_perche():
    """Senza AI il programma funziona: perde la compilazione automatica, non la scheda.
    L'anonimizzatore sa che lì c'è un nome, non di chi è — e questo va detto."""

    class SenzaChiave:
        def genera(self, domanda):
            raise modello.ModelloNonDisponibile("chiave assente")

    esito = estrattore.estrai("testo", cliente=SenzaChiave(), servizio=Anonimizzatore())
    assert esito.campi == {}
    assert any("non è disponibile" in a for a in esito.avvisi)
    assert esito.non_trovati, "si dice comunque cosa resta da scrivere"


def test_senza_testo_mascherato_non_si_manda_niente_fuori():
    """Un PDF che è solo l'immagine di una pagina non dà testo da mascherare. Non si manda
    il file: si dice che non si può leggere."""
    cliente = Modello(_lettura([_persona(nome_completo="Ada Rossi")]))
    esito = estrattore.estrai("x", cliente=cliente, servizio=Anonimizzatore("   "))
    assert cliente.domande == [], "il modello non è stato nemmeno chiamato"
    assert any("non ha prodotto testo mascherato" in a for a in esito.avvisi)


def test_il_json_incorniciato_nel_blocco_di_codice_si_legge_lo_stesso():
    """Rifiutare una risposta giusta per tre backtick è il modo più stupido di perdere una
    lettura."""
    dentro = json.dumps(_lettura([_persona(nome_completo="Ada Rossi")]))
    assert _estrai(f"```json\n{dentro}\n```").campi["cognome"] == "Rossi"


def test_una_risposta_che_non_e_json_lo_dice():
    with pytest.raises(lettura.LetturaIlleggibile) as errore:
        _estrai("Non riesco a leggere il documento.")
    assert "non ha prodotto dati utilizzabili" in str(errore.value)


def test_una_risposta_troncata_non_da_la_colpa_alla_scansione():
    """Due cause diverse, due messaggi diversi: una risposta troncata è un difetto nostro, e
    mandare a rifare una scansione che andava benissimo sposta la colpa."""
    with pytest.raises(lettura.LetturaIlleggibile) as errore:
        _estrai('{"documento": {"spiegazione": "' + "x" * 300)
    assert "si è interrotta a metà" in str(errore.value)


def test_una_scheda_che_non_esiste_si_rifiuta_prima_di_pagare_il_modello():
    cliente = Modello(_lettura())
    with pytest.raises(ValueError):
        estrattore.estrai("x", "fornitore", cliente=cliente, servizio=Anonimizzatore())
    assert cliente.domande == []


# --------------------------------------------------------------------------
# Il dominio, da solo


def test_il_checksum_del_codice_fiscale():
    assert dominio.valido("BNSKRM90A01Z352P")
    assert not dominio.valido("BNSKRM90A01Z352V"), "un carattere finale sbagliato"
    assert not dominio.valido("BNSKRM90A01")


def test_dal_codice_fiscale_la_data_e_il_sesso():
    nascita, sesso = dominio.data_e_sesso("RSSDAA90A41H501K")
    assert nascita.isoformat() == "1990-01-01"
    assert sesso == "F", "il giorno maggiorato di 40"


def test_il_secolo_non_e_nel_codice_fiscale():
    """Due cifre per l'anno, e chi le ha scelte nel 1973 non pensava al 2000. Si prende la
    più recente delle due date che non sia nel futuro."""
    nascita, _ = dominio.data_e_sesso("BNSKRM90A01Z352P")
    assert nascita.year == 1990


def test_le_date_come_le_scrivono_i_documenti():
    assert dominio.leggi_data("12 agosto 1994") == "1994-08-12"
    assert dominio.leggi_data("1° settembre 2026") == "2026-09-01"
    assert dominio.leggi_data("12/08/1994") == "1994-08-12"
    assert dominio.leggi_data("1994-08-12") == "1994-08-12"
    assert dominio.leggi_data("il giorno dopo") == "", "vuoto, non il testo così com'era"
    assert dominio.leggi_data("31 febbraio 1994") == ""


def test_il_codice_paese_gia_a_posto_non_peggiora():
    """La funzione la chiamano sia la lettura sia il salvataggio: deve essere idempotente."""
    assert dominio.nazionalita("NG") == "NG"
    assert dominio.nazionalita(dominio.nazionalita("nigeriana")) == "NG"
    assert dominio.nazionalita("di nazionalità tunisina") == "TN"


def test_le_parentesi_quadre_perse_dal_modello_si_rimettono():
    """Il modello a volte risponde `STREET_2 BUILDINGNUM_2` senza parentesi. Senza, la
    ricomposizione non scatta e resta a video il nome del segnaposto."""
    mappa = {"[STREET_2]": "Via Matarrese", "[BUILDINGNUM_2]": "9"}
    assert pii.ricomponi("STREET_2 BUILDINGNUM_2", mappa) == "Via Matarrese 9"
    assert pii.normalizza("PIZZAIOLO", mappa) == "PIZZAIOLO", "non è un segnaposto"


def test_il_segnaposto_lungo_non_lo_rovina_il_corto():
    """`[FULLNAME_10]` contiene `[FULLNAME_1]`: sostituendo prima il corto si otterrebbe
    «Mario Rossi0»."""
    mappa = {"[FULLNAME_1]": "Mario Rossi", "[FULLNAME_10]": "Anna Bianchi"}
    assert pii.ricomponi("[FULLNAME_10]", mappa) == "Anna Bianchi"


def test_i_segnaposto_si_riconoscono_per_quello_che_sono():
    assert scheda._e_un_segnaposto("[FULLNAME_1]")
    assert scheda._e_un_segnaposto("[STREET_2] [BUILDINGNUM_2]")
    assert not scheda._e_un_segnaposto("Via Bologna 7")
