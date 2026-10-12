# Vilkår og personvern

*Utkast. Teksten må kvalitetssikres juridisk før tjenesten lanseres.*

{{ site_name }} drives av {{ settings.operator or "driftsansvarlig for " ~ site_name }}, som er behandlingsansvarlig for personopplysningene. {% if settings.contact_email %}Spørsmål om personvern, innsyn og sletting sendes til {{ settings.contact_email }}.{% else %}Kontaktadressen for personvern er ikke satt opp ennå.{% endif %}

## Bruk av tjenesten

- Det er gratis å bruke {{ site_name }}. Du må være minst 18 år for å lage en konto.
{% if settings.bankid_required %}- Du lager og logger inn på kontoen med BankID. Hver person kan ha én konto.
{% elif settings.phone_verification_required %}- Du lager kontoen med e-post og passord. Før du legger ut annonser eller sender meldinger, bekrefter du et norsk mobilnummer som du selv disponerer, med en kode på SMS. Hvert nummer kan bare brukes på én konto.
{% else %}- Du lager kontoen med e-post og passord.
{% endif %}- Du er ansvarlig for annonsene og meldingene du publiserer – også når en AI-agent publiserer dem på dine vegne.
{% if settings.listing_days %}- Annonser ligger ute i {{ settings.listing_days }} dager. Deretter skjules de, og du kan gjøre dem aktive igjen på Min side.
{% endif %}{% if settings.delete_after_days %}- Annonser som ikke er aktive, for eksempel skjulte, utløpte og solgte, slettes automatisk sammen med bildene når de ikke har vært endret på {{ settings.delete_after_days|days_no }}. Du får beskjed {{ DELETION_NOTICE_DAYS|days_no }} før, på Min side og på e-post hvis du har bekreftet adressen. Gjør du annonsen aktiv igjen eller endrer den innen da, blir den ikke slettet. Annonser fra andre kilder og fra bedrifter som synkroniserer lageret sitt, følger kilden.
{% endif %}
- Etter en handel som selgeren har registrert, kan dere vurdere hverandre fra 1 til 5 med en kommentar, én gang og innen 14 dager. Bare de to som var med på handelen, kan vurdere den, så vurderingene kommer fra ekte handler. De sjekkes ikke før de vises. Vurderingen er offentlig på profilen til den som blir vurdert, med navnet ditt, tittelen på annonsen og datoen. Den vises når dere begge har vurdert, eller når fristen er ute, og kan ikke endres. Vurderinger skal være ærlige og handle om handelen. Usanne eller krenkende vurderinger kan rapporteres og fjernes av en moderator.
- Det du legger ut, må være lov å selge, og du må ha rett til bildene og teksten (se under). Svindel, spam og støtende innhold er ikke tillatt og blir fjernet.
- Kontoer som misbruker tjenesten, kan bli begrenset eller stengt.
- Fjerner en moderator annonsen din, får du en begrunnelse på annonsen og på e-post. Mener du at avgjørelsen er feil, kan du klage én gang på annonsen. En moderator ser på saken på nytt og publiserer annonsen igjen eller forklarer hvorfor den forblir fjernet.{% if settings.contact_email %} Er kontoen din stengt, kan du klage til {{ settings.contact_email }}.{% endif %}

## Dette kan du ikke legge ut

Alt som er ulovlig å selge eller formidle i Norge, er ikke tillatt. Det gjelder blant annet:

- **Narkotika, dopingmidler og legemidler**, også reseptfrie.
- **Alkohol**. Tomme flasker og emballasje går bra.
- **Tobakk, snus og nikotinprodukter**, også e-sigaretter.
- **Våpen som krever tillatelse**, våpendeler og ammunisjon, og våpen som er forbudt å eie, som pepperspray, batonger, slagringer og springkniver.
- **Fyrverkeri og eksplosiver.**
- **Stjålne varer**, og ting du ikke eier eller har rett til å selge.
- **Kopivarer og piratkopier**: falske merkevarer og kopier av filmer, spill, musikk og programvare.
- **ID-dokumenter, bankkort, BankID og kontoer**, ekte eller falske, og opplysninger om andre personer.
- **Seksuelle tjenester.**
- **Lotterier, pengespill og pyramidespill.**
- **Farlige og tilbakekalte produkter.**
- **Dyr som ikke selges i tråd med dyrevelferdsloven.** Valper og kattunger kan ikke selges før de er 8 uker, og ville dyr og fredede arter kan ikke selges.

