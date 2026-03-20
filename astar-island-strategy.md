# Astar Island — Forbedret strategi

## Scoringmodell (viktig å forstå)

Scoren baseres på **entropy-vektet KL-divergens**. Det betyr:

1. **Kun dynamiske celler teller.** Ocean, fjell og isolert skog har entropi ≈ 0 i ground truth og påvirker ikke scoren overhodet. Vi trenger ikke observere dem — bare predikere riktig klasse.

2. **Celler med HØY entropi teller MEST.** En celle der ground truth er [0.4, 0.3, 0.2, 0.1, 0, 0] teller mye mer enn en der det er [0.95, 0.05, 0, 0, 0, 0]. De mest usikre cellene dominerer scoren.

3. **KL-divergens straffer feil asymmetrisk.** Å si 0.01 når ground truth er 0.5 er KATASTROFALT mye verre enn å si 0.3 når ground truth er 0.5. Vi skal heller være "jevnt usikre" enn "selvsikkert feil".

4. **Eksponentiell decay:** `score = 100 × exp(-3 × weighted_kl)`. Liten forbedring i KL gir avtagende score-gevinst. Å gå fra forferdelig til ok er mye verdt. Å gå fra bra til perfekt er lite verdt.

### Implikasjon: "Good enough" overalt > perfekt noen steder

Det er bedre å ha rimelig gode prediksjoner for ALLE dynamiske celler enn perfekte prediksjoner for halvparten og dårlige for resten. Fordi KL-divergensen er et gjennomsnitt (vektet), ødelegger noen få katastrofalt dårlige celler hele scoren.

---

## Informasjonsstrategi

### Hva vi vet GRATIS (fra initial state)

For hver seed får vi:
- **Komplett terrengkart** (40×40 grid med koder 0-11)
- **Alle bosettingsposisjoner** med port-status

Fra dette kan vi utlede:
- Nøyaktig plassering av ocean, fjell, skog, plains
- Fjord-geometri og kystlinjer
- Hvilke bosettinger har tilgang til hav (potensielle porter)
- Hvilke bosettinger er nær hverandre (konflikt-soner)
- Matforsyning per bosetting (antall tilliggende skogceller)
- Isolerte vs. klyngede bosettinger

### Hva vi BARE får fra queries

- **Terrengutfall etter 50 år** (stokastisk — ulikt hver gang)
- **Settlement stats:** populasjon, mat, rikdom, forsvar, tech-nivå, owner_id
- **Fraksjonstilhørighet** — hvem eier hva

---

## Celletypologi og prediksjonsstrategi

### Tier 0: Garantert statiske (predikér direkte, null queries)

| Celle | Prediksjon |
|-------|-----------|
| Ocean (10) | [0.98, 0.004, 0.004, 0.004, 0.004, 0.004] klasse 0 |
| Mountain (5) | [0.004, 0.004, 0.004, 0.004, 0.004, 0.98] klasse 5 |

Disse endrer seg aldri. Bruk 0.98 + gulv 0.004 på resten (sum=1.0).

### Tier 1: Nesten statiske (predikér med høy konfidens, sjelden queries)

| Celle | Prediksjon |
|-------|-----------|
| Skog >5 celler fra nærmeste bosetting | [0.04, 0.005, 0.005, 0.005, 0.94, 0.005] klasse 4 |
| Plains >7 celler fra nærmeste bosetting | [0.94, 0.015, 0.005, 0.015, 0.015, 0.005] klasse 0 |

Fjern skog kan teoretisk vokse inn i ruiner, men sannsynligheten er minimal.

### Tier 2: Dynamisk — bosettingssoner (TRENGER queries)

Celler innenfor ~5-6 celler fra en bosetting. Her skjer det meste:
- Eksisterende bosettinger kan overleve, utvikle port, eller kollapse til ruin
- Tomme celler kan koloniseres
- Ruiner kan gjenoppbygges eller overvokses
- Skog nær bosettinger kan ryddes for ekspansjon

### Tier 3: Dynamisk — ekspansjonssoner (nyttig med queries, men kan infereres)

Celler 4-7 fra bosettinger. Noen bosettinger ekspanderer hit, men sannsynligheten avtar med avstand. Kan delvis infereres fra observerte settlement stats.

