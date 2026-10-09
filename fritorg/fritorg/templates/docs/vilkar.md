# Vilkår og personvern

*Utkast. Teksten må kvalitetssikres juridisk før tjenesten lanseres.*

{% if settings.operator %}{{ site_name }} drives av {{ settings.operator }}, som er behandlingsansvarlig for personopplysningene.{% endif %}{% if settings.contact_email %} Spørsmål om personvern, innsyn eller sletting kan sendes til {{ settings.contact_email }}.{% endif %}

## Bruk av tjenesten

- Det er gratis å bruke {{ site_name }}.
{% if settings.bankid_required %}- Du lager og logger inn på kontoen med BankID. Hver person kan ha én konto.
{% elif settings.phone_verification_required %}- Du lager kontoen med e-post og passord. Før du legger ut annonser eller sender meldinger, bekrefter du et norsk mobilnummer som du selv disponerer, med en kode på SMS. Hvert nummer kan bare brukes på én konto.
{% else %}- Du lager kontoen med e-post og passord.
{% endif %}- Du er ansvarlig for annonsene og meldingene du publiserer – også når en AI-agent publiserer dem på dine vegne.
{% if settings.listing_days %}- Annonser ligger ute i {{ settings.listing_days }} dager. Deretter skjules de, og du kan gjøre dem aktive igjen på Min side.
{% endif %}{% if settings.delete_after_days %}- Annonser som ikke er aktive, for eksempel skjulte, utløpte og solgte, slettes automatisk sammen med bildene når de ikke har vært endret på {{ settings.delete_after_days|days_no }}. Du får beskjed {{ DELETION_NOTICE_DAYS|days_no }} før, på Min side og på e-post hvis du har bekreftet adressen. Gjør du annonsen aktiv igjen eller endrer den innen da, blir den ikke slettet. Annonser fra andre kilder og fra bedrifter som synkroniserer lageret sitt, følger kilden.
{% endif %}
- Etter en handel som selgeren har registrert, kan dere vurdere hverandre fra 1 til 5 med en kommentar, én gang og innen 30 dager. Vurderingen er offentlig på profilen til den som blir vurdert, med navnet ditt, tittelen på annonsen og datoen. Den vises når dere begge har vurdert, eller etter 14 dager, og kan ikke endres. Vurderinger skal være ærlige og handle om handelen. Usanne eller krenkende vurderinger kan rapporteres og fjernes av en moderator.
- Ulovlige varer og tjenester, svindel, spam og støtende innhold er ikke tillatt og blir fjernet.
- Kontoer som misbruker tjenesten, kan bli begrenset eller stengt.

## Åpne data og AI-agenter

- Annonser som er aktive eller merket som solgt, er offentlige. De kan leses, indekseres, eksporteres og brukes av mennesker, søkemotorer og AI-agenter, også via API og MCP.
- Skjulte annonser er bare synlige for deg. Meldinger er bare synlige for deg og den du skriver med.
- Innhold som lages via MCP, merkes som laget av en AI-agent.

## Personopplysninger

{% if settings.bankid_required %}- Fra BankID lagrer vi navnet ditt og tidspunktet du ble verifisert. Fødselsnummeret lagres aldri, bare en kryptografisk hash. Den brukes til å sikre at hver person har én konto.
- Vi lagrer også e-postadressen din, visningsnavnet, annonsene og meldingene dine.
- Bare visningsnavnet ditt (fornavn og forbokstav i etternavnet) vises offentlig. E-postadressen din deles aldri.
{% else %}- Vi lagrer e-postadressen din, visningsnavnet, annonsene og meldingene dine. Passordet lagres bare som en kryptografisk hash.
{% if settings.phone_verification_required %}- Mobilnummeret ditt lagres ikke i klartekst. Vi lagrer en kryptografisk hash av det, for å sikre at hvert nummer bare brukes på én konto, og de tre siste sifrene, som bare du ser. For å sende koden gir vi nummeret til SMS-leverandøren vår, som behandler det på våre vegne.
{% endif %}- Bare visningsnavnet ditt vises offentlig. E-postadressen{% if settings.phone_verification_required %} og mobilnummeret{% endif %} ditt deles aldri.
{% endif %}- Favoritter og lagrede søk er private. Selgere ser hvor mange som har lagret annonsen deres, men ikke hvem. E-post om nye treff sendes bare til en bekreftet adresse når du har slått det på, og hver e-post har en lenke for å melde seg av.
- For å stoppe svindel sjekkes annonser og meldinger automatisk for kjente svindelmønstre. Meldinger med sterke svindelsignaler og saker som er rapportert, kan bli lest av en moderator.
{% if settings.nav_import %}- **Ledige stillinger fra arbeidsplassen.no.** Stillingsannonser merket «Fra arbeidsplassen.no (Nav)» hentes fra Navs åpne stillingsfeed, som Nav lar alle publisere videre. Annonsene kan inneholde navn og kontaktopplysninger til kontaktpersoner hos arbeidsgiveren, slik arbeidsgiveren selv har publisert dem. Vi viser dem for at ledige stillinger skal være lett å finne (berettiget interesse, personvernforordningen artikkel 6 nr. 1 f). Kontaktpersonlistene fra Nav lagres ikke. Annonsene oppdateres når de endres hos Nav, og slettes hos oss så snart de er inaktive hos Nav eller visningstiden er ute. Står du i en slik annonse og vil ha opplysninger fjernet, kan du kontakte oss{% if settings.contact_email %} på {{ settings.contact_email }}{% endif %} eller arbeidsgiveren.
{% endif %}{% if settings.jobtech_import %}- **Svenske stillinger fra Platsbanken.** Stillinger merket «Fra Platsbanken (Arbetsförmedlingen, Sverige)» hentes fra Arbetsförmedlingens åpne stillingsdata (CC0) når de ligger i Norge eller krever norsk. Kontaktpersonene lagres ikke, og annonsene fjernes når de forsvinner fra Platsbanken eller søknadsfristen er ute.
{% endif %}- Vi bruker bare nødvendige informasjonskapsler: innlogging, beskyttelse av skjemaer og korte bekreftelsesmeldinger. Ingen sporing og ingen reklame.
{% if settings.delete_after_days %}- Annonsene dine lagres til du sletter dem, eller til de slettes automatisk fordi de ikke har vært aktive eller endret på {{ settings.delete_after_days|days_no }} (se over). Meldingene blir liggende også når annonsen er slettet. Du kan slette en samtale fra innboksen din, og når dere begge har slettet den, slettes den for godt, med mindre den er rapportert eller har meldinger med sterke svindelsignaler.
{% endif %}- Du kan laste ned en kopi av alt vi har lagret om deg, og slette annonsene dine og hele kontoen din selv, på [Min side]({{ base }}/min-side). Sletter du kontoen, slettes også annonsene, bildene, meldingene og vurderingene du har gitt og fått.
