# Investor radar deploy

Statický web je připravený pro GitHub Pages bez buildu.

## Co web obsahuje

- prioritní investor radar se scoringem podle stage, AI/healthcare fitu a kontaktovatelnosti
- detail každého fondu, angela nebo grantového programu po kliknutí
- vyhledávání napříč fondy, angels, granty a akčním plánem
- export investorů a zdrojů do CSV
- veřejný contact intelligence dataset: e-maily, telefony, LinkedIn, Facebook, formuláře a další oficiální kanály
- stav sledovaných zdrojů včetně HTTP výsledku, změn a chyb
- týdenní automatický refresh přes GitHub Actions

## Lokální refresh dat

```bash
python3 scripts/update_data.py --skip-fetch
```

Bez `--skip-fetch` skript ověří URL v `data/sources.json`, uloží metadata do
`data/source-status.json` a přegeneruje `data/site-data.json`.

## Lokální refresh kontaktů

```bash
python3 scripts/research_contacts.py
```

Crawler ukládá veřejné profesní kontakty do `data/contact-research.json`,
`data/contact-research.csv` a `CONTACT_RESEARCH.md`. Záměrně negeneruje
domnělé osobní e-maily ani nepřidává neveřejná čísla.

## GitHub Pages

1. Nahraj celý obsah adresáře do GitHub repozitáře.
2. V repo settings zapni Pages z větve `main`, složka `/root`.
3. V Actions povol workflow `Update investor radar data`.

Workflow běží každé pondělí ráno a commituje aktualizovaná data. Když se změní
obsah sledované stránky, web ji označí štítkem `změna`.
