# Chi è chi

**Leggere un contratto di assunzione senza mandare il contratto fuori.**

Un anonimizzatore che gira in locale maschera ogni dato personale; un modello linguistico,
leggendo il testo **mascherato**, dice che cosa c'è nel documento — quali entità, con quale
ruolo, con quali attributi, legate da quali relazioni. I valori tornano al loro posto qui,
sulla propria macchina, e il dominio decide quali sono validi.

Il fornitore del modello non vede un solo dato personale. Eppure risponde questo:

```
 4.5 s  1 · anonimizzazione (in locale)
        51 entità, 12 tipi; 35 segnaposto. Da qui in poi esce solo il testo mascherato.
31.0 s  2 · lettura sul testo mascherato
        lettera_assunzione · verso chiaro · 4 entità
        (datore, legale_rappresentante, lavoratore, sede_di_lavoro), 1 relazioni.
    —   3 · mappatura sulla scheda
        18 campi compilati, 0 da scrivere a mano.
```

> 📐 **[ARCHITETTURA.md](ARCHITETTURA.md)** — l'engine per intero: i diagrammi del confine e
> del flusso, la mappa dei moduli, le degradazioni, l'architettura scartata e perché, i
> numeri misurati. Questo README racconta l'idea; quello descrive il motore.

---

## Il problema

Un anonimizzatore dà **tipi, non ruoli**.

Su una lettera di assunzione di due pagine trova cinquantuno entità: due `FULLNAME`, due
`CF`, tre `STREET`, sei `DATE`, due `EMAIL`. E ha ragione su tutte. Ma «qui ci sono due
persone» non è «questa è quella che stai assumendo», e nessuna quantità di riconoscimento di
entità colma quella distanza.

Il ruolo non sta nel dato. Sta **nelle parole intorno**:

> **Egr. Sig.** Karim Ben Salah, **residente in** Via Salvatore Matarrese 9
> […]
> Ristorazione Mediterranea S.r.l., **con sede legale in** Via Giulio Petroni 148
> […]
> **Il legale rappresentante** Domenico Sarnataro

Prendere «la prima email che si trova» dà la PEC dell'azienda. Prendere «l'unico indirizzo»
dà la sede legale. Prendere «l'ultima parola del nome» come cognome dà `Karim` invece di
`Ben Salah`. Sono tutti dati veri, e sono tutti nel campo sbagliato — che è peggio di un
campo vuoto, perché un campo vuoto si vede e un campo sbagliato no.

## L'osservazione

Quelle parole — «Egr. Sig.», «con sede legale in», «il legale rappresentante» — **non sono
dati personali**. Quindi l'anonimizzatore non le tocca. Quindi restano leggibili nel testo
che esce.

Il modello riceve questo:

```
[ORG_1]
Sede legale: [STREET_1] [BUILDINGNUM_1] — [ZIPCODE_1] [CITY_1] ([PROVINCE_1])
PEC: [EMAIL_1] — Tel. [TELEPHONENUM_2]

Egr. Sig.
[FULLNAME_1]
[STREET_2] [BUILDINGNUM_2]

1. DATI DEL LAVORATORE
   Cognome e nome: [FULLNAME_2]
   Nato a: [CITY_2] ([CITY_3]) il [DATE_2]
   Codice fiscale: [CF_1]
```

e ha tutto quello che gli serve per dire che `[FULLNAME_1]` è il lavoratore, che
`[STREET_2]` è la **sua** residenza e che `[EMAIL_1]` è invece dell'azienda — senza sapere
come si chiama nessuno, e senza che nessuno glielo dica.

## I tre passaggi

```
  1. ANONIMIZZARE   tutto in locale. Ogni dato personale diventa un segnaposto, e la
     (rizzo-pii)    mappa per rimetterli a posto NON esce da questo processo.

  2. LEGGERE        sul testo MASCHERATO, una domanda sola: che cosa c'è dentro.
     (LLM)          Entità, ruoli, attributi, relazioni.

  3. MAPPARE        la lettura diventa una scheda, i valori tornano dalla mappa, e il
     (codice)       dominio decide quali sono validi.
```

### Cosa si chiede al modello

Non un modulo da riempire: una **lettura**.

```json
{
  "documento": {"natura": "lettera_assunzione", "verso": "chiaro", "spiegazione": "…"},
  "entita": [
    {"tipo": "persona", "ruolo": "lavoratore",
     "attributi": {"nome_completo": "[FULLNAME_2]", "codice_fiscale": "[CF_1]"}},
    {"tipo": "organizzazione", "ruolo": "datore", "attributi": {"…": "…"}},
    {"tipo": "persona", "ruolo": "legale_rappresentante", "attributi": {"…": "…"}}
  ],
  "relazioni": [
    {"tipo": "rapporto_di_lavoro",
     "attributi": {"data_inizio": "1° settembre 2026", "mansione": "pizzaiolo",
                   "ore_settimanali": "40", "livello_inquadramento": "4° livello"}}
  ]
}
```

