# Chi è chi

**Estrarre i dati di un contratto di assunzione senza mandare il contratto fuori.**

Un rilevatore di dati personali che gira in locale trova le entità; un modello linguistico,
leggendo il testo **mascherato**, decide quale entità ha quale ruolo — chi è il datore di
lavoro e chi il dipendente. I valori tornano al loro posto qui, sulla propria macchina.

Il fornitore del modello non vede un solo dato personale. Eppure risponde questo:

```
CHI È CHI — quello che il modello ha capito senza vedere i nomi
  soggetto     Ben Salah Karim
  controparte  RISTORAZIONE MEDITERRANEA S.R.L.
  verso        chiaro
  perché       L'atto è emesso da RISTORAZIONE MEDITERRANEA S.R.L. («Sede legale»,
               firma «Il legale rappresentante Domenico Sarnataro») e indirizzato
               «Egr. Sig. Karim Ben Salah», i cui dati sono ripresi al punto 1
               «DATI DEL LAVORATORE».
```

---

## Il problema

Un rilevatore di entità dà **tipi, non ruoli**.

Su una lettera di assunzione di due pagine ne trova cinquanta: due `FULLNAME`, due `CF`,
tre `STREET`, sei `DATE`, due `EMAIL`. E ha ragione su tutte. Ma «qui ci sono due persone»
non è «questa è quella che stai assumendo», e nessuna quantità di riconoscimento di entità
colma quella distanza.

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
Egr. Sig.
[FULLNAME_1]
[STREET_3] [BUILDINGNUM_3]
[ZIPCODE_1] [CITY_1] ([PROVINCE_1])

1. DATI DEL LAVORATORE
   Cognome e nome: [FULLNAME_1]
   Nato a: [CITY_4] il [DATE_2]
   Codice fiscale: [CF_1]
```

e ha tutto quello che gli serve per dire che `[FULLNAME_1]` è il lavoratore e `[STREET_3]`
è la **sua** residenza — senza sapere come si chiama e senza che nessuno glielo dica.

## I tre passaggi

```
  1. RILEVATORE       tutto in locale. Trova le entità e ne attribuisce quelle che sa
     (rizzo-pii)      attribuire da solo — per aritmetica, non per ipotesi.

  2. MODELLO          sul testo MASCHERATO. Decide chi è chi. È l'unica cosa che un
     (LLM)            rilevatore di entità non può fare.

  3. RICOMPOSIZIONE   i segnaposto tornano valori, in locale, e poi si validano.
```

### 1 · Quello che il codice sa da solo

Il passaggio 2 costa tempo e denaro, quindi si fa **solo per quello che resta**.

Un codice fiscale con il checksum giusto *contiene* la data di nascita, e con la regola delle
prime sei lettere dice quale dei nomi trovati è il suo. Non è un'euristica, è aritmetica:

```python
dominio.nome_dal_codice(["Domenico Sarnataro", "Ben Salah Karim"], "BNSKRM94C12Z352D")
# ('Ben Salah', 'Karim')
```

Fra due nomi non si indovina: si calcola. E quando il calcolo basta, il modello non si
chiama affatto.

### 2 · Chi è chi

Al modello si chiede il **verso dell'atto** prima dei campi: chi lo emette (il *dante causa*)
e chi lo riceve (l'*avente causa*). Poi si chiede di attribuire, e in più l'elenco dei
segnaposto che appartengono alla controparte — quelli si potano dai menù.

Se il verso non è chiaro, il modello lo dichiara e **non si attribuisce niente** che non sia
certo per costruzione. Una scheda mescolata è peggio di una vuota.

### 3 · Ricomposizione, e poi i controlli

I segnaposto tornano valori **qui**, dalla mappa che non è mai uscita. E solo dopo si valida:
un `[ZIPCODE_3]` non è un CAP di cinque cifre, e validare prima di ricomporre significa
buttare via la risposta giusta.

## Le due regole che tengono in piedi il resto

**«Certo per costruzione» non è «ce n'era uno solo».**
Il codice fiscale validato è aritmetica: nessuna rilettura lo migliora, e il modello non lo
tocca. «C'era una sola email nel documento» è invece un'ipotesi — e su una carta intestata è
pure sbagliata. I primi non si toccano; i secondi si sottopongono al modello, che ha il
contesto davanti.

**Il tipo di un dato lo decide il rilevatore, non il modello.**
Alla domanda «quale segnaposto è la via» può arrivare `[ORG_1]`. Il rilevatore aveva già
deciso che è un'organizzazione, e quella decisione vince: la risposta si scarta e il campo
resta visibilmente vuoto invece che invisibilmente falso.

```python
schema.tipo_compatibile("via", "[STREET_2] [BUILDINGNUM_2]")   # True — via e civico
schema.tipo_compatibile("via", "[ORG_1]")                      # False — è una società
```

## Il risultato, sul contratto d'esempio

15 campi, tutti corretti. Il codice fiscale scelto è quello del lavoratore e non quello del
legale rappresentante — entrambi validi, e il rilevatore da solo non poteva sceglierne uno.

```json
{
  "cognome": "Ben Salah",   "nome": "Karim",
  "codice_fiscale": "BNSKRM94C12Z352D",
  "data_nascita": "1994-03-12",
  "via": "Via Salvatore Matarrese 9",
  "cap": "70124", "citta": "Bari", "provincia": "BA",
  "email": "karim.bensalah94@gmail.com",
  "telefono": "347 6612094",
  "datore": "RISTORAZIONE MEDITERRANEA S.R.L.",
  "data_assunzione": "2026-09-01",
  "tipo_contratto": "indeterminato",
  "mansione": "pizzaiolo",
  "monte_ore_settimanale": "40"
}
```

Con un avviso che dice **come** ci si è arrivati:

> Il codice fiscale BNSKRM94C12Z352D è coerente con «Ben Salah Karim»: cognome, nome e data
> di nascita non sono stati letti, sono stati **calcolati**.

## Provarlo

Servono due cose accese, e una sola è obbligatoria.

**1 · Il rilevatore, in locale.** [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii)
gira su CPU, in un container. Quando è pronto, `http://127.0.0.1:5005/health` risponde
`model_loaded: true` — ci mette una decina di secondi dall'avvio.

