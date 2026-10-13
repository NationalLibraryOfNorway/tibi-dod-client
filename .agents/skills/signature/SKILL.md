---
name: signature
description: Lager en signatur for noe som har blitt generert av KI, inkludert informasjon om bruker, modell og editor. Brukes for å dokumentere opprinnelsen til innholdet i både Jira-kommentarer, GitHub-kommentarer eller generisk markdown. Det er ment for å gi kontekst til lesere om hvordan innholdet ble generert.
---

## Input

- Støttede nøkler:
  - `output_format` (valgfritt, default: `markdown`):
    - bruk `JIRA` når brukeren skal lage en tekst til en JIRA-kommentar
    - bruk `GitHub` når brukeren skal lage en tekst til en GitHub-kommentar
    - bruk `markdown` når brukeren skal lage Markdown-formatert tekst
  - `full_name` (valgfritt): Navnet på personen som genererte innholdet
  - `email` (valgfritt): E-postadresse til personen. Denne prioriteres ved oppslag i `jira-users.csv`
  - `model` (valgfritt): Navnet på KI-modellen
  - `editor` (valgfritt): Navnet på verktøyet/plattformen

## Innhold

- For `output_format=JIRA` returneres et Jira ADF-fragment (`paragraph`) med `mention` når `jira_user_id` er tilgjengelig.
- Fragmentet er ment å appendes i `content` på et eksisterende ADF `doc` før innsending til Jira API.
- For øvrige formater returneres ferdig signaturstreng i tekstformat.

## Kjøring av skriptet

```
.agents/skills/signature/scripts/signature.sh output_format=<output_format> full_name="<full_name>" email="<email>" model="<model>" editor="<editor>"
```

output_format, model og editor skal alltid oppgis etter beste evne. Resten oppgis kun hvis brukeren spesifiserer det eksplisitt.


## Output

Scriptet returnerer ferdig signatur:

`🤖 Generert med KI av [bruker] med [modell] i [editor]`

For `output_format=JIRA` returneres tilsvarende innhold som ADF JSON-fragment.
