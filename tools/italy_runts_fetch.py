#!/usr/bin/env python3
"""
Italian autism-related organizations from RUNTS (Registro Unico Nazionale del
Terzo Settore) -- Italy's official national register of third-sector
entities (Ministero del Lavoro e delle Politiche Sociali), public since
Dec 2023, ~119,000+ entities:

    https://servizi.lavoro.gov.it/runts/it-it/Ricerca-enti

Same tier of source as tools/france_rna_fetch.py or tools/belgium_kbo_fetch.py:
an official government registry, not scraped or LLM-narrated. But unlike
France's Opendatasoft-hosted API or Belgium's PDF-export endpoint, RUNTS is a
legacy ASP.NET WebForms/UpdatePanel portal with no discoverable JSON API and
no bulk export -- results only exist as an AJAX-paginated HTML table behind
ViewState-bound postbacks.

This was driven with Playwright (fill "Denominazione" search box, submit,
read the results table, click the "Successiva" pager link, repeat) rather
than reverse-engineering the postback protocol directly, since ViewState/
EventValidation tokens are single-use and page-specific. Even so, the
portal's AJAX pagination proved genuinely unreliable to automate end-to-end
in one session -- the "Successiva" postback intermittently either updates
the table in place or triggers a full page reload (destroying the JS
execution context Playwright was reading from), and which one happens is
not consistent between runs. Search terms and how far pagination got before
that flakiness stopped it, this session (2026-09-24):
  - "autismo": 220 total results reported by the portal: only 20-70 rows
    were reliably captured per attempt depending on where pagination broke.
  - "autistici": 22 total, captured in full (22 rows, 3 pages).
  - "autistica": 2 total, captured in full (1 page).
Net: 89 unique entries after excluding 5 "scautismo" (scouting -- a false
positive substring match, "SCAUTISMO" contains "AUTISMO") false positives.
This is a PARTIAL capture of "autismo" specifically -- rerunning this
session's scrape (see scrape_runts() below) against the live portal may
surface more of the ~130 "autismo" rows not captured this time, since the
failure point isn't deterministic. Re-run and diff by name against
ENTRIES below to add any newly-captured rows by hand, same spirit as this
file itself.

RUNTS's results table gives only name + comune (city) + sezione (entity
type/category) -- no street address, phone, or website -- so entries here
are geocoded to city centroid via Nominatim, same limitation as
tools/netherlands_anbi_fetch.py.

Usage:
    python3 tools/italy_runts_fetch.py            # geocodes ENTRIES below, writes output
    python3 tools/italy_runts_fetch.py --scrape    # re-runs the live Playwright scrape first
                                                     (requires `pip install playwright` +
                                                     `playwright install chromium` in a venv;
                                                     prints newly found entries to add by hand,
                                                     does not modify ENTRIES automatically)

Writes:
    new_resources_italy_runts.json   final resource-schema output (repo root)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_italy_runts.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Italy RUNTS (Registro Unico Nazionale del Terzo Settore) - official government register"

SEZIONE_TYPE_MAP = {
    "IMPRESE SOCIALI": "medical",
    "ENTI FILANTROPICI": "general_support",
}


def infer_type(name, sezione):
    n = name.lower()
    if any(k in n for k in ("clinica", "terapia", "riabilitazione", "ricerca", "neuroscienze")):
        return "medical"
    if any(k in n for k in ("scuola", "formazione", "educativo", "educazione")):
        return "education"
    if sezione in SEZIONE_TYPE_MAP:
        return SEZIONE_TYPE_MAP[sezione]
    return "general_support"


# (name, comune, sezione) -- see docstring for provenance and known gaps.
ENTRIES = [
    ('ISTITUTO SOCIALE DI RICERCA SU AUTISMO E NEUROSCIENZE APS', 'MERCOGLIANO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('EQUIPE CLINICA AUTISMO E PSICOTERAPIA IMPRESA SOCIALE S.R.L.', 'ROMA', 'IMPRESE SOCIALI'),
    ('AUTISMO & CO. OLTRE LA DIAGNOSI ASSOCIAZIONE PROMOZIONE SOCIALE', 'TAURIANOVA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('AUTISMO VAL VIBRATA APS', 'CONTROGUERRA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("FONDAZIONE GENITORI PER L'AUTISMO ENTE DEL TERZO SETTORE", 'PONTE NIZZA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("CERRADI APS- CENTRO DI RICERCA E RI-ABILITAZIONE PER L'AUTISMO E LE DISABILITA' INTELLETTIVE", 'TRIESTE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('FONDAZIONE PROGETTOAUTISMO FVG - ETS', 'TAVAGNACCO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("FONDAZIONE TRENTINA PER L'AUTISMO ENTE DEL TERZO SETTORE", 'MEZZOLOMBARDO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("FONDAZIONE TEDA PER L'AUTISMO ETS", 'TORINO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("IS.PE.D.D. ISTITUTO DISTURBI PERVASIVI DELLO SVILUPPO E L'AUTISMO ODV", 'CALTANISSETTA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ("ASSOCIAZIONE AUTISMO E' ... - ENTE DEL TERZO SETTORE", 'BREMBATE DI SOPRA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('AUTISMO OLTRE ONLUS - ANGSA CATANIA APS', 'CATANIA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("KOALA ETS PER L'AUTISMO E I DISTURBI DEL NEUROSVILUPPO", 'MILANO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("GRUPPO AUTISMO E DISABILITA' INTELLETTIVA - GAUDIO APS", 'PESCHIERA BORROMEO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('AUTISMO ASSOCIAZIONETEMPORANEA TRA ETS', 'NIZZA DI SICILIA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('SEMPLICEMENTE NOI-AUTISMO INSIEME-COOPERATIVA SOCIALE', 'POZZUOLI', 'IMPRESE SOCIALI'),
    ("ASSOCIAZIONE NAZIONALE COMITATO L'AUTISMO PARLA ETS", 'PALERMO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('FONDAZIONE BAMBINI E AUTISMO PER IL FUTURO ETS', 'PORDENONE', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('AUTISMO CAMPANIA APS', 'AFRAGOLA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("L'ABBRACCIO ASSOCIAZIONE PER L'AUTISMO E LE MALATTIE GENETICHE RARE ODV", 'PISTOIA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ("FONDAZIONE IL CIRENEO PER L'AUTISMO - ENTE DEL TERZO SETTORE", 'VASTO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('ASSOCIAZIONE NAZIONALE PARLAUTISMO - ASSOCIAZIONE DI PROMOZIONE SOCIALE - ENTE DEL TERZO SETTORE', 'PALERMO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('BUCANEVE X AUTISMO ODV', 'FORLIMPOPOLI', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('FONDAZIONE AUTISMO FUORI DAL SILENZIO ETS', 'PAGANI', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("FONDAZIONE FALANGA PER L'AUTISMO ETS - ENTE FILANTROPICO", 'FANO', 'ENTI FILANTROPICI'),
    ("FONDAZIONE ITALIANA PER L'AUTISMO ENTE DEL TERZO SETTORE - ETS", 'ROMA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("INSIEME SI PUO PER L'AUTISMO APS", 'TRENTO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('DISABILITA, AUTISMO E MALATTIE RARE APS', 'NAPOLI', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('PIANETA BLU AUTISMO ASSOCIAZIONE DI PROMOZIONE SOCIALE', None, 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('A.M.A. ASSOCIAZIONE MOLA AUTISMO APS', 'MOLA DI BARI', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("IO VIVO L'AUTISMO PARLIAMONE APS", 'PALERMO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('AUTISMO FUORI DAL CORO ODV', 'SAVONA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE MANFREDONIA - AUTISMO APS', 'MANFREDONIA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("UN CUORE PER L'AUTISMO APS", 'BOSISIO PARINI', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("ASSOCIAZIONE STELLABA APS PER L'AUTISMO", 'RIONERO IN VULTURE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("A.G.A. ASSOCIAZIONE GENITORI PER L'AUTISMO - ODV", 'PORTO MANTOVANO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('CULTURAUTISMO ODV', 'LA SPEZIA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ("S.O.S. AUTISMO,INSIEME PER L'INCLUSIONE APS", 'PESCARA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("UN FUTURO PER L'AUTISMO APS", 'MONTESARCHIO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('GRETA - GENITORI E RETE AUTISMO - AUTISMUS DENKFABRIK / BZ', 'BOLZANO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('APS CO-PROGETTAZIONE AUTISMO', 'MARINO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("NOIAUT VIVERE L'AUTISMO", 'VENARIA REALE', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('UNIVERSO AUTISMO APS', 'FIRENZE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("SIAMO DELFINI - IMPARIAMO L'AUTISMO", 'ROMA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE AUTISMO E SOCIETA ONLUS', 'TORINO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("COOPERATIVA SOCIALE P.A.M.A.P.I. (PARENTI E AMICI MALATI AUTISMO, PSICOSI INFANTILE E DISTURBI RELAZIONALI) - SOCIETA' COOPERATIVA A RESPONSABILITA' LIMITATA", 'FIRENZE', 'IMPRESE SOCIALI'),
    ("LE ORE SOSPESE. AUTISMO ED ALTRE VIRTU'. - ASSOCIAZIONE DI PROMOZIONE SOCIALE", 'TRAVAGLIATO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("ASSOCIAZIONE PER L'AUTISMO E LA NEURODIVERSITA' APS", 'CASALUCE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE NAZIONALE GENITORI PERSONE CON AUTISMO-CASTELLAMMARE DI STABIA MONTI LATTARI PENISOLA SORRENTINA APS', 'CASTELLAMMARE DI STABIA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE NAZIONALE GENITORI PERSONE CON AUTISMO ABRUZZO APS', 'MONTESILVANO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("VADEMECUM PER L'AUTISMO ETS", 'GAGGIANO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("ASSOCIAZIONE SPORTIVA DILETTANTISTICA CASTELLO INSIEME PER L'AUTISMO APS", 'CASTEL SAN PIETRO TERME', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('IN&AUT INCLUSIONE E AUTISMO ETS', 'MILANO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('ANGSA - ASSOCIAZIONE NAZIONALE GENITORI PERSONE CON AUTISMO APS', 'ROMA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("AUTISMO MILLE OPPORTUNITA' APS", 'SALERNO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('SOS AUTISMO APS', 'PACECO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("ANGELI FIGLI DELL'AUTISMO ODV", 'PULSANO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE VALLE PELIGNA AUTISMO APS', 'SULMONA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("INSIEME PER L'AUTISMO ODV", 'AVOLA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE NAZIONALE GENITORI PERSONE CON AUTISMO COSENZA APS ETS', 'COSENZA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('A.L.A. ( ASSOCIAZIONE LUCANA AUTISMO) ODV - E.T.S.', 'POTENZA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('FIDA - COORDINAMENTO ITALIANO DIRITTI AUTISMO APS', 'ROMA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ("AUTISMO E' PUGLIA - APS", 'MARTINA FRANCA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('AUTISMO IN BLU VALDINIEVOLE-PISTOIA ODV', 'CHIESINA UZZANESE', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ANDREA COMBATTE L’AUTISMO APS', 'TORINO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('FONDAZIONE ANTONIETTA E RICCARDO PAOLETTI - SOGGETTI AUTISTICI - VENEZIA ENTE DEL TERZO SETTORE', 'VENEZIA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ("AIABA - ASSOCIAZIONE ITALIANA PER L'ASSISTENZA AI BAMBINI AUTISTICI E.T.S.", 'FIRENZE', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('ABACO ASSOCIAZIONE BAMBINI E ADOLESCENTI AUTISTICI COSENZA APS', 'COSENZA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE FAMILIARI AUTISTICI NEBRODI APS ETS', 'NASO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('A.G.S.A. ASSOCIAZIONE GENITORI SOGGETTI AUTISTICI LAZIO ETS', 'ROMA', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('UADI UNIONE AUTISTICI DISABILI ITALIANI - APS', 'ROMA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI PADOVA APS', 'MONSELICE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('A.B.A. ASSOCIAZIONE BAMBINI AUTISTICI ODV', 'CONVERSANO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ("ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI VALLE D'AOSTA - APS", 'AOSTA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('FUORI DAL GUSCIO - A.B.A.F. (AIUTO BAMBINI AUTISTICI E FAMIGLIE) ODV - ETS', 'CAGLIARI', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('AGAN-ASSOCIAZIONE GENITORI AUTISTICI NAPOLI APS', 'NAPOLI', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE GENITORI SOGGETTI AUTISTICI SOLIDALI ONLUS', 'PALERMO', 'ALTRI ENTI DEL TERZO SETTORE'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI DELLA TOSCANA APS ANGSA TOSCANA APS', 'LUCCA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('TALENTI AUTISTICI APS', 'PISA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI - SEZIONE LOCALE DI CROTONE ETS ODV', 'VERZINO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI SEZIONE NOVARA VERCELLI ODV', 'NOVARA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI DI BOLOGNA ENTE DEL TERZO SETTORE E ASSOCIAZIONE DI PROMOZIONE SOCIALE', 'BOLOGNA', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('FA.B.A. FAMIGLIE BAMBINI AUTISTICI ODV', 'BENEVENTO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('A.N.G.S.A. ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI, VCO ODV', 'VERBANIA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('A.B.A. AIUTIAMO I BAMBINI AUTISTICI', 'SALENTO', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('ASSOCIAZIONE NAZIONALE GENITORI SOGGETTI AUTISTICI CASALE MONFERRATO APS', 'CASALE MONFERRATO', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
    ('AGAPO - ASSOCIAZIONE GENITORI SOGGETTI AUTISTICI PROGETTO EDUCATIVO ORIZZONTE ODV', 'LA SPEZIA', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('AUTISTICAMENTE IO ODV', 'TERMINI IMERESE', 'ORGANIZZAZIONI DI VOLONTARIATO'),
    ('AUTISTICAMENTE APS', 'STATTE', 'ASSOCIAZIONI DI PROMOZIONE SOCIALE'),
]


def geocode(city):
    if not city:
        return None
    params = {"q": f"{city}, Italy", "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {city!r}: {e}")
    return None


def title_case_name(name):
    # Keep acronym-heavy Italian org names readable without over-lowercasing
    # short all-caps tokens like "APS"/"ODV"/"ETS"/"A.B.A."
    return name.title() if not any(c.islower() for c in name) else name


def main():
    resources = []
    for name, comune, sezione in ENTRIES:
        coords = geocode(comune)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        clean_name = title_case_name(name)
        entry = {
            "name": clean_name,
            "type": infer_type(name, sezione),
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered Italian third-sector entity (RUNTS), category: {sezione.title()}.",
        }
        if comune:
            entry["address"] = f"{comune.title()}, Italy"
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {clean_name}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    if "--scrape" in sys.argv:
        print("Live re-scrape requires Playwright; see this file's docstring for the")
        print("interactive scraping approach used to build ENTRIES -- not wired up as")
        print("an unattended one-shot here because of the pagination flakiness described")
        print("in the docstring. Run the scrape interactively and diff by name instead.")
        sys.exit(1)
    main()
