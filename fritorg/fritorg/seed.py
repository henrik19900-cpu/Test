"""Demo data so a fresh install has something to search. All people and companies are fictional."""

from __future__ import annotations

import random
import secrets
from datetime import timedelta
from typing import Any

from . import identity, listings, messages, users
from .config import Settings
from .db import Database
from .util import to_iso, utcnow

DEMO_EMAIL = "demo@fritorg.no"
DEMO_PASSWORD = "demo1234"  # used when BankID is off
DEMO_TEST_IDENTITY = "01017012345"  # log in with this in the BankID simulator

# (email, full name as BankID would report it, fake 11-digit test identity)
USERS = [
    ("kari@example.no", "Kari Nordmann", "01017010001"),
    ("ola@example.no", "Ola Hansen", "01017010002"),
    ("ingrid@example.no", "Ingrid Berg", "01017010003"),
    ("sara@example.no", "Sara Ahmed", "01017010004"),
    ("fjordbil@example.no", "Jonas Fjeld", "01017010005"),
    ("bolig@example.no", "Mette Lund", "01017010006"),
    ("jobb@example.no", "Lars Lien", "01017010007"),
    (DEMO_EMAIL, "Demo Bruker", DEMO_TEST_IDENTITY),
]

# (owner email, via, data)
LISTINGS: list[tuple[str, str, dict[str, Any]]] = [
    (
        "kari@example.no",
        "web",
        {
            "category": "elektronikk",
            "title": "iPhone 13 128 GB, midnatt",
            "description": "Pent brukt iPhone 13 med 128 GB lagring. Batterikapasitet 88 %. Ingen riper på skjermen, "
            "alltid brukt med deksel. Lader og original eske følger med.",
            "price": 4200,
            "county": "oslo",
            "location": "Frogner",
            "attributes": {"brand": "Apple", "condition": "good", "can_ship": True},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "elektronikk",
            "title": 'Samsung 55" QLED-TV (2021)',
            "description": "Fungerer perfekt, selges på grunn av flytting. Fjernkontroll og veggfeste følger med. "
            "Må hentes.",
            "price": 3500,
            "county": "vestland",
            "location": "Bergen",
            "attributes": {"brand": "Samsung", "condition": "good"},
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "elektronikk",
            "title": "PlayStation 5 med to kontrollere",
            "description": "PS5 med diskstasjon, to kontrollere og tre spill (FIFA 23, Spider-Man og Gran Turismo 7). "
            "Lite brukt.",
            "price": 4500,
            "county": "trondelag",
            "location": "Trondheim",
            "attributes": {"brand": "Sony", "condition": "like_new", "can_ship": True},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "elektronikk",
            "title": "Moccamaster kaffetrakter, sølv",
            "description": "Klassisk Moccamaster KBG Select. Avkalket jevnlig og lager god kaffe. Kannen er uten "
            "sprekker.",
            "price": 900,
            "county": "rogaland",
            "location": "Stavanger",
            "status": "sold",
            "attributes": {"brand": "Moccamaster", "condition": "good"},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "mobler",
            "title": "Hjørnesofa i grå velur",
            "description": "Romslig hjørnesofa, 280 x 200 cm. Ingen flekker, fra røykfritt og dyrefritt hjem. "
            "Kan demonteres for transport.",
            "price": 4000,
            "county": "oslo",
            "location": "Grünerløkka",
            "attributes": {"condition": "good"},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "mobler",
            "type": "give",
            "title": "Sovesofa gis bort – må hentes",
            "description": "Eldre sovesofa fra IKEA (Friheten) gis bort mot henting innen søndag. Litt slitt på "
            "armlenet, ellers i orden.",
            "county": "akershus",
            "location": "Lillestrøm",
            "attributes": {"brand": "IKEA", "condition": "used"},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "mobler",
            "title": "Spisebord i eik med seks stoler",
            "description": "Solid spisebord i heltre eik, 200 x 95 cm, med seks stoler. Noen bruksmerker på "
            "bordplaten. Hentes i Bærum.",
            "price": 6500,
            "county": "akershus",
            "location": "Bærum",
            "attributes": {"condition": "used"},
        },
    ),
    (
        DEMO_EMAIL,
        "web",
        {
            "category": "mobler",
            "type": "wanted",
            "title": "Ønsker å kjøpe: skrivebord med hev/senk",
            "description": "Ser etter et elektrisk hev/senk-skrivebord, minst 140 cm bredt. Kan hente i Oslo og "
            "omegn.",
            "price": 2500,
            "county": "oslo",
            "location": "Oslo",
            "attributes": {},
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "klaer",
            "title": "Bergans dunjakke, dame str. M",
            "description": "Varm dunjakke fra Bergans, brukt én sesong. Ingen skader. Nypris 3 500 kr.",
            "price": 1200,
            "county": "innlandet",
            "location": "Lillehammer",
            "attributes": {"brand": "Bergans", "size": "M", "condition": "like_new", "can_ship": True},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "klaer",
            "type": "give",
            "title": "Barneklær str. 86–92 gis bort",
            "description": "To bæreposer med barneklær i str. 86–92: bodyer, bukser og gensere. Hentes på Tiller.",
            "county": "trondelag",
            "location": "Trondheim",
            "attributes": {"size": "86–92", "condition": "used"},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "sport",
            "title": "Langrennski Madshus 195 cm med bindinger",
            "description": "Madshus Race Pro skøyteski, 195 cm, for 70–80 kg. NIS-bindinger. Brukt to sesonger.",
            "price": 1800,
            "county": "innlandet",
            "location": "Gjøvik",
            "attributes": {"brand": "Madshus", "condition": "good"},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "sport",
            "title": "Telt for fire personer – Helsport Fjellheimen",
            "description": "Robust tunneltelt, brukt på noen fjellturer. Komplett med plugger og barduner.",
            "price": 3900,
            "county": "nordland",
            "location": "Bodø",
            "attributes": {"brand": "Helsport", "condition": "good", "can_ship": True},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "sykler",
            "title": "Terrengsykkel Trek Marlin 7, str. L",
            "description": "Lite brukt terrengsykkel med hydrauliske skivebremser. Nylig service på sykkelverksted.",
            "price": 6500,
            "county": "oslo",
            "location": "Majorstuen",
            "attributes": {"bike_type": "terrain", "frame_size": "L", "brand": "Trek", "condition": "good"},
        },
    ),
    (
        "sara@example.no",
        "mcp",
        {
            "category": "sykler",
            "title": "Elsykkel Cube Kathmandu Hybrid",
            "description": "Cube Kathmandu Hybrid med 625 Wh batteri, ca. 3 000 km. Skjermer, bagasjebrett og lys. "
            "Perfekt til pendling.",
            "price": 18500,
            "county": "vestland",
            "location": "Bergen",
            "attributes": {
                "bike_type": "electric",
                "frame_size": "54 cm",
                "brand": "Cube",
                "condition": "good",
            },
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "sykler",
            "title": "Barnesykkel 16 tommer med støttehjul",
            "description": "Rød barnesykkel for 4–6 år. Støttehjul følger med.",
            "price": 600,
            "county": "rogaland",
            "location": "Sandnes",
            "attributes": {"bike_type": "kids", "brand": "DBS", "condition": "used"},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "barn",
            "title": "Barnevogn Emmaljunga NXT90",
            "description": "Komplett med bag, sittedel og regntrekk. Pent brukt, vasket og klar til bruk.",
            "price": 3200,
            "county": "vestfold",
            "location": "Tønsberg",
            "attributes": {"brand": "Emmaljunga", "condition": "good"},
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "barn",
            "type": "give",
            "title": "Babyutstyr gis bort",
            "description": "Babybadekar, stellematte og en bæresele gis bort samlet.",
            "county": "agder",
            "location": "Kristiansand",
            "attributes": {"condition": "used"},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "hjem-og-hage",
            "title": "Hagemøbler i teak – bord og fire stoler",
            "description": "Teakmøbler som er oljet hver vår. Bordet er 160 cm langt.",
            "price": 2800,
            "county": "ostfold",
            "location": "Fredrikstad",
            "attributes": {"condition": "good"},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "hjem-og-hage",
            "title": "Robotgressklipper Husqvarna 305",
            "description": "Klipper opptil 600 m². Ladestasjon og 200 m kabel følger med.",
            "price": 4500,
            "county": "buskerud",
            "location": "Drammen",
            "attributes": {"brand": "Husqvarna", "condition": "good"},
        },
    ),
    (
        DEMO_EMAIL,
        "mcp",
        {
            "category": "hobby",
            "title": "LEGO Star Wars-samling (12 sett)",
            "description": "Tolv komplette sett med instruksjoner, de fleste med eske. Liste over settene sendes på "
            "forespørsel.",
            "price": 5500,
            "county": "telemark",
            "location": "Skien",
            "attributes": {"brand": "LEGO", "condition": "like_new", "can_ship": True},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "hobby",
            "title": "Yamaha digitalpiano P-125",
            "description": "88 tangenter med vektet anslag. Pedal og stativ følger med.",
            "price": 4200,
            "county": "more-og-romsdal",
            "location": "Ålesund",
            "attributes": {"brand": "Yamaha", "condition": "good"},
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "dyr",
            "type": "give",
            "title": "Kaninbur med utstyr gis bort",
            "description": "Stort innendørsbur med høyhekk og vannflaske. Kaninen er dessverre ikke med.",
            "county": "troms",
            "location": "Tromsø",
            "attributes": {"condition": "used"},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "antikk-og-kunst",
            "title": "Oljemaleri av Lofoten, signert",
            "description": "Originalt oljemaleri, 60 x 80 cm, med ramme. Kjøpt i et galleri i Svolvær.",
            "price": 7500,
            "county": "nordland",
            "location": "Svolvær",
            "attributes": {"condition": "good"},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "annet",
            "type": "wanted",
            "title": "Ønsker gamle LP-plater",
            "description": "Kjøper LP-samlinger, gjerne norsk rock og jazz fra 60- og 70-tallet. Henter på hele "
            "Østlandet.",
            "county": "oslo",
            "location": "Oslo",
            "attributes": {},
        },
    ),
    (
        "fjordbil@example.no",
        "api",
        {
            "category": "bil",
            "title": "Tesla Model 3 Long Range 2021",
            "description": "Hvit, firehjulstrekk, ca. 45 000 km. Autopilot, panoramatak og vinterhjul på felg. "
            "EU-godkjent til 2027. Ingen kjente feil.",
            "price": 249000,
            "county": "oslo",
            "location": "Oslo",
            "attributes": {
                "make": "Tesla",
                "model": "Model 3 Long Range",
                "year": 2021,
                "mileage_km": 45000,
                "fuel": "electric",
                "gearbox": "automatic",
            },
        },
    ),
    (
        "fjordbil@example.no",
        "api",
        {
            "category": "bil",
            "title": "Volkswagen Golf 1.5 TSI 2018",
            "description": "Godt vedlikeholdt Golf med full servicehistorikk. Nye sommerdekk.",
            "price": 159000,
            "county": "trondelag",
            "location": "Stjørdal",
            "attributes": {
                "make": "Volkswagen",
                "model": "Golf 1.5 TSI",
                "year": 2018,
                "mileage_km": 78000,
                "fuel": "petrol",
                "gearbox": "manual",
            },
        },
    ),
    (
        "fjordbil@example.no",
        "api",
        {
            "category": "bil",
            "title": "Toyota RAV4 Hybrid AWD 2020",
            "description": "Lav kilometerstand, hengerfeste og ryggekamera. Én eier.",
            "price": 329000,
            "county": "vestland",
            "location": "Førde",
            "attributes": {
                "make": "Toyota",
                "model": "RAV4 Hybrid AWD",
                "year": 2020,
                "mileage_km": 52000,
                "fuel": "hybrid",
                "gearbox": "automatic",
            },
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "bil",
            "title": "Volvo V70 D4 2014 – pent brukt",
            "description": "Romslig stasjonsvogn med skinnseter og webasto. Registerreim er byttet.",
            "price": 89000,
            "county": "innlandet",
            "location": "Hamar",
            "attributes": {
                "make": "Volvo",
                "model": "V70 D4",
                "year": 2014,
                "mileage_km": 198000,
                "fuel": "diesel",
                "gearbox": "automatic",
            },
        },
    ),
    (
        "fjordbil@example.no",
        "api",
        {
            "category": "bil",
            "type": "rent",
            "title": "Nissan Leaf til leie per dag",
            "description": "Utleie av Nissan Leaf, perfekt til byturer. Hentes på Lade.",
            "price": 450,
            "price_unit": "day",
            "county": "trondelag",
            "location": "Trondheim",
            "attributes": {
                "make": "Nissan",
                "model": "Leaf",
                "year": 2019,
                "fuel": "electric",
                "gearbox": "automatic",
            },
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "mc",
            "title": "Honda CB500F 2019",
            "description": "A2-vennlig MC, bare 9 000 km. Nyservet med nye dekk.",
            "price": 64000,
            "county": "rogaland",
            "location": "Stavanger",
            "attributes": {
                "make": "Honda",
                "model": "CB500F",
                "year": 2019,
                "mileage_km": 9000,
                "engine_cc": 471,
            },
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "bat",
            "title": "Askeladden C61 Cruiser med 115 hk",
            "description": "Populær familiebåt med Yamaha F115. Kalesje, ekkolodd og henger. Vinterlagret innendørs.",
            "price": 239000,
            "county": "vestfold",
            "location": "Sandefjord",
            "attributes": {
                "boat_type": "motorboat",
                "make": "Askeladden",
                "model": "C61 Cruiser",
                "year": 2016,
                "length_ft": 20,
                "engine_hp": 115,
            },
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "bat",
            "title": "Seilbåt Albin Vega 27",
            "description": "Klassisk havseiler med mye utstyr. Nye seil i 2022.",
            "price": 69000,
            "county": "agder",
            "location": "Arendal",
            "attributes": {
                "boat_type": "sailboat",
                "make": "Albin",
                "model": "Vega 27",
                "year": 1974,
                "length_ft": 27,
                "engine_hp": 10,
            },
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "bobil",
            "title": "Hymer bobil 2016 med fire soveplasser",
            "description": "Integrert bobil med queenseng, nytt fortelt og solcellepanel. Alltid vinterlagret.",
            "price": 649000,
            "county": "more-og-romsdal",
            "location": "Molde",
            "attributes": {
                "vehicle_type": "motorhome",
                "make": "Hymer",
                "year": 2016,
                "mileage_km": 62000,
                "berths": 4,
            },
        },
    ),
    (
        DEMO_EMAIL,
        "mcp",
        {
            "category": "deler",
            "title": 'Vinterhjul 18" til Tesla Model 3',
            "description": "Piggfrie vinterdekk med 6–7 mm mønster på originale felger. Sensorer følger med.",
            "price": 7500,
            "county": "oslo",
            "location": "Oslo",
            "attributes": {"brand": "Nokian", "condition": "good"},
        },
    ),
    (
        "bolig@example.no",
        "web",
        {
            "category": "bolig",
            "title": "Lys 3-roms med balkong på Grünerløkka",
            "description": "Lys og pen leilighet i 3. etasje med vestvendt balkong. Kort vei til trikk, butikker og "
            "Sofienbergparken.",
            "price": 5950000,
            "county": "oslo",
            "location": "Grünerløkka",
            "postal_code": "0552",
            "attributes": {
                "property_type": "apartment",
                "bedrooms": 2,
                "area_m2": 68,
                "ownership": "cooperative",
                "year_built": 1902,
                "floor": 3,
            },
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "bolig",
            "type": "rent",
            "title": "Hybel til leie nær NTNU Gløshaugen",
            "description": "Møblert hybel på 18 m² med eget bad. Delt kjøkken. Strøm og internett er inkludert.",
            "price": 6500,
            "price_unit": "month",
            "county": "trondelag",
            "location": "Trondheim",
            "postal_code": "7030",
            "attributes": {"property_type": "room", "bedrooms": 1, "area_m2": 18},
        },
    ),
    (
        "bolig@example.no",
        "web",
        {
            "category": "bolig",
            "title": "Enebolig med stor hage i Sandnes",
            "description": "Familievennlig enebolig med fire soverom, dobbel garasje og solrik hage.",
            "price": 7400000,
            "county": "rogaland",
            "location": "Sandnes",
            "attributes": {
                "property_type": "detached",
                "bedrooms": 4,
                "area_m2": 186,
                "ownership": "freehold",
                "year_built": 1998,
            },
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "bolig",
            "type": "wanted",
            "title": "Ønsker å leie 2-roms i Bergen sentrum",
            "description": "Rolig par i 30-årene søker 2-roms fra 1. desember. Ikke-røykere, ingen dyr, faste jobber.",
            "price": 14000,
            "price_unit": "month",
            "county": "vestland",
            "location": "Bergen",
            "attributes": {"property_type": "apartment", "bedrooms": 1},
        },
    ),
    (
        "bolig@example.no",
        "web",
        {
            "category": "fritidsbolig",
            "title": "Hytte på Hafjell med ski inn/ut",
            "description": "Moderne hytte fra 2015 med fire soverom, badstue og ski inn/ut til alpinbakken.",
            "price": 5200000,
            "county": "innlandet",
            "location": "Øyer",
            "attributes": {
                "bedrooms": 4,
                "area_m2": 120,
                "plot_area_m2": 900,
                "ownership": "freehold",
                "year_built": 2015,
            },
        },
    ),
    (
        "bolig@example.no",
        "web",
        {
            "category": "tomt",
            "title": "Boligtomt med sjøutsikt",
            "description": "Regulert boligtomt på 850 m² med utsikt over fjorden. Vei, vann og avløp frem til "
            "tomtegrensen.",
            "price": 1250000,
            "county": "vestland",
            "location": "Os",
            "attributes": {"plot_area_m2": 850},
        },
    ),
    (
        "jobb@example.no",
        "api",
        {
            "category": "jobb-it",
            "title": "Utvikler (Python) – fast stilling",
            "description": "Vi søker en utvikler som vil bygge åpne og tilgjengelige digitale tjenester. Du jobber med "
            "Python, SQL og moderne nettsider i et lite og selvstendig team.",
            "county": "oslo",
            "location": "Oslo",
            "attributes": {
                "employer": "Nordlys Teknologi AS",
                "employment_type": "full_time",
                "remote": "hybrid",
                "deadline": "2026-11-15",
                "salary": "650 000–800 000 kr/år",
            },
        },
    ),
    (
        "jobb@example.no",
        "api",
        {
            "category": "jobb-helse",
            "title": "Sykepleier – helgestilling 25 %",
            "description": "Hjemmetjenesten trenger sykepleier i helgestilling. Turnus hver tredje helg.",
            "county": "trondelag",
            "location": "Trondheim",
            "attributes": {
                "employer": "Fjellheim Omsorg AS",
                "employment_type": "part_time",
                "remote": "onsite",
                "deadline": "2026-10-31",
                "salary": "Etter tariff",
            },
        },
    ),
    (
        "jobb@example.no",
        "web",
        {
            "category": "jobb-bygg",
            "title": "Tømrer søkes til spennende prosjekter",
            "description": "Vi har mye å gjøre og trenger flere dyktige tømrere med fagbrev. Firmabil og gode "
            "betingelser.",
            "county": "akershus",
            "location": "Lillestrøm",
            "attributes": {
                "employer": "Byggmester Lien AS",
                "employment_type": "full_time",
                "remote": "onsite",
                "deadline": "2026-11-01",
            },
        },
    ),
    (
        "jobb@example.no",
        "web",
        {
            "category": "jobb-handel",
            "title": "Butikkmedarbeider, deltid",
            "description": "Liker du sport og friluftsliv? Vi søker en blid butikkmedarbeider på deltid, også helger.",
            "county": "vestfold",
            "location": "Larvik",
            "attributes": {"employer": "Torvet Sport", "employment_type": "part_time", "remote": "onsite"},
        },
    ),
    (
        "jobb@example.no",
        "web",
        {
            "category": "jobb-transport",
            "title": "Sjåfør klasse C – faste ruter",
            "description": "Faste dagruter i Nordmøre. Krever førerkort klasse C og YSK.",
            "county": "more-og-romsdal",
            "location": "Kristiansund",
            "attributes": {"employer": "Kystfrakt AS", "employment_type": "full_time", "remote": "onsite"},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "hagearbeid",
            "title": "Snømåking og hagearbeid i Bærum",
            "description": "Tilbyr snømåking om vinteren og hagearbeid resten av året. Timepris eller fast pris per "
            "oppdrag.",
            "price": 450,
            "price_unit": "hour",
            "county": "akershus",
            "location": "Bærum",
            "attributes": {"provider_type": "private"},
        },
    ),
    (
        "sara@example.no",
        "web",
        {
            "category": "flytting",
            "title": "Flyttehjelp med varebil",
            "description": "To sterke studenter med varebil hjelper deg å flytte. Vi henter også ting du har kjøpt på "
            "Torget.",
            "price": 650,
            "price_unit": "hour",
            "county": "oslo",
            "location": "Oslo",
            "attributes": {"provider_type": "private"},
        },
    ),
    (
        "ingrid@example.no",
        "web",
        {
            "category": "undervisning",
            "title": "Leksehjelp i matte og fysikk",
            "description": "Masterstudent gir leksehjelp for ungdomsskole og videregående, digitalt eller hjemme hos "
            "deg.",
            "price": 400,
            "price_unit": "hour",
            "county": "trondelag",
            "location": "Trondheim",
            "attributes": {"provider_type": "private"},
        },
    ),
    (
        "kari@example.no",
        "web",
        {
            "category": "it-hjelp",
            "title": "Hjelp med PC, nettverk og smarthus",
            "description": "Kommer hjem til deg og fikser PC, skriver, wifi og smarthus. Tålmodig og pedagogisk.",
            "price": 500,
            "price_unit": "hour",
            "county": "ostfold",
            "location": "Moss",
            "attributes": {"provider_type": "business"},
        },
    ),
    (
        DEMO_EMAIL,
        "web",
        {
            "category": "rengjoring",
            "type": "wanted",
            "title": "Søker vaskehjelp annenhver uke",
            "description": "Leilighet på 80 m² i Bergen sentrum. Omtrent tre timer annenhver uke.",
            "price": 350,
            "price_unit": "hour",
            "county": "vestland",
            "location": "Bergen",
            "attributes": {},
        },
    ),
    (
        "ola@example.no",
        "web",
        {
            "category": "handverk",
            "title": "Elektriker tar små og store oppdrag",
            "description": "Autorisert elektriker med lang erfaring. Gratis befaring i Kongsberg-området.",
            "county": "buskerud",
            "location": "Kongsberg",
            "attributes": {"provider_type": "business"},
        },
    ),
]