La differenza non è stilistica. Chiedere «qual è la data di assunzione» è chiedere una riga
di una tabella che il modello deve comunque ricostruire per intero — e ogni riga che non si
pensa a chiedere è una riga persa. Chiedere «dimmi che cosa c'è dentro» la fa costruire una
volta sola, completa.

Da lì alla scheda è **codice esatto**: una tabella dichiarata in
[`scheda.py`](chi_e_chi/scheda.py), nessuna interpretazione. Interpretare è il lavoro del
passaggio prima, e tenerli separati è il motivo per cui, quando qualcosa non torna, si sa
quale dei due ha sbagliato.

### Se il verso non è chiaro, non si fa niente

Ogni atto ha due parti: chi lo emette e chi lo riceve. Se il modello non le distingue, lo
**dichiara**, e allora non si compila niente: una scheda mescolata è peggio di una vuota.

### Il dominio decide, sempre

Il modello propone; il codice esatto decide. Un codice fiscale con il carattere di controllo
sbagliato non entra nella scheda con l'aria di essere giusto — è esattamente il dato che
nessuno riverifica dopo che «l'ha letto il computer».

E dove il codice sa fare meglio, fa meglio:

```python
dominio.nome_dal_codice(["Karim Ben Salah"], "BNSKRM94C12Z352D")
# ('Ben Salah', 'Karim')     ← non indovinato: calcolato
```

«Ben Salah Karim» e «Karim Ben Salah» si scrivono entrambi, e la convenzione sbaglia una
volta su due. Le prime sei lettere del codice fiscale sono consonanti di cognome e nome in
quest'ordine: l'ordine non si indovina, si calcola. E da lì discendono anche la data di
nascita e il sesso, che nel codice ci sono già.

Lo stesso vale per le date come le scrivono i documenti («1° settembre 2026»), per le
province («Bari» → `BA`) e per le nazionalità («di nazionalità marocchina» → `MA`).

## Il risultato, sul contratto d'esempio

**18 campi, nessun campo mancante, nessun avviso.**

```json
{
  "cognome": "Ben Salah",   "nome": "Karim",
  "codice_fiscale": "BNSKRM94C12Z352D",
  "data_nascita": "1994-03-12",
  "nazionalita": "MA",
  "via": "Via Salvatore Matarrese 9",
  "cap": "70124", "citta": "Bari", "provincia": "BA",
  "email": "karim.bensalah94@gmail.com",
  "telefono": "347 6612094",
  "datore": "RISTORAZIONE MEDITERRANEA S.R.L.",
  "sede_lavoro": "La Bruschetta",
  "data_assunzione": "2026-09-01",
  "tipo_contratto": "indeterminato",
  "mansione": "pizzaiolo",
  "livello_inquadramento": "4° livello",
  "monte_ore_settimanale": "40"
}
```

L'email è quella del lavoratore e non la PEC aziendale; l'indirizzo è la sua residenza e non
la sede legale; il codice fiscale è il suo e non quello del legale rappresentante — ce ne
sono **due validi** nel documento, e nessun anonimizzatore poteva sceglierne uno.

## La stessa lettura, schede diverse

`persona` compila un dipendente e il suo rapporto di lavoro. `locale` compila una sede
operativa — e in un contratto di locazione ci sono **tre indirizzi**, la sede del locatore,
quella del conduttore e l'immobile, e solo il terzo è il locale.

La domanda al modello è la stessa. Cambia la tabella che traduce la lettura in campi:

```bash
python prova.py contratto.pdf persona
python prova.py contratto.pdf locale
```

## Provarlo

Servono due cose accese, e una sola è obbligatoria.

**1 · L'anonimizzatore, in locale.**
[rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii) gira su CPU, in un container.
Quando è pronto, `http://127.0.0.1:5005/health` risponde `model_loaded: true` — ci mette una
decina di secondi dall'avvio.

**2 · Il modello.** Senza chiave il programma funziona: torna una scheda vuota e dice cosa
si sta perdendo. Senza modello non c'è nessuno che sappia dire chi è chi.

```bash
git clone <questo-repo> && cd chi-e-chi

python -m venv .venv
.venv/bin/pip install -e ".[ai]"          # Windows: .venv\Scripts\pip

cp .env.example .env                       # e ci si mette la chiave
.venv/bin/python prova.py                  # Windows: .venv\Scripts\python
```

