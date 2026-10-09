# Hjelp

Svar på det folk lurer mest på. Finner du ikke svaret{% if settings.contact_email %}, skriv til {{ settings.contact_email }}{% else %}, ta kontakt med oss{% endif %}.

## Kom i gang

### Hva koster det?

Ingenting. Det er gratis å legge ut annonser, søke, lagre favoritter og sende meldinger. {{ site_name }} har ikke reklame og selger ikke opplysninger om deg.

### Hvordan legger jeg ut en annonse?

Trykk på **Ny annonse**, velg kategori og fyll ut skjemaet. Legg gjerne ved bilder: annonser med bilder får mye mer oppmerksomhet. Annonsen ligger ute i {{ settings.listing_days or 60 }} dager, og du kan fornye den med ett klikk.

{% if settings.bankid_required %}### Hvorfor må jeg logge inn med BankID?

Alle kontoer er knyttet til en ekte person, og hver person kan bare ha én konto. Det gjør det mye vanskeligere å svindle. Fødselsnummeret ditt lagres aldri.
{% elif settings.phone_verification_required %}### Hvorfor må jeg bekrefte mobilnummeret?

Før du legger ut annonser eller sender meldinger, bekrefter du et norsk mobilnummer med en kode på SMS. Hvert nummer kan bare brukes på én konto, og det gjør det mye vanskeligere å lage falske kontoer. Nummeret vises aldri for andre, og vi lagrer det ikke i klartekst. {{ site_name }} ringer deg aldri og spør aldri om koden.

Er nummeret allerede brukt på en annen konto, får du en SMS om det i stedet for en kode. Da logger du inn med den kontoen.
{% endif %}
### Jeg har glemt passordet

Bruk «Glemt passordet?» på innloggingssiden. Du får en lenke på e-post{% if settings.phone_verification_required %} eller en kode på SMS til nummeret du har bekreftet{% endif %}.

Etter 10 feil passord på et kvarter stenges innloggingen for kontoen en liten stund, så ingen kan prøve seg fram. Med «Glemt passordet?» kommer du likevel inn med en gang.

## Kjøpe

### Hvordan kontakter jeg selgeren?

Skriv en melding på annonsen. Samtalen havner under **Meldinger**, og selgeren ser aldri e-postadressen{% if settings.phone_verification_required %} eller mobilnummeret{% endif %} ditt. Stillinger fra andre kilder søker du på hos arbeidsgiveren, med knappen i annonsen.

### Hvordan lagrer jeg en annonse?

Trykk på hjertet. Annonsen havner under **Favoritter**. Settes prisen ned, ser du den gamle prisen der, og har du bekreftet e-postadressen, får du beskjed på e-post.

### Kan jeg få beskjed når det kommer noe nytt?

Ja. Søk etter det du vil ha, for eksempel en barnesykkel i ditt fylke, og trykk på **Lagre søket**. Under **Lagrede søk** ser du hvor mange nye annonser som har kommet siden sist. Med bekreftet e-postadresse får du dem også på e-post, høyst én gang i timen per søk.

### Hvordan unngår jeg å bli svindlet?

Se varen før du betaler, hold samtalen på {{ site_name }}, og oppgi aldri kortnummer, BankID eller koder for å *motta* penger. Les mer under [Trygg handel]({{ base }}/trygg-handel).

## Selge

### Hvordan merker jeg annonsen som solgt?

Åpne annonsen og trykk **Merk som solgt** (eller «gitt bort», «utleid» og så videre). Du finner også knappene under **Min side**.

### Hva skjer med gamle annonser?

{% if settings.listing_days %}Etter {{ settings.listing_days }} dager skjules annonsen, og du kan gjøre den aktiv igjen med ett klikk. {% endif %}{% if settings.delete_after_days %}Annonser som ikke har vært aktive eller endret på {{ settings.delete_after_days|days_no }}, slettes automatisk med bildene. {{ DELETION_NOTICE_DAYS|days_no|capitalize }} før står det på **Min side**, og har du bekreftet e-postadressen, får du beskjed på e-post. Vil du beholde annonsen, gjør du den aktiv igjen eller endrer den.{% else %}Skjulte og solgte annonser blir liggende til du sletter dem.{% endif %}

### Hvordan fungerer vurderinger?

Når dere er enige om en handel, trykker selgeren **Solgt til …** i samtalen. Da blir annonsen merket som solgt, og dere kan gi hverandre en vurdering fra 1 til 5 med en kort kommentar, innen 30 dager. Vurderingene vises på profilen når dere begge har vurdert, eller etter 14 dager, så ingen kan svare på en vurdering de har lest. En vurdering kan ikke endres. Er en vurdering usann eller krenkende, kan du rapportere den på profilen.

### Hvorfor er annonsen min «til kontroll»?

Noen annonser ligner på dem svindlere bruker, for eksempel med krav om depositum før visning eller betalingslenker. Da sjekker en moderator annonsen før den blir synlig. Det betyr ikke at vi tror du er en svindler. Grunnen står på annonsen.

### En moderator har fjernet annonsen min. Kan jeg klage?

Ja. Begrunnelsen står på annonsen. Mener du at den er feil, åpner du annonsen og velger **Klag på avgjørelsen**. En moderator ser på saken på nytt og svarer deg på e-post. Du kan klage én gang per avgjørelse.

### Hvor mange har sett annonsen min?

Det står på annonsen og under **Min side**, sammen med hvor mange som har lagret den.

### Jeg er en bedrift med mange annonser

Du kan holde hele lageret oppdatert automatisk fra ditt eget system. Se [For bedrifter]({{ base }}/for-bedrifter).

## Meldinger

### Kan jeg slette en samtale?

Ja. Åpne samtalen og velg **Slett samtalen**. Den andre beholder sin kopi, og skriver en av dere igjen, kommer samtalen tilbake. Når dere begge har slettet den, slettes den for godt.

### Noen plager meg. Hva gjør jeg?

Åpne samtalen og velg **Blokker**. Da kan dere ikke sende meldinger til hverandre, og personen får ikke beskjed. Er det svindel eller trusler, bør du også **rapportere** samtalen, så ser en moderator på den.

## AI-assistenter

### Kan jeg bruke {{ site_name }} med ChatGPT, Claude eller andre assistenter?

Ja. Assistenten kan søke, følge med på nye annonser og legge ut annonser for deg. Alt den lager, merkes som «via AI-agent». Se [Koble til din AI-assistent]({{ base }}/for-agenter).

## Personvern og konto

### Hva lagrer dere om meg?

Bare det som trengs for å drive tjenesten. Under **Min side** kan du laste ned alt vi har lagret om deg. Les mer i [vilkårene]({{ base }}/vilkar).

### Hvordan sletter jeg kontoen min?

Under **Min side**, nederst. Annonsene, bildene og meldingene dine slettes for godt.
