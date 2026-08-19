"""L'esempio, da guardare **mentre lavora**.

    python prova.py esempi/contratto-assunzione.txt
    python prova.py esempi/contratto-locazione.txt locale

Stampa i tre passaggi con i loro tempi, quello che il testo mascherato contiene davvero, e
il risultato. Il punto da guardare è il passaggio 2: che cosa vede il modello, e che cosa
riesce a dire senza vedere un solo dato personale.

Il secondo argomento è la scheda da compilare — `persona` o `locale`. La domanda al modello
è **la stessa**: cambia solo la tabella che traduce la lettura in campi.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from chi_e_chi import estrattore, lettura, modello, pii

# Su Windows la console parla ancora cp1252 e un trattino lungo la fa esplodere. Il
# documento è italiano e la traccia pure: si dichiara UTF-8 invece di rinunciare agli
# accenti.
for flusso in (sys.stdout, sys.stderr):
    if hasattr(flusso, "reconfigure"):
        flusso.reconfigure(encoding="utf-8", errors="replace")


def carica_env(percorso: Path = Path(".env")) -> None:
    """Legge il `.env`, se c'è. Senza librerie.

    Il file esisteva e nessuno lo leggeva: si diceva «copia `.env.example` in `.env`» e poi
    le variabili non arrivavano da nessuna parte. Quindici righe qui valgono più di una
    dipendenza in più su un progetto che si vanta di non averne.

    Le variabili già presenti nell'ambiente **vincono**: chi le esporta a mano lo fa per
    scavalcare il file, non per essere scavalcato.
    """
    if not percorso.exists():
        return
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        pulita = riga.strip()
        if not pulita or pulita.startswith("#") or "=" not in pulita:
            continue
        chiave, valore = pulita.split("=", 1)
        chiave = chiave.strip()
        if chiave and chiave not in os.environ:
            os.environ[chiave] = valore.strip().strip("'\"")


def leggi(percorso: Path) -> str:
    if percorso.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print("Per i PDF serve pypdf: pip install pypdf", file=sys.stderr)
            raise SystemExit(2) from None
        import re

        pagine = [p.extract_text() or "" for p in PdfReader(str(percorso)).pages]
        # pypdf separa le parole con tabulazioni: al rilevatore va dato testo normale, o
        # trova meno entità e non si capisce perché.
        return re.sub(r"[ ]{2,}", " ", "\n".join(pagine).replace("\t", " "))
    return percorso.read_text(encoding="utf-8")


def riquadro(titolo: str) -> None:
    print(f"\n{'─' * 78}\n{titolo}\n{'─' * 78}")


def main() -> int:
    carica_env()
    argomenti = [a for a in sys.argv[1:] if not a.startswith("-")]
    percorso = Path(argomenti[0] if argomenti else "esempi/contratto-assunzione.txt")
    # Il secondo argomento è la scheda: `persona` (chi assumi) o `locale` (dove). La stessa
    # lettura serve tutte e due, ed è il punto: cambia la tabella, non la domanda.
    tipo = argomenti[1] if len(argomenti) > 1 else "persona"
    if not percorso.exists():
        print(f"Non trovo {percorso}", file=sys.stderr)
        return 2
    testo = leggi(percorso)

    riquadro(f"DOCUMENTO · {percorso.name} · {len(testo)} caratteri · scheda «{tipo}»")
    print(f"anonimizzatore: {pii.indirizzo()}  ({'vivo' if pii.disponibile() else 'SPENTO'})")
    cliente = modello.cliente()
    print(f"modello:        {getattr(cliente, 'modello', '—')}  "
          f"({'configurato' if not isinstance(cliente, modello.Spento) else 'SPENTO'})")

    try:
        esito = estrattore.estrai(testo, tipo, cliente=cliente)
    except pii.PiiNonDisponibile as errore:
        # Senza anonimizzatore non c'è niente da mostrare, e la traccia di uno stack non
        # spiega cosa fare. Il messaggio dice il come, non il perché tecnico.
        print(f"\nL'anonimizzatore non risponde ({errore}).")
        print(f"Atteso su {pii.indirizzo()} — avvialo, oppure cambia PII_URL nel .env.")
        print("Si scarica da https://github.com/Rizzo-AI-Academy/rizzo-pii")
        return 1
    except (lettura.LetturaIlleggibile, ValueError) as errore:
        print(f"\n{errore}")
        return 1

    riquadro("I TRE PASSAGGI")
    for passo in esito.traccia:
        tempo = f"{passo.durata_ms / 1000:5.1f} s" if passo.durata_ms else "     —"
        print(f"{tempo}  {passo.nome}\n         {passo.dettaglio}")

    riquadro("CHE DOCUMENTO È — quello che il modello ha capito senza vedere i nomi")
    print(f"  natura       {esito.tipo_documento or '—'}")
    print(f"  verso        {esito.parti.get('verso') or '—'}")
    if esito.parti.get("spiegazione"):
        print(f"  perché       {esito.parti['spiegazione']}")

    riquadro("RISULTATO")
    print(json.dumps(esito.come_dizionario(), indent=2, ensure_ascii=False))

    riquadro("COSA È USCITO DA QUESTA MACCHINA")
    if not esito.anonimizzato:
        print("Niente: il modello non è stato chiamato.")
        return 0
    print("Il testo mascherato, primi 700 caratteri — è tutto quello che ha visto il")
    print("fornitore del modello. Le parole intorno non sono dati personali, e sono")
    print("esattamente ciò che gli permette di dire chi è chi.\n")
    print(esito.anonimizzato[:700].strip())
    print("\n…")
    # La verifica, non un'illustrazione: dei valori che l'anonimizzatore aveva mascherato,
    # quanti sono rimasti nel testo uscito. Deve essere zero.
    sfuggiti = esito.valori_usciti
    print(f"\nDati personali rimasti nel testo uscito: {len(sfuggiti)}"
          + (f" — {sfuggiti}" if sfuggiti else "  ✓"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