Il `.env` lo legge `prova.py` da sé, senza librerie. Le variabili già esportate
nell'ambiente vincono su quelle del file.

Nel repo ci sono due documenti di prova:

```bash
.venv/bin/python prova.py esempi/contratto-assunzione.txt   # 2 KB, testo
.venv/bin/python prova.py esempi/contratto-cuoco.pdf        # 4 pagine, PDF
```

Sono documenti di simulazione: persone, recapiti e indirizzi sono generati, e le e-mail usano
il dominio riservato `example.com` (RFC 2606). I codici fiscali sono **validi come
checksum** — con codici finti metà dell'esempio non si vedrebbe, perché il dominio non
avrebbe niente da calcolare.

Per i PDF serve `pip install -e ".[pdf]"`.

I test girano senza niente acceso, né anonimizzatore né modello:

```bash
.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
```

### Se qualcosa non va

| cosa si vede | cosa vuol dire |
|---|---|
| `anonimizzatore: … (SPENTO)` | il container non risponde su `PII_URL`. Il programma lo dice e si ferma: senza maschera non manda niente a nessuno. |
| `modello: — (SPENTO)` | manca `ANTHROPIC_API_KEY`. Torna una scheda vuota con l'avviso: l'anonimizzatore sa che lì c'è un nome, non di chi è. |
| `verso: incerto` | il modello non ha distinto le parti, e allora **non compila niente**: una scheda mescolata è peggio di una vuota. |
| `non ha prodotto testo mascherato` | il PDF è la scansione di un'immagine. Non c'è niente da mascherare, e quindi niente da mandare fuori. |

## Quello che ho misurato

Sulla macchina di sviluppo, un portatile senza GPU:

| | |
|---|---|
| anonimizzatore, costo | **~1,5 ms per carattere**, lineare su tutta la scala |
| anonimizzatore, 2.400 caratteri | ~4,5 s |
| anonimizzatore, 19.000 caratteri | ~26 s |
| anonimizzatore, richieste in parallelo | **non parallelizza**: 12 nuclei, 2/4/8 pezzi insieme rendono 1,0x / 0,8x / 0,9x |
| modello, lettura completa sul mascherato | ~31 s |

Due conseguenze pratiche:

- l'unica leva sull'anonimizzatore è **mandargli meno testo**, e per farlo bisogna averlo in
  mano;
- il tempo del modello se ne va **a scrivere**, non a leggere: dimezzare il testo in ingresso
  non sposta l'attesa, ridurre la risposta sì. Ed è anche il motivo per cui **una** domanda
  che chiede tutto costa meno di cinque domande che chiedono un campo ciascuna.

Ho anche provato un modello più piccolo e veloce: 32 secondi invece di 54, e tre esecuzioni
con tre risultati diversi. Capire che una via è la residenza del dipendente e l'altra la sede
della società *sembra* meccanico e non lo è: è comprensione del testo. Venti secondi non
valgono un campo sbagliato.

## Cosa esce da questa macchina

Il testo mascherato, e basta. La mappa segnaposto → valore resta nel processo che l'ha
creata. `prova.py` lo mostra in fondo, con il conteggio dei valori mascherati rimasti nel
testo uscito — che è zero, e che si calcola dove la mappa è in mano, non a valle dove non si
potrebbe più.

Il caso in cui **non** funziona è dichiarato: un PDF che è la scansione di una pagina non ha
un livello di testo, e l'anonimizzatore legge testo, non fa OCR. Lì o si fa OCR in locale, o
si manda fuori il documento — e va detto a chi lo sta caricando, non scoperto dopo.

## Una nota su com'è nato

La prima versione faceva un passaggio in più: l'anonimizzatore attribuiva i campi che sapeva
attribuire da solo — «di email ce n'è una, sarà la sua» — e al modello si chiedeva solo il
resto, campo per campo. Funzionava, e perdeva dati nelle cuciture: la nazionalità mascherata
come nome proprio, la PEC aziendale nel campo del dipendente, i campi del contratto che
nessuno pensava a chiedere.

Erano tutti lo stesso difetto, ed era architetturale. **Un anonimizzatore non è un
estrattore**, e ogni volta che gli si chiedeva un ruolo bisognava aggiungere un pezzo per
correggere la risposta.

Ora il compito di capire è tutto del modello, il compito di anonimizzare è tutto
dell'anonimizzatore, e il compito di decidere se un dato è valido resta del codice. Il
risultato, sullo stesso documento: da 15 campi con due avvisi a 18 campi senza avvisi.