Annonser som ser ut til å gjelde noe av dette, kontrolleres av en moderator før de blir synlige. Rapporter gjerne annonser som bryter reglene.

## Bedrifter og privatpersoner

- Selger du som bedrift, også som enkeltpersonforetak, må du registrere organisasjonsnummeret på Min side. Annonsene dine merkes da **Bedrift**, med navnet bedriften har i Enhetsregisteret. Det er påkrevd for å synkronisere et lager.
- Kjøper du som privatperson fra en bedrift, gjelder forbrukerkjøpsloven, og som regel har du 14 dagers angrerett når dere ikke møtes for å handle. Kjøper du fra en privatperson, gjelder kjøpsloven, og angrerett har du ikke.
- Opplysningen om bedriften er selgerens egen. Vi sjekker at organisasjonsnummeret finnes i Enhetsregisteret, og lenker dit, så du kan se hvem bedriften er.
- Avtalen om en handel inngås mellom kjøper og selger. {{ site_name }} er ikke part i handelen og har ikke ansvar for at den blir gjennomført.

## Bilder og tekst

- Bruk bare bilder og tekst du har laget selv, eller som du har lov til å bruke. Ikke kopier bilder fra nettbutikker, produsenter eller andres annonser.
- Du beholder rettighetene til det du legger ut. Ved å publisere gir du {{ site_name }} lov til å lagre, vise og dele annonsen gratis, også via API, MCP, eksport, søkemotorer og AI-agenter, så lenge den er publisert.
- Mener du at en annonse bruker bilder eller tekst du har rettighetene til, kan du rapportere annonsen med grunnen «Bruker mine bilder eller min tekst»{% if settings.contact_email %} eller skrive til {{ settings.contact_email }}{% endif %}. Innhold som krenker andres rettigheter, fjernes.

## Slik sorteres annonsene

- Uten søkeord kommer de nyeste annonsene først.
- Med søkeord kommer først annonsene der alle ordene står i tittelen, kategorien, stedet eller egenskapene, nyeste først. Deretter kommer resten.
- Du kan også sortere på pris eller dato. Ingen kan betale for å komme høyere opp, og siden har ingen reklame.

## Åpne data og AI-agenter

- Annonser som er aktive eller merket som solgt, er offentlige. De kan leses, indekseres, eksporteres og brukes av mennesker, søkemotorer og AI-agenter, også via API og MCP.
- Skjulte annonser er bare synlige for deg og moderatorene. Meldinger er bare synlige for deg og den du skriver med.
- Innhold som lages via MCP, merkes som laget av en AI-agent.

## Personopplysninger

### Hva vi bruker opplysningene til, og hvorfor vi har lov

- **For å levere tjenesten** (avtalen med deg, personvernforordningen artikkel 6 nr. 1 b): kontoen din, annonsene, meldingene, handlene og vurderingene, favorittene, de lagrede søkene og varslene.
- **For å holde tjenesten trygg** (berettiget interesse, artikkel 6 nr. 1 f): bekreftelse av mobilnummeret, automatisk svindelkontroll, rapporter, moderering, logger og sikkerhetskopier.
- **For å gjøre annonsene lette å finne** (berettiget interesse): offentlige annonser, profiler og vurderinger kan også leses via API, MCP, eksport og søkemotorer. Kopier som andre allerede har hentet, kan vi ikke slette.
- Annonser og meldinger med sterke svindelsignaler holdes automatisk tilbake til en moderator har sett på dem. Det er alltid et menneske som fjerner annonser og stenger kontoer.

### Hva vi lagrer

