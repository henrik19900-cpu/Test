# Fritorg på Oracle Cloud «Always Free»

Oracle Cloud har en gratis maskin uten tidsgrense. Den holder godt for Fritorg: 2 ARM-kjerner, 12 GB minne og 200 GB disk (grensene i oktober 2026). Denne guiden setter opp Fritorg der, med eget domene og HTTPS. Det tar rundt en time.

Det du trenger:

- et betalingskort (Oracle bruker det til å bekrefte hvem du er, og trekker ikke penger for gratisressursene)
- et domene, for eksempel et .no-domene fra en norsk registrar
- en konto hos en SMS-leverandør og en SMTP-tjeneste for e-post (se README)

> Oracle har endret gratisgrensene før, uten å si fra. Sjekk [Always Free-ressursene](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) før du begynner, og ta sikkerhetskopi til et annet sted (steg 9).

## 1. Lag kontoen

1. Gå til [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) og lag en konto.
2. Velg **Sweden Central (Stockholm)** som hjemregion. Da ligger dataene i EU, og regionen kan ikke byttes senere.
3. Når kontoen er klar: åpne **Billing & Cost Management → Upgrade and Manage Payment** og oppgrader til **Pay As You Go**. Det som er innenfor gratisgrensene, er fortsatt gratis. På rene gratiskontoer kan Oracle ta tilbake maskiner som har vært lite brukt i en uke, og en ny side med lite trafikk havner fort der.
4. Lag et budsjettvarsel under **Billing & Cost Management → Budgets**, for eksempel på 1 dollar i måneden. Da får du e-post hvis noe begynner å koste.

## 2. Lag maskinen

Under **Compute → Instances → Create instance**:

1. **Image:** Canonical Ubuntu 24.04 (den vanlige, ikke «Minimal»).
2. **Shape:** Ampere, `VM.Standard.A1.Flex`, med 2 OCPU og 12 GB minne.
3. **Networking:** la Oracle lage et nytt nettverk, og kryss av for **Assign a public IPv4 address**.
4. **SSH keys:** last opp din offentlige SSH-nøkkel (eller la Oracle lage en og last den ned).
5. **Boot volume:** velg **Specify a custom boot volume size**, for eksempel 150 GB. Da får databasen og bildene plass på samme disk. Gratisgrensen er 200 GB til sammen.
6. Trykk **Create**.

Får du «Out of capacity», er det for få ledige ARM-maskiner i regionen akkurat nå. Prøv igjen om noen timer.

Noter den offentlige IP-adressen (Public IP).

## 3. Åpne portene for nettsiden

To steder må slippe gjennom port 80 og 443.

**I Oracle:** åpne maskinen, velg subnettet under **Primary VNIC**, så **Security Lists → Default Security List → Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port Range |
| --- | --- | --- |
| 0.0.0.0/0 | TCP | 80,443 |
| 0.0.0.0/0 | UDP | 443 |

**På maskinen:** Oracles Ubuntu-bilder har en brannmur som bare slipper inn SSH. Logg inn og åpne portene, før du installerer Docker:

```sh
ssh ubuntu@<ip-adressen>
sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -m state --state NEW -j ACCEPT
sudo iptables -I INPUT -p udp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 4. Installer Docker

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Logg inn igjen med `ssh`, så du kan bruke `docker` uten `sudo`.

## 5. Pek domenet til maskinen

Hos registraren: lag en **A-oppføring** for domenet (og for `www`) som peker til IP-adressen. Det kan ta litt tid før den virker. Sjekk med `ping ditt-domene.no`.

## 6. Hent og start Fritorg

```sh
git clone <adressen til repoet> fritorg-kode
cd fritorg-kode/fritorg/deploy
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # lim inn som FRITORG_SECRET_KEY
nano .env
```

Fyll inn domene, driftsansvarlig, kontaktadresse, SMS-leverandør og SMTP. Sett `FRITORG_SMS_DAILY_LIMIT` lavt i starten, for eksempel 100, så kan misbruk ikke koste mye.

```sh
docker compose up -d --build
```

Den første byggingen tar noen minutter. Alle avhengighetene finnes ferdig bygget for ARM, så ingenting må kompileres. Caddy henter HTTPS-sertifikatet selv når domenet peker riktig og port 80 og 443 er åpne.

## 7. Sjekk og lag moderator

```sh
docker compose exec app fritorg doctor --send-test-mail deg@example.no --send-test-sms 91234567
```

Lag kontoen din på nettsiden, og gjør den til moderator:

```sh
docker compose exec app fritorg make-admin deg@example.no
```

## 8. Hold maskinen oppdatert

Ubuntu installerer sikkerhetsoppdateringer selv (`unattended-upgrades`). Ny versjon av Fritorg:

```sh
cd ~/fritorg-kode && git pull && cd fritorg/deploy && docker compose up -d --build
```

Databasen oppgraderes automatisk når appen starter.

## 9. Sikkerhetskopi

En daglig sikkerhetskopi på maskinen (`crontab -e`):

```sh
0 3 * * * cd ~/fritorg-kode/fritorg/deploy && docker compose exec -T app fritorg backup /data/backup && docker compose cp app:/data/backup ./backup
```

Kopier den videre til et annet sted, for eksempel til din egen PC:

```sh
scp -r ubuntu@<ip-adressen>:fritorg-kode/fritorg/deploy/backup ./fritorg-backup
```

Prøv også en gjenoppretting en gang, så du vet at den virker.

## Feilsøking

- **Siden svarer ikke:** sjekk at begge brannmurene er åpnet (steg 3), og at `docker compose ps` viser at `app` og `caddy` kjører.
- **«429 Too Many Requests» når bildet bygges:** Docker Hub begrenser nedlastinger uten innlogging. Vent litt, eller hent Python-bildet fra Googles speil av Docker Hub: `docker compose build --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim`, og så `docker compose up -d`.
- **Feil med sertifikatet:** domenet peker ikke til maskinen ennå, eller port 80 er stengt. Se `docker compose logs caddy`.
- **Maskinen er stoppet:** sjekk e-posten fra Oracle. På gratiskontoer kan lite brukte maskiner bli tatt tilbake. Oppgrader til Pay As You Go (steg 1), og start maskinen igjen under **Compute → Instances**.
