# Spørsmål til juristen

Gratistorget er en gratis markedsplass for privatpersoner og bedrifter, der også AI-agenter kan lese og legge ut annonser. Vilkårene og personvernerklæringen står på `/vilkar` og er et utkast. Det koden faktisk gjør med personopplysninger, er gått gjennom og rettet slik at teksten stemmer.

Det som står igjen, krever en juridisk vurdering.

## Personvern

1. **Aldersgrense.** 18 år er bare en avkrysning ved registrering. Holder det, sett opp mot personvernforordningen artikkel 8 og 13-årsgrensen i Norge?
2. **Varsler på e-post.** Varsler om nye treff på lagrede søk, og om prisfall på favoritter, er slått på fra start. Hver e-post har en lenke for å melde seg av. Krever markedsføringsloven § 15 samtykke først?
3. **E-post som ikke kan slås av.** Dette gjelder e-post om nye meldinger, handler og vurderinger. Er det greit?
4. **Stengte kontoer.** Kontoer som en moderator har stengt, beholdes med alle opplysninger uten tidsgrense. Hvilken lagringstid bør gjelde?
5. **Navn fra BankID.** Brukes innlogging med BankID, lagres hele navnet så lenge kontoen finnes, men det brukes ikke til noe. Er det nødvendig?
6. **Sletting under en sak.** Ber noen om å slette kontoen mens en rapport om dem behandles, avvises det, og de må be på nytt når saken er avgjort. Krever artikkel 17 at forespørselen holdes og utføres av seg selv?
7. **Felles samtaler.** Sletter noen kontoen, slettes også meldingene den andre har skrevet i samtalene deres. Er det riktig balanse, eller bør den slettede siden bare anonymiseres?
8. **Innsynskopien.** Den utelater:
   - hvem som har rapportert personen, og hva de skrev
   - svindelvurderingen av meldinger personen har sendt
   - vurderinger som ikke vises ennå (i inntil 14 dager)

   Er det forenlig med artikkel 15 nr. 4 og personopplysningsloven § 16?
9. **Automatiske avgjørelser.** Annonser med sterke svindelsignaler holdes tilbake til en moderator har sett på dem. Gjelder artikkel 22?
10. **Overføring utenfor EØS.** Dette gjelder SMS gjennom Twilio (USA) og AI-assistentene brukerne selv kobler til. Står serveren utenfor EU/EØS, sier installasjonsskriptet fra.
11. **Trening av KI.** `robots.txt` tillater at offentlige annonser, med selgerens visningsnavn, brukes til å trene KI-modeller. Personvernerklæringen nevner ikke det formålet.
12. **Informasjonskapselen `ft_csrf`.** Den settes ved første sidevisning for alle besøkende, også dem som aldri sender et skjema. Er den fortsatt strengt nødvendig etter ekomloven § 3-15?
13. **Personvernerklæringen og vilkårene ellers.** Dette dekker blant annet:
    - lagringstidene, for eksempel at ubrukte kontoer slettes etter to år med varsel en måned før
    - protokollen over behandlingene (artikkel 30)
    - om det trengs en vurdering av personvernkonsekvenser (DPIA, artikkel 35), siden alle meldinger sjekkes automatisk for svindel

## Handel og forbrukerrett

14. **Bedriftsselgere.** Hvem som helst kan oppgi et organisasjonsnummer. Kjøperne ser da navnet fra Enhetsregisteret, merket «oppgitt av selgeren» og med lenke til registeret. Navn som Posten, Bring, Vipps, Nav og politiet avvises. Er det nok, eller må det bekreftes at selgeren faktisk representerer bedriften, for eksempel med BankID og rollene i Enhetsregisteret?
15. **Opplysninger om den som driver siden (ehandelsloven § 8).** Siden viser navn, postadresse, eventuelt org.nr. og e-post. Er det nok? Driver en privatperson siden, må hjemmeadressen da vises?
16. **Hva som ikke kan selges.** Er listen i vilkårene dekkende?
17. **Forbrukerrettigheter.** Stemmer teksten om rettighetene ved kjøp fra bedrifter (forbrukerkjøpsloven og angrerett) og fra privatpersoner (kjøpsloven)?
