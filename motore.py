# Backward-compatible re-exports — engine lives in battaglia_navale.py
from battaglia_navale import (  # noqa: F401
    ACQUA,
    COLONNE,
    COLPITO,
    DIMENSIONE_GRIGLIA,
    LUNGHEZZE_NAVI,
    MANCATO,
    NAVE,
    POTERI_TIPI,
    Partita,
    Tavola,
    celle_nave,
    coordinate_label,
    parse_coordinata,
    piazzamento_casuale,
    piazzamento_valido,
)
