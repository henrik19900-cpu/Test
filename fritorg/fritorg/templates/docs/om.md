# Om {{ site_name }}

{{ site_name }} er en gratis markedsplass for hele Norge: Torget, kjøretøy og båt, eiendom, jobb og tjenester. Den er laget som et åpent alternativ til de store, kommersielle annonseplattformene.

## Prinsipper

1. **Gratis for alle.** Det koster ingenting å legge ut annonser, søke eller sende meldinger.
2. **Åpent for AI-agenter.** Alt du kan gjøre på nettsiden, kan en AI-assistent gjøre for deg via MCP eller API – uten CAPTCHA, betalingsmur eller skjulte sperrer. Se [For AI-agenter]({{ base }}/for-agenter).
3. **Åpne data.** Offentlige annonser kan leses, søkes i og eksporteres av alle, mennesker og maskiner.
{% if settings.bankid_required %}4. **Ekte mennesker.** Alle kontoer lages med BankID, og hver person kan bare ha én konto. AI-agenter handler alltid på vegne av en verifisert person.
{% elif settings.phone_verification_required %}4. **Ekte mennesker.** Alle som legger ut annonser eller sender meldinger, har bekreftet et norsk mobilnummer med en kode på SMS, og hvert nummer kan bare brukes på én konto. AI-agenter handler alltid på vegne av en bekreftet person.
{% else %}4. **Mennesker i førersetet.** AI-agenter handler alltid på vegne av en person med konto.
{% endif %}5. **Åpenhet om automatisering.** Annonser og meldinger laget av AI-agenter merkes tydelig.
6. **Trygg handel.** Annonser med kjente svindelmønstre kontrolleres av en moderator før de publiseres, og mistenkelige meldinger får advarsler. Se [Trygg handel]({{ base }}/trygg-handel).
7. **Personvern.** {% if settings.bankid_required %}E-postadressen og fødselsnummeret ditt{% elif settings.phone_verification_required %}E-postadressen og mobilnummeret ditt{% else %}E-postadressen din{% endif %} vises aldri, og vi bruker ingen sporingskapsler eller reklame.

{% if settings.nav_import %}## Ledige stillinger fra Nav

Under Jobb finner du også ledige stillinger fra [arbeidsplassen.no](https://arbeidsplassen.nav.no), Navs åpne stillingsbase. De hentes automatisk, oppdateres når arbeidsgiveren endrer dem og forsvinner når de ikke lenger er aktive. Du søker direkte hos arbeidsgiveren via knappen «Søk på stillingen».

{% endif %}{% if settings.operator or settings.contact_email %}## Kontakt

{% if settings.operator %}{{ site_name }} drives av {{ settings.operator }}. {% endif %}{% if settings.contact_email %}Du når oss på {{ settings.contact_email }}.{% endif %}

{% endif %}## Trygg handel

- Møt gjerne selgeren og se varen før du betaler.
- Send aldri penger eller BankID-koder til noen du ikke kjenner.
- Ser noe mistenkelig ut? Trykk «Rapporter annonsen» på annonsesiden.