def seed(db: Database, settings: Settings | None = None, *, force: bool = False) -> int:
    settings = settings or Settings()
    secret = identity.load_secret_key(settings)
    with db.session() as conn:
        if not force and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return 0
        rng = random.Random(2026)
        accounts: dict[str, int] = {}
        for number, (email, full_name, subject) in enumerate(USERS):
            existing = users.get_user_by_email(conn, email)
            if existing:
                accounts[email] = existing.id
                continue
            verified = identity.VerifiedIdentity(identity.SIMULATED_ISSUER, subject, full_name)
            if settings.bankid_required:
                user = users.create_user(
                    conn,
                    email,
                    verified.display_name,
                    None,
                    identity_hash=identity.identity_hash(secret, verified),
                    verified_name=full_name,
                    verified_via="bankid-simulert",
                )
            else:
                password = DEMO_PASSWORD if email == DEMO_EMAIL else secrets.token_urlsafe(18)
                user = users.create_user(conn, email, verified.display_name, password)
            # Established demo members, so their listings don't look like brand-new accounts.
            joined = to_iso(utcnow() - timedelta(days=200 + 97 * number))
            conn.execute(
                "UPDATE users SET created_at = ?, verified_at = CASE WHEN verified_at IS NULL THEN NULL ELSE ? END "
                "WHERE id = ?",
                (joined, joined, user.id),
            )
            if settings.phone_verification_required:
                # Demo members count as having confirmed a number (none is stored, so real numbers stay free).
                conn.execute(
                    "UPDATE users SET verified_at = ?, verified_via = 'sms', phone_verified_at = ? WHERE id = ?",
                    (joined, joined, user.id),
                )
            accounts[email] = user.id

        now = utcnow()
        created = 0
        # Spread publication times over the last three weeks, with categories mixed.
        slots = list(range(len(LISTINGS)))
        rng.shuffle(slots)
        for slot, (email, via, data) in zip(slots, LISTINGS, strict=True):
            listing_id = listings.create_listing(conn, accounts[email], data, via=via, max_per_day=10_000)
            moment = now - timedelta(hours=slot * 9 + rng.randint(1, 8))
            conn.execute(
                "UPDATE listings SET created_at = ?, updated_at = ? WHERE id = ?",
                (to_iso(moment), to_iso(moment), listing_id),
            )
            created += 1

        sofa = conn.execute("SELECT id FROM listings WHERE title = 'Hjørnesofa i grå velur'").fetchone()
        if sofa:
            conversation_id = messages.contact_seller(
                conn,
                sofa["id"],
                accounts[DEMO_EMAIL],
                "Hei! Er sofaen fortsatt til salgs? Kan hente på lørdag.",
            ).conversation_id
            messages.reply(
                conn,
                conversation_id,
                accounts["kari@example.no"],
                "Hei! Ja, den er ledig. Lørdag passer fint.",
            )
        return created


def seed_if_empty(db: Database, settings: Settings | None = None) -> int:
    return seed(db, settings, force=False)