{% if settings.bankid_required %}- Fra BankID lagrer vi navnet ditt og tidspunktet du ble verifisert. Fødselsnummeret lagres aldri. Vi lagrer en nøkkelbasert hash av identifikatoren fra BankID-leverandøren, som brukes til å sikre at hver person har én konto.
- Vi lagrer også e-postadressen din, visningsnavnet, annonsene og meldingene dine.
- Bare visningsnavnet ditt (fornavn og forbokstav i etternavnet) vises offentlig. E-postadressen din deles aldri.
{% else %}- Vi lagrer e-postadressen din, visningsnavnet, annonsene og meldingene dine. Passordet lagres bare som en kryptografisk hash.
{% if settings.phone_verification_required %}- Mobilnummeret ditt lagres ikke i klartekst. Vi lagrer en kryptografisk hash av det, for å sikre at hvert nummer bare brukes på én konto, og de tre siste sifrene, som bare du ser. For å sende koden gir vi nummeret til SMS-leverandøren vår, som behandler det på våre vegne.
{% endif %}- Bare visningsnavnet ditt vises offentlig. E-postadressen{% if settings.phone_verification_required %} og mobilnummeret{% endif %} ditt deles aldri.
{% endif %}- Profilen din viser visningsnavnet, når du ble medlem, om kontoen er bekreftet, annonsene dine, hvor raskt du pleier å svare, og vurderingene du har fått, med navnet til den som skrev dem.
- Ikke del sensitive opplysninger om deg selv eller andre i annonser og meldinger, for eksempel om helse, religion, politisk syn, seksuell orientering, etnisitet eller lovbrudd, og ikke opplysninger om eller bilder av barn.
- Selger du som bedrift, lagrer vi organisasjonsnummeret og navnet fra Enhetsregisteret. De vises på annonsene og profilen din.
- Favoritter og lagrede søk er private. Selgere ser hvor mange som har lagret annonsen deres, men ikke hvem. Har du bekreftet e-postadressen, får du e-post om nye treff på søkene du lagrer, og når prisen settes ned på en favoritt. Det er slått på fra start. Du slår det av for hvert søk under Lagrede søk og for favorittene under Favoritter, og hver slik e-post har en lenke for å melde seg av.
- For å stoppe svindel sjekkes annonser og meldinger automatisk for kjente svindelmønstre. Meldinger med sterke svindelsignaler og saker som er rapportert, kan bli lest av en moderator.
{% if settings.nav_import %}- **Ledige stillinger fra arbeidsplassen.no.** Stillingsannonser merket «Fra arbeidsplassen.no (Nav)» hentes fra Navs åpne stillingsfeed, som Nav lar alle publisere videre. Annonsene kan inneholde navn og kontaktopplysninger til kontaktpersoner hos arbeidsgiveren, slik arbeidsgiveren selv har publisert dem. Vi viser dem for at ledige stillinger skal være lett å finne (berettiget interesse, personvernforordningen artikkel 6 nr. 1 f). Kontaktpersonlistene fra Nav lagres ikke. Annonsene oppdateres når de endres hos Nav, og slettes hos oss så snart de er inaktive hos Nav eller visningstiden er ute. Står du i en slik annonse og vil ha opplysninger fjernet, kan du kontakte oss{% if settings.contact_email %} på {{ settings.contact_email }}{% endif %} eller arbeidsgiveren.
{% endif %}{% if settings.jobtech_import %}- **Svenske stillinger fra Platsbanken.** Stillinger merket «Fra Platsbanken (Arbetsförmedlingen, Sverige)» hentes fra Arbetsförmedlingens åpne stillingsdata (CC0) når de ligger i Norge eller krever norsk. Kontaktpersonene lagres ikke, og annonsene fjernes når de forsvinner fra Platsbanken eller søknadsfristen er ute.
{% endif %}- Vi bruker bare informasjonskapsler som trengs for at tjenesten skal virke, ingen for sporing eller reklame. `ft_csrf` beskytter skjemaene mot at andre nettsider sender dem i ditt navn, og slettes når du lukker nettleseren. `ft_session` holder deg innlogget i 30 dager, eller til du logger ut. `ft_flash` viser en kort bekreftelse etter noe du har gjort, og slettes etter ett minutt.{% if settings.bankid_required %} `ft_pending` husker BankID-innloggingen mens du lager kontoen, i inntil 30 minutter.{% endif %}
- Serveren logger IP-adresse, tidspunkt, hvilken side som ble besøkt og det nettleseren sender med, som nettlesertype og språk, for drift og sikkerhet. Nøkler, engangslenker og e-postadresser tas ikke med i loggen.
- For å stoppe misbruk teller vi forespørsler per IP-adresse og feil passord per e-postadresse. Det skjer bare i minnet, og tellingen glemmes etter inntil en time.

### Hvem som behandler opplysningene