---

## Optimal query-allokering

### Prinsipp: Dekk dynamiske soner med LITT overlapp

**Anbefalt: 8-12 queries per seed, tilpasset kompleksitet.**

For en typisk seed med 8-12 bosettinger:

1. **Identifiser klynger av bosettinger.** Grupper bosettinger som er innenfor 10 celler av hverandre. Hver klynge er en "hot zone".

2. **Plasser viewports over hot zones.** Bruk 15×15 viewports sentrert over klyngene. Med 2-3 klynger per seed trengs 2-3 unike viewport-posisjoner.

3. **Repeter hvert viewport 2-4 ganger.** Dette gir oss 2-4 stokastiske utfall per celle, nok til å bygge en rimelig frekvensfordeling.

### Foreslått fordeling (50 queries, 5 seeds):

**Fase 1: Analyse (0 queries)**
- Analysér initial state for alle 5 seeds
- Beregn "dynamisk score" per seed: antall bosettinger × nærhet til hverandre
- Ranger seeds etter kompleksitet

**Fase 2: Bred dekning (30 queries)**
- 6 queries per seed
- Per seed: identifiser 2-3 viewport-posisjoner som dekker flest dynamiske celler
- Kjør hvert viewport 2 ganger
- → 2 observasjoner per dynamisk celle i dekket område

**Fase 3: Målrettet fordypning (20 queries)**
- Analyser resultater fra Fase 2
- Identifiser regioner med høy varians (ulike utfall mellom observasjonene)
- Allokér ekstra queries til disse regionene
- Vurder å omprioritere mellom seeds basert på resultater

### Adaptiv allokering mellom seeds

Ikke alle seeds fortjener like mange queries:
- **Enkel seed** (få bosettinger, isolerte, mye ocean): 6-7 queries
- **Kompleks seed** (mange bosettinger, tett, flere fraksjoner): 12-14 queries

Analyser initial_states FØRST, og fordel queries deretter.

---

## Prediksjonsbygging

### For observerte celler: Bayesiansk frekvensestimering

```python
# For celle (x,y) observert N ganger med counts per klasse
alpha = 0.5  # Dirichlet prior (Jeffreys prior)
# prior_counts kan justeres basert på celletype
counts = [count_empty, count_settlement, count_port, count_ruin, count_forest, count_mountain]
posterior = [(c + alpha) / (N + 6 * alpha) for c in counts]
```

**Jeffreys prior (alpha=0.5)** er bedre enn Laplace (alpha=1.0) for denne oppgaven fordi den gir sterkere estimater med få observasjoner og er den minimax-optimale prioret for KL-divergens.

### For uobserverte dynamiske celler: Terreng- og avstandsbasert prior

Bygge en prior basert på:

1. **Avstand til nærmeste bosetting (d):**
   - d=0 (bosetting selv): høy prob Settlement/Port/Ruin
   - d=1-2: moderat prob Settlement (ekspansjon)
   - d=3-5: lav men ikke-null prob Settlement
   - d>5: primært original terrengtype

2. **Kystlinje-nærhet:**
   - Celle ved hav + nær bosetting: økt Port-sannsynlighet
   - Celle ved hav + nær eksisterende port: enda høyere Port-prob

3. **Matforsyning (skog-tetthet):**
   - Bosettinger med mange skogceller rundt seg: høyere overlevelsessannsynlighet
   - → Naboceller mer sannsynlig Settlement, mindre sannsynlig Ruin

4. **Konflikt-eksponering:**
   - Bosettinger mellom rivaliserende fraksjoner: høyere Ruin-sannsynlighet
   - Isolerte bosettinger: mer stabile utfall

5. **Initialt terreng:**
   - Skog nær bosetting: kan bli ryddet (Empty) eller overleve (Forest)
   - Plains nær bosetting: kan koloniseres (Settlement) eller forbli (Empty)

### Foreslått prior-modell (uobserverte celler)