**2 · Il modello.** Facoltativo. Senza chiave il programma funziona: attribuisce quello che
il codice sa calcolare da solo, e dichiara cosa si sta perdendo.

```bash
git clone <questo-repo> && cd chi-e-chi

python -m venv .venv
.venv/bin/pip install -e ".[ai]"          # Windows: .venv\Scripts\pip

cp .env.example .env                       # e ci si mette la chiave
.venv/bin/python prova.py                  # Windows: .venv\Scripts\python
```

Il `.env` lo legge `prova.py` da sé, senza librerie. Le variabili già esportate
nell'ambiente vincono su quelle del file.

Accetta anche un percorso, e anche un PDF (`pip install -e ".[pdf]"`):

```bash
.venv/bin/python prova.py esempi/contratto-assunzione.txt
.venv/bin/python prova.py ~/un-contratto-vero.pdf
```

Il documento d'esempio è un fac-simile: nomi, indirizzi e recapiti sono inventati. I codici
fiscali sono **validi come checksum**, perché è esattamente ciò che l'esempio dimostra — con
codici finti il passaggio deterministico non avrebbe niente da calcolare.

I test girano senza niente acceso, né rilevatore né modello:

```bash
.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
```

### Se qualcosa non va

| cosa si vede | cosa vuol dire |
|---|---|
| `rilevatore: … (SPENTO)` | il container non risponde su `PII_URL`. Il programma lo dice e si ferma: senza maschera non manda niente a nessuno. |
| `modello: — (SPENTO)` | manca `ANTHROPIC_API_KEY`. Funziona lo stesso: escono i campi calcolati dal codice fiscale, e un avviso dice cosa manca. |
| `verso: incerto` | il modello non ha distinto le parti. Allora **non attribuisce niente** che non sia certo per costruzione: una scheda mescolata è peggio di una vuota. |

## Quello che ho misurato

Sulla macchina di sviluppo, un portatile senza GPU:

| | |
|---|---|
| rilevatore, costo | **~1,5 ms per carattere**, lineare su tutta la scala |
| rilevatore, 2.400 caratteri | ~5 s |
| rilevatore, 19.000 caratteri | ~26 s |
| rilevatore, richieste in parallelo | **non parallelizza**: 12 nuclei, 2/4/8 pezzi insieme rendono 1,0x / 0,8x / 0,9x |
| modello, sul testo mascherato | 10–25 s, a seconda del modello |

Due conseguenze pratiche:

- l'unica leva sul rilevatore è **mandargli meno testo**, e per farlo bisogna averlo in mano;
- il tempo del modello se ne va **a scrivere**, non a leggere: dimezzare il testo in ingresso
  non sposta l'attesa, ridurre la risposta sì.

Ho anche provato un modello più piccolo e veloce: 32 secondi invece di 54, e tre esecuzioni
con tre risultati diversi. Attribuire un segnaposto al campo giusto *sembra* meccanico e non
lo è — capire che una via è la residenza del dipendente e l'altra la sede della società è
comprensione del testo. Venti secondi non valgono un campo sbagliato.

## Cosa esce da questa macchina

Il testo mascherato, e basta. La mappa segnaposto → valore resta nel processo che l'ha
creata. `prova.py` lo mostra in fondo, con il conteggio dei valori personali rimasti nel
testo uscito — che è zero.

Il caso in cui **non** funziona è dichiarato: un PDF che è la scansione di una pagina non ha
un livello di testo, e il rilevatore legge testo, non fa OCR. Lì o si fa OCR in locale, o si
manda fuori il documento — e va detto a chi lo sta caricando.