- {% if settings.processors %}Disse leverandørene behandler opplysninger på våre vegne, etter databehandleravtaler: {{ settings.processors }}.{% else %}Vi bruker leverandører for servere{% if settings.bankid_required %}, innlogging med BankID{% elif settings.phone_verification_required %}, SMS{% endif %} og e-post. De behandler opplysninger på våre vegne, etter databehandleravtaler.{% endif %}{% if settings.phone_verification_required and settings.sms_provider == "twilio" %} SMS-kodene sendes gjennom Twilio, et selskap med base i USA. Overføringen bygger på EU-kommisjonens standardavtaler og EU–US Data Privacy Framework.{% endif %}
- Kobler du en AI-assistent til kontoen din, får selskapet bak assistenten det den leser og skriver for deg, også meldinger andre sender deg. Det selskapet er ikke vår databehandler: du velger selv å bruke det, og du kan trekke tilgangen tilbake på Min side.
- Vi selger aldri opplysninger og deler dem ikke med noen andre, med mindre loven krever det.

### Hvor lenge vi lagrer

{% if settings.delete_after_days %}- Annonsene dine lagres til du sletter dem, eller til de slettes automatisk fordi de ikke har vært aktive eller endret på {{ settings.delete_after_days|days_no }} (se over). Meldingene blir liggende også når annonsen er slettet.
{% else %}- Annonsene og meldingene dine lagres til du sletter dem.
{% endif %}- Du kan slette en samtale fra innboksen din. Når dere begge har slettet den, slettes den for godt, men ikke så lenge en rapport om den er åpen, i 90 dager hvis en melding i den har sterke svindelsignaler, og så lenge handelen dere registrerte i den kan vurderes.
{% if settings.inactive_account_days %}- Kontoer som ikke har vært brukt på {{ settings.inactive_account_days|days_no }}, slettes automatisk med alt som hører til. En måned før får du beskjed på e-post hvis du har bekreftet adressen. Logger du inn, eller bruker du kontoen med en AI-assistent, blir den ikke slettet. Behandler en moderator en rapport om deg eller annonsene dine, venter slettingen til saken er avgjort. Kontoer som en moderator har stengt, slettes ikke på denne måten.
{% endif %}- Innlogging på nettsiden varer i 30 dager. Koder for bekreftelse og nytt passord slettes etter inntil to døgn. Lenkene vi sender på e-post, lagres ikke hos oss, og slutter å virke etter en time (nytt passord) eller tre døgn (bekreftelse av e-postadressen).
- En nøkkel som en AI-assistent har fått ved å logge inn på kontoen din (MCP-innlogging), slettes når den ikke har vært brukt på 90 dager. Andre nøkler varer til du sletter dem på Min side.
- Tilgangsloggen slettes etter 14 dager og sikkerhetskopier etter 30 dager. Må vi legge tilbake en sikkerhetskopi, slettes kontoer som er slettet etter at kopien ble tatt, på nytt. For å få til det husker vi i 60 dager at en konto er slettet: bare nummeret den hadde, og når den ble laget og slettet.
- Rapporter som er avgjort, moderatorenes beslutninger og vurderinger en moderator har fjernet, slettes etter ett år.

### Rettighetene dine

- Du har rett til innsyn, retting, sletting, begrensning, dataportabilitet og til å protestere mot behandlingen. Det meste gjør du selv på [Min side]({{ base }}/min-side): laste ned en kopi av opplysningene, endre visningsnavn og e-post, og slette annonsene og hele kontoen.
- Sletter du kontoen, slettes også annonsene, bildene, meldingene, samtalene (også for den du skrev med) og vurderingene du har gitt og fått. Moderatorenes notater om deg fjernes. At en beslutning ble tatt, og rapporter du har sendt om andre, beholdes uten navnet ditt i inntil ett år. Behandler en moderator en rapport om deg eller annonsene dine, kan du slette kontoen når saken er avgjort.
- Står du i en annonse eller på et bilde, kan du rapportere annonsen med grunnen «Personopplysninger om meg»{% if settings.contact_email %}, eller skrive til {{ settings.contact_email }}{% endif %}. Det kan du også gjøre hvis kontoen din er stengt.
- Mener du at vi behandler opplysningene dine i strid med regelverket, kan du klage til [Datatilsynet](https://www.datatilsynet.no/).