```python
def dynamic_prior(cell_x, cell_y, initial_terrain, settlements, is_coastal):
    """Returnerer [p_empty, p_settlement, p_port, p_ruin, p_forest, p_mountain]"""
    
    d = min_distance_to_settlement(cell_x, cell_y, settlements)
    
    if initial_terrain == 5:  # Mountain - aldri endres
        return [0.004, 0.004, 0.004, 0.004, 0.004, 0.98]
    
    if initial_terrain == 10:  # Ocean - aldri endres
        return [0.98, 0.004, 0.004, 0.004, 0.004, 0.004]
    
    # Sannsynlighet for at cellen blir en bosetting, avtar med avstand
    p_settle = max(0.02, 0.5 * exp(-0.5 * d))
    
    # Port-sannsynlighet: bare relevant for kystceller
    p_port = 0.3 * p_settle if is_coastal else 0.01
    p_settle = p_settle - p_port  # Juster settlement ned
    
    # Ruin-sannsynlighet: bosettinger som kollapser
    p_ruin = 0.15 * p_settle  # Noen bosettinger kollapser
    
    # Skog: kan vokse inn i ruiner / tomme celler
    if initial_terrain == 4:  # Var skog i starten
        p_forest = max(0.3, 0.8 * exp(-0.3 * (5 - d)))
    else:
        p_forest = 0.05 + 0.1 * (d > 3)  # Skog vokser inn langt fra bosettinger
    
    p_mountain = 0.01  # Fjell oppstår aldri
    p_empty = 1.0 - p_settle - p_port - p_ruin - p_forest - p_mountain
    
    probs = [p_empty, p_settle, p_port, p_ruin, p_forest, p_mountain]
    
    # Gulv og renormalisering
    probs = [max(p, 0.01) for p in probs]
    total = sum(probs)
    return [p / total for p in probs]
```

### Kombinere prior med observasjoner

For celler med NOEN observasjoner (men få), bruk en vektet blanding:

```python
def combine_prior_and_observations(prior, counts, N, confidence_in_prior=2.0):
    """
    confidence_in_prior: antall "pseudo-observasjoner" prioret representerer.
    Høyere = stoler mer på prior, lavere = stoler mer på observasjoner.
    """
    total = N + confidence_in_prior
    posterior = [
        (counts[i] + confidence_in_prior * prior[i]) / total
        for i in range(6)
    ]
    return posterior
```

---

## Avansert: Utnytt settlement stats

Hver simulate-respons gir settlement stats. Bruk disse til å inferere systemtilstand:

### Overlevelsesmodell
```
overlevelsesscore = population × food × defense / (1 + nearby_enemies)
```
- Høy score → bosettingen overlever → naboceller sannsynlig Settlement
- Lav score → bosettingen kollapser → cellen sannsynlig Ruin, naboer mer usikre

### Ekspansjonsmodell
```
ekspansjonsscore = population × wealth × tech_level
```
- Høy score → bosettingen ekspanderer → tomme naboceller sannsynlig Settlement
- Lav score → ingen ekspansjon

### Fraksjonsanalyse
- owner_id viser fraksjonstilhørighet
- Bosettinger med forskjellig owner_id nær hverandre → konflikt-sone
- Konflikt-soner har høyere Ruin-sannsynlighet

### Aggreger over observasjoner
For settlement-celler observert i flere queries:
- Beregn gjennomsnittlig overlevelsesscore og ekspansjonsscore
- Bruk standardavviket som usikkerhetsmål
- Juster naboprediksjonerbasert på disse

---

## Viewport-plassering: Optimaliseringsalgoritme

### Greedy set cover med entropi-vekting

```python
def optimal_viewports(seed_state, num_queries, viewport_size=15):
    """Finn de beste viewport-posisjonene for et seed."""
    
    # 1. Beregn "dynamisk verdi" for hver celle
    #    Basert på avstand til bosettinger, terrengtype, kystlinje
    value_grid = compute_dynamic_value(seed_state)
    
    # 2. Greedy: velg viewport som dekker mest verdi
    viewports = []
    covered = set()
    
    for _ in range(num_queries):
        best_score = -1
        best_pos = None
        
        for x in range(0, width - viewport_size + 1, 2):  # Steg 2 for hastighet
            for y in range(0, height - viewport_size + 1, 2):
                score = 0
                for dx in range(viewport_size):
                    for dy in range(viewport_size):
                        cx, cy = x + dx, y + dy
                        if (cx, cy) not in covered:
                            score += value_grid[cy][cx]
                        else:
                            score += value_grid[cy][cx] * 0.3  # Repetisjon har noe verdi
                
                if score > best_score:
                    best_score = score
                    best_pos = (x, y)
        
        viewports.append(best_pos)
        # Marker som dekket, men med redusert verdi (repetisjon ok)
        for dx in range(viewport_size):
            for dy in range(viewport_size):
                covered.add((best_pos[0] + dx, best_pos[1] + dy))
    
    return viewports
```

