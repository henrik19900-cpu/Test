# Trygg handel

De fleste handler trygt på {{ site_name }}. Svindlere bruker likevel de samme triksene om og om igjen. Kjenner du dem, er du godt beskyttet.

## Varselsignaler

- **«Motta pengene her»-lenker.** Du skal aldri oppgi kortnummer, BankID eller koder for å *motta* penger. Lenker som later som de kommer fra Posten, Bring, Vipps eller {{ site_name }}, er svindel.
- **Forskudd og depositum før visning.** Betal aldri depositum for en bolig du ikke har sett, og aldri til en «utleier» som er i utlandet og vil sende nøklene i posten.
- **Uvanlige betalingsmåter.** Gavekort, kryptovaluta, Western Union og MoneyGram brukes nesten bare av svindlere.
- **Flytting av samtalen.** Svindlere vil gjerne over på WhatsApp, Telegram eller e-post, der de er vanskeligere å spore.
- **For godt til å være sant.** En nesten ny bil eller en sentral leilighet langt under vanlig pris er et klassisk lokkemiddel.
- **Tidspress.** «Første som betaler får den» og «må selges i dag» skal få deg til å handle før du tenker deg om.
- **Jobb som «finansagent».** Å motta og videresende penger eller pakker for andre er hvitvasking, og du kan bli straffet.

## Slik beskytter {{ site_name }} deg

- **BankID.** Alle kontoer er knyttet til en person som har logget inn med BankID, og hver person kan bare ha én konto. Visningsnavnet kommer fra BankID.
- **Automatisk kontroll.** Annonser med kjente svindelmønstre blir sjekket av en moderator før de blir synlige.
- **Varsler i meldinger.** Meldinger med betalingslenker, forespørsler om koder og lignende får en tydelig advarsel.
- **Stjålne bilder og kopiert tekst** fra andre selgere oppdages automatisk.
- **Nye kontoer** kan legge ut færre annonser og sende færre meldinger det første døgnet.
- **Rapportering.** Rapporterer flere brukere samme annonse, skjules den til den er kontrollert.
- **Merking.** Annonser og meldinger laget av en AI-agent merkes, så du vet hvem du snakker med.

## Gode vaner

1. Hold samtalen på {{ site_name }}.
2. Møt selgeren og se varen før du betaler, gjerne et sted med andre folk.
3. Betal med Vipps eller kontant når du får varen. Ved frakt bør du bruke en betalingsløsning med kjøperbeskyttelse.
4. Ved leie: se boligen, signer kontrakt og bruk en depositumskonto i banken.
5. Rapporter mistenkelige annonser og meldinger. Det hjelper alle.

Har du allerede betalt en svindler? Kontakt banken din med en gang, og anmeld forholdet til politiet.

## For AI-agenter

API-et og MCP-serveren gir agenter de samme varslene: `safety_warnings` på annonser og `warnings` på meldinger. Agenter bør alltid vise dem til brukeren sin, aldri sende betaling eller koder for brukeren, og tilby å rapportere (`report_listing` / `report_conversation`).
