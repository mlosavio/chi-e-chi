"""Che cosa si vuole tirare fuori, e a quale **tipo** di entità corrisponde.

Due tabelle, e la seconda è quella interessante.

`CAMPI` dice cosa chiedere: è la lista che finisce nella domanda al modello, e cambiarla
qui cambia il prompt — non c'è una seconda copia da tenere allineata.

`ETICHETTE_AMMESSE` dice **quale tipo di entità può finire in quale campo**, e serve a
rendere innocuo un errore di attribuzione. Alla domanda «quale segnaposto è la via di
residenza» un modello può rispondere `[ORG_1]`: nel campo «via» comparirebbe «Da Nicola
S.r.l.», che *sembra* un dato — è il nome giusto, nel posto sbagliato — e nessuno lo
rilegge. Ma il rilevatore aveva **già deciso** che `[ORG_1]` è un'organizzazione, e quella
decisione viene da un modello addestrato a riconoscere tipi.

Il modello linguistico sceglie **quale** segnaposto; non decide **che cosa sia**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Campo:
    nome: str
    descrizione: str


CAMPI: tuple[Campo, ...] = (
    Campo("cognome", "il cognome del lavoratore, come sul documento"),
    Campo("nome", "il nome proprio del lavoratore"),
    Campo("codice_fiscale", "sedici caratteri, senza spazi, maiuscolo"),
    Campo("data_nascita", "in formato AAAA-MM-GG"),
    Campo("via", "via e numero civico della residenza del lavoratore"),
    Campo("cap", "cinque cifre"),
    Campo("citta", "il comune di residenza del lavoratore"),
    Campo("provincia", "la sigla di due lettere, per esempio BA"),
    Campo("email", "l'indirizzo di posta del lavoratore"),
    Campo("telefono", "il recapito telefonico del lavoratore"),
    Campo("datore", "la ragione sociale di chi assume"),
    Campo("data_assunzione", "la data di inizio del rapporto, AAAA-MM-GG"),
    Campo("tipo_contratto", "indeterminato, determinato, apprendistato, stagionale"),
    Campo("mansione", "il mestiere per cui è assunto"),
    Campo("monte_ore_settimanale", "le ore settimanali previste, solo il numero"),
)

NOMI = {c.nome for c in CAMPI}


def elenco() -> str:
    return "\n".join(f"- {c.nome}: {c.descrizione}" for c in CAMPI)


ETICHETTE_AMMESSE: dict[str, set[str]] = {
    "via": {"STREET", "BUILDINGNUM"},
    "cap": {"ZIPCODE"},
    "citta": {"CITY"},
    "provincia": {"PROVINCE", "CITY"},
    "email": {"EMAIL"},
    "telefono": {"TELEPHONENUM"},
    "codice_fiscale": {"CF"},
    "data_nascita": {"DATE"},
    "data_assunzione": {"DATE"},
    "datore": {"ORG"},
    "nome_completo": {"FULLNAME"},
}
"""Campo → tipi di entità che ci possono finire.

I campi che non compaiono qui — `mansione`, `tipo_contratto`, `monte_ore_settimanale` — non
sono dati personali: il rilevatore non li maschera, il modello li riporta in chiaro, e non
c'è nessun tipo da confrontare. È anche il motivo per cui si possono estrarre **senza che
esca niente**: non erano mai stati mascherati perché non identificano nessuno.
"""


SEGNAPOSTO = re.compile(r"\[([A-Z_]+?)_\d+\]")


def tipo_compatibile(campo: str, risposta: str, etichetta_di=None) -> bool:
    """La risposta del modello è del tipo giusto per questo campo?

    Una risposta può contenere **più di un segnaposto**: «via e numero civico» sono due
    entità distinte per il rilevatore — `[STREET_2] [BUILDINGNUM_2]` — e unirle è la cosa
    corretta da fare. Si controllano tutti quelli che ci sono, e devono essere tutti
    ammessi: guardare solo il primo lascerebbe passare `[STREET_2] [ORG_1]`.
    """
    del etichetta_di          # l'etichetta sta nel segnaposto: non serve chiederla a nessuno
    ammesse = ETICHETTE_AMMESSE.get(campo)
    etichette = set(SEGNAPOSTO.findall(str(risposta or "")))
    # Nessun segnaposto (risposta in chiaro) o campo senza regola: passa, e più avanti c'è
    # comunque la validazione del dominio.
    if not etichette or ammesse is None:
        return True
    return etichette <= ammesse
