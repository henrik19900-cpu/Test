# For bedrifter

Bilforhandlere, meglere, butikker, auksjonshus og arbeidsgivere kan legge ut annonsene sine på {{ site_name }} gratis, rett fra sitt eget system. Annonsene holdes oppdatert automatisk: nye kommer til, endringer kommer med, og det som er solgt eller borte, forsvinner.

## Slik kommer dere i gang

1. Lag en gratis konto på [{{ base }}/registrer]({{ base }}/registrer){% if settings.phone_verification_required %} og bekreft et norsk mobilnummer{% endif %}.
2. Lag en API-nøkkel på [Min side]({{ base }}/min-side).
3. Send hele lageret i ett kall, så ofte dere vil (for eksempel hver time):

        curl -X PUT {{ base }}/api/v1/me/feeds/bruktbiler \
          -H "Authorization: Bearer DIN_NØKKEL" \
          -H "Content-Type: application/json" \
          -d '{"listings": [{"external_id": "BIL-1001", "category": "bil", "title": "Volvo V60 D4 2019", "description": "Pent brukt, full servicehistorikk.", "price": 239000, "county": "oslo", "location": "Oslo", "attributes": {"make": "Volvo", "model": "V60", "year": 2019, "mileage_km": 85000, "fuel": "diesel"}}]}'

`external_id` er deres egen id for varen (lagernummer, annonsenummer eller varenummer). Svaret viser hvor mange annonser som ble laget, endret, uendret og fjernet, og {{ site_name }}-id-en til hver annonse. Bilder lastes opp til nye annonser med `POST {{ base }}/api/v1/listings/{id}/images`.

- Navnet i adressen (her `bruktbiler`) er en feed. Dere kan ha flere, for eksempel én per avdeling.
- Varer som ikke lenger er med i listen, slettes. Vil dere bare legge til eller endre, sender dere `"remove_missing": false`.
- En konto kan ha opptil {{ settings.max_synced_listings }} synkroniserte annonser, og maks 1000 per kall.
- Kategorier og felt per kategori: [{{ base }}/api/v1/categories]({{ base }}/api/v1/categories). Hele API-et: [{{ base }}/api/docs]({{ base }}/api/docs).

## Regler

- Dere må ha rett til tekstene og bildene dere sender, også bilder tatt av en fotograf.
- Annonsene følger de samme reglene som alle andre: de sjekkes automatisk for svindel, kan rapporteres og kan fjernes av en moderator.
- Kjøpere kontakter dere med meldinger på {{ site_name }}. Med bekreftet e-postadresse får dere varsel om nye meldinger.
- Synkroniserte annonser holdes aktive så lenge dere synkroniserer. Stopper synkroniseringen, går de ut etter {{ settings.listing_days }} dager.

Spørsmål eller behov for større grenser?{% if settings.contact_email %} Skriv til {{ settings.contact_email }}.{% else %} Ta kontakt med oss.{% endif %}