### Dynamisk verdi-beregning

```python
def compute_dynamic_value(seed_state):
    """Beregn forventet entropi/dynamikk per celle."""
    grid = seed_state["grid"]
    settlements = seed_state["settlements"]
    
    value = np.zeros((H, W))
    
    for y in range(H):
        for x in range(W):
            terrain = grid[y][x]
            
            # Statisk → null verdi
            if terrain in (10, 5):  # Ocean, Mountain
                continue
            
            d = min_distance_to_any_settlement(x, y, settlements)
            
            # Nærmere bosetting = mer dynamisk = høyere verdi
            if d == 0:
                value[y][x] = 5.0   # Bosettingsceller: svært dynamiske
            elif d <= 2:
                value[y][x] = 3.0   # Ekspansjonssone
            elif d <= 4:
                value[y][x] = 1.5   # Mulig ekspansjon
            elif d <= 6:
                value[y][x] = 0.5   # Liten sjanse for endring
            
            # Kystbonus
            if is_adjacent_to_ocean(x, y, grid) and d <= 3:
                value[y][x] *= 1.5  # Porter er interessante
            
            # Konfliktbonus: mellom bosettinger av ulike fraksjoner
            if between_rival_settlements(x, y, settlements):
                value[y][x] *= 1.3
    
    return value
```

---

## Oppsummert flyt

```
1. GET /rounds → finn aktiv runde
2. GET /rounds/{id} → hent initial_states for alle 5 seeds
3. For hver seed:
   a. Analysér kart: klassifiser celler i Tier 0/1/2/3
   b. Beregn dynamisk verdi-grid
   c. Bestem antal queries (basert på kompleksitet)
   d. Beregn optimale viewport-posisjoner
4. GET /budget → verifiser at vi har nok queries
5. Kjør queries (POST /simulate) for alle seeds:
   a. Lagre alle terrengutfall per celle
   b. Lagre alle settlement stats
6. Bygg prediksjoner per seed:
   a. Tier 0/1: direkte fra initial state
   b. Tier 2/3 med observasjoner: Bayesiansk frekvensestimering
   c. Tier 2/3 uten observasjoner: terreng/avstandsbasert prior
   d. Juster basert på settlement stats
   e. Gulv 0.01, renormalisér
7. POST /submit for alle 5 seeds
8. Print scores og bekreftelser
```

---

## Mulige forbedringer (avansert)

### 1. Lær fra tidligere runder
Bruk `/analysis/{round_id}/{seed_index}` fra avsluttede runder til å:
- Kalibrere avstandsbaserte priors mot faktisk ground truth
- Finne systematiske bias i modellen
- Justere alpha-verdier i Bayesiansk smoothing

### 2. Kernel density estimation
I stedet for per-celle frekvenser, bruk en spatial kernel:
- Observasjoner i naboceller informerer prediksjonen
- Spesielt nyttig med få observasjoner

### 3. Klyngebasert prediksjon
Bosettinger i samme klynge har korrelerte utfall:
- Hvis én bosetting i en klynge kollapser, er nabobosettingene mer sannsynlige å overleve (mindre konkurranse)
- Bruk observerte utfall fra én del av klyngen til å inferere resten

### 4. Monte Carlo-aktig inferens
Med settlement stats fra queries, kan vi simulere forenklede versjoner av mekanikken:
- "Denne bosettingen har lav mat og nær fiende → ~60% sjanse for kollaps"
- "Denne har høy pop + kyst → ~40% sjanse for port"
- Kjør enkle regler 100x for å bygge en pseudo-ground-truth

### 5. Iterativ query-strategi
I stedet for å planlegge alle queries på forhånd:
- Kjør 60% av queries først
- Analyser resultater
- Bruk resterende 40% på de mest usikre områdene
