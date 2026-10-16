# RAKATHON 2026 — MASTER CONTEXT

> Vše na jednom místě: zadání, novinky z challenge contextu, plány architektury,
> role, výzkum, technologie, dema, nasazení a otevřené otázky.
> Tým staví **G3 (VZP Cesta pacienta) s přesahem do G4 (InterSystems)**.
> Aktualizováno: 16. 10. 2026 (pátek, den zahájení hackathonu).
> Pracovní složka: `/mnt/870Ext/sync/programming/rakathon/prep/`
> (na transerveru zrcadleno v `/mnt/mediastuff/sync/programming/rakathon/prep/`)

---
---

# 1. PROJEKT V KOSTCE

- **Soutěž:** Rakathon 2026 (Hack'n'Roll), kola Praha / Brno / Ostrava, 30 hodin práce.
- **Naše volba:** hlavní výzva **G3**, technologický přesah **G4** (dva acceptance testy jednoho produktu).
- **B1 (FN Brno outlier)** technicky nestavíme; ponecháváme jen narativní paralelu
  ("učíme se z dat"), abychom netříštili scope.
- **Motto organizátorů:** "Máte před sebou 30 hodin, během kterých vznikne něco,
  co jinde trvá měsíce. Dotáhněte to do konce."
- **Ekonomika rozhoduje (FN Brno):** řešení musí být ekonomicky udržitelné
  ("musí něco přinášet"), jinak nemá šanci — promítnout do návrhu i prezentace.

## 1.1 Výzvy

### G3 — Cesta pacienta bez ztráty informací (VZP, hlavní)
> "Vytvořte sdílený případ onkologického pacienta, který propojí lékaře,
> koordinátora a KOC, vytěží data z dokumentace, hlídá podklady, termíny
> a odpovědnosti a předává výsledek MDT. Cílem je rychlejší cesta pacienta
> a méně administrativy."
> Zadavatel: Všeobecná zdravotní pojišťovna ČR.

### B1 — Když realita překoná prognózu (FN Brno – Klinika dětské onkologie, NESTAVÍME)
> "Dokážete odhalit pacienty, jejichž skutečný průběh léčby se výrazně liší
> od očekávané prognózy? Vytvořte model, který neobvyklé případy rozpozná,
> srozumitelně vysvětlí možné příčiny odchylky a nabídne lékařům přehledný
> nástroj pro ověření výsledků a hledání nových klinických souvislostí."
> **Výslovně z memo: nejde o predikci čerstvě příchozího pacienta ani o triáž**,
> ale o zpětné poučení z překvapivých průběhů (analogie Jenner / Semmelweis / Fleming).

### G4 — Nejlepší využití technologií InterSystems pro AI a interoperabilitu (side-challenge)
> Tým, který při řešení kterékoli z ostatních výzev nejlépe využije technologie
> InterSystems k zapojení AI, propojení dat a systémů (zejména HL7 FHIR) nebo obojí.
> Cena: **1 500 €**. Zadavatel: InterSystems.
> Chtějí: (1) FHIR úložiště, (2) AI-ready vrstvu (normalizace, mapování,
> dotazovatelnost), (3) AI pomocníka nad tím.
> Nabízejí: vlastní FHIR server, ukázky mapování, dokumentaci, konzultace,
> vývojové nástroje. Stack: **FHIR / OMOP / SNOMED / LOINC** (+MedDRA, ATC).
> Hodnocení jejich ceny: data v IRIS + agentní tools (SQL / FHIR server /
> Vector Search) + demo interoperability přes lokální FHIR repozitář.
> Reálné/testovací nemocniční prostředí nebude — simuluje se lokálním FHIR
> serverem v IRIS. Přednahraná data v templatu nejsou data výzev.
> Klíčová rada: **začít s FHIR hned od začátku**, keep it simple, neřešit
> autentizaci do detailu. Mentoři: Praha (Ondřej + Gabriel), Ostrava (Dan Kutáč),
> Brno (Daniil Drozdov); online 24/7 Slack Tech Help Desk + kanál výzvy.

---
---

# 2. G3 — PŘESNÉ ZADÁNÍ (z fotek + VZP 3 memo)

Přednášející trojice: **RNDr. Marián Rybář, Ph.D., MHA (MZ / poradce ministra,
data)** + **doc. MUDr. Zuzana Bielčíková, Ph.D. (onkoložka)** +
**Ing. Klára Vaňková (živá koordinátorka)**.

## 2.1 Motivace (Rybář, VZP 3)
- >50 % lidí s karcinomem plic se nedostane k léčbě dříve než
  do 8 týdnů od CT (doloženo pro plíce; prs/pankreas slide-only, nedokládat).
  Mezitím přechod stadia 1–2 → 3–4 (léčitelné → neléčitelné).
- Za to nemůže nemoc ani příhoda — **může za to systém**, který neumí
  koordinovat pacienta včas k léčbě.
- Časná stadia ~50 tis. Kč (slide-only), pozdní stadia mnohonásobně dražší.
- VZP s MZ spolupracuje na hrazení výkonu koordinátora (kód 51887, 250 Kč
  za výkon — bodová hodnota 0, úhradová vyhláška 2026 bod 8.5).
- Praktik s podezřením často neví co dál / kam referovat; koordinátor pacienta
  provede systémem rychle, dokud je rakovina léčitelná.

## 2.2 Čtyři úkoly softwaru
1. **01 PŘEVZÍT / SJEDNOTIT** — shromáždit dokumentaci referovaného případu
   na jedno místo, **bez dalšího formuláře** (referující lékař nahraje existující
   zprávy ze svého ambulantního systému na 1–2 kliky).
2. **02 VYTĚŽIT** — porozumět dokumentaci: AI strukturované vytěžení
   + **kontrola úplnosti**; AI před-připraví dokument ke kontrole / schválení /
   odeslání člověkem.
3. **03 KOORDINOVAT** — počítat **čas do léčby pro každého pacienta**
   (T1+T2+T3); koordinátor vidí stav (nový / v řešení / čeká na doplnění),
   termíny, vlastníka; systém umí zpětně kontaktovat referujícího pro doplnění.
4. **04 ZPĚTNÁ VAZBA** — hlásit výsledek zpět: po rozhodnutí KOC/MDT vrátit
   referujícímu lékaři jasný strukturovaný výsledek **včetně původního kontextu
   případu**; reviznímu lékaři předat **automaticky** (AI třídění do předem
   definované struktury + možnost vyžádat si doplnění od koordinátora);
   předání potvrdit a případ uzavřít.

## 2.3 Metrika: čas do léčby = T1 + T2 + T3
- **T1** — referování: symptom → předání do KOC (hlídá praktik + koordinátor).
- **T2** — KOC/MDT: přijetí → rozhodnutí.
- **T3** — rozhodnutí → zahájení léčby.
- Osa: Symptom —T1→ Diagnostika (KOC/ROC) —T2→ MDT (KOC) —T3→ Léčba (KOC/ROC).
- Role na ose: PL / specialista → KOC/ROC → KOC → KOC/ROC.
- Fáze pacienta: **K1 Před léčbou** (náš hlavní scope, červená) → **K2 Během léčby**
  → **K3 Po léčbě** (přesah/monitoring).
- Každé 4 týdny zpoždění = vyšší mortalita (Hanna et al., BMJ 2020, 1,2 mil.
  pacientů, 34 studií) — ale **4 týdny nejsou univerzální bezpečná doba**,
  SLA vždy per diagnóza a klinický plán (Banks 2023: 58 % = operace
  5–12 týdnů od dg; ne ">6 týdnů od bronchoskopie" — opravit citaci).
- T-metriky na slajdu: VL (vlastník), PT (pacient), SYS (systém), milníky T1/T2/T3.

## 2.4 Problém na třech místech (slajd)
1. **NA VSTUPU (referující lékař):** dokumentace přichází roztříštěná různými
   kanály a nekompletně; lékaři opakovaně přepisují údaje, které už existují;
   podezření odhalit, odeslat e-mailem na KOC, dohledávat dokumentaci.
2. **UVNITŘ KOC (koordinátor):** kompletovat dokumentaci, sledovat termíny,
   připravit MDT; koordinátor tráví čas dohledáváním místo koordinací; není
   společný přehled o stavu, termínech a odpovědnosti; MDT dostává podklady
   pozdě/nekompletně.
3. **NA VÝSTUPU (zpět k lékaři):** informační smyčka se neuzavírá — referující
   lékař nemá jak zjistit, zda byl pacient přijat, co chybí a jak MDT rozhodlo;
   prodleva odeslání → dokumentace → rozhodnutí → léčba se obtížně sleduje.

## 2.5 Ideální řešení (akceptační kritéria UI)
- Seznam pacientů/případů **seřazený podle priority**; na první pohled fáze
  cesty, **další krok a kdo ho má udělat**.
- Stručný přehled o případu na jednom místě; klíčové informace pro koordinaci;
  dokumentace přehledně uspořádaná; **z dokumentace lze informace kopírovat**.
- Systém **počítá čas do léčby a upozorňuje** na blížící se termíny a lhůty;
  zpoždění lze řešit včas; **jedním klikem informuji referujícího lékaře**.

## 2.6 Demo MUSÍ ukázat (6 povinných bodů)
1. Referování pacienta do KOC **bez dalšího formuláře** (krok 01).
2. **AI vytěžení s kontrolou úplnosti** (krok 02).
3. Přehled případů **se stavem a termínem** (krok 03).
4. **Vlastník každého dalšího kroku** (krok 03).
5. **Strukturovaný závěr KOC/MDT** (krok 04).
6. **Zpětná vazba a potvrzené předání** (krok 04).
- **Výstup: jedna diagnóza a funkční demo.** Celý průchod jednoho případu
  od referování po potvrzené předání.
- **"Rakathon ověří princip. Produkční integrace patří do další fáze."**

## 2.7 Referenční případ Pan Novák (HPB, VFN — hotový testovací příběh)
- ILUSTRATIVNÍ ZJEDNODUŠENO (ne medián reálné praxe): 60 let.
  **5. 1. 2026** zežloutnul, volá PL → **6. 1.** UZ břicha: tumor
  slinivky; PL aktivuje koordinátora KOC → **7. 1.** hospitalizace →
  **9. 1.** stent do žlučových cest + histologie → **12. 1.** CT, TM →
  **13. 1.** 1. MDT, **20. 1.** 2. MDT → **26. 1.** operace.
- 21 dní symptom→operace, 2× MDT (IDEÁL s koordinátorem, ne medián).
  CT-po-histologii v příběhu je atypické pořadí (demo artefakt).
  Entity k extrakci: datum, UZ/CT/TM/histologie/stent/MDT. Prodlevy mezi milníky = T1/T2/T3 demo.
- Kontakt: `koordinace-hpb@vfn.cz` — POZOR, na fotkách je pouze hpb,
  hbp jen v próze (OPEN/neověřeno — nehardcodovat, **ověřit u garanta**).
- Pilot VFN HPB = testovací data/persona; koordinátor KOC/ROC, lékař i nelékař.

## 2.8 Kdo je koordinátor (role K1)
- Vzniká při vysokém podezření; nová pozice (NOVÉ: pozice / procesy /
  odpovědnost / finance). Diagram: LÉKAŘ → [odeslání] → KOORDINÁTOR →
  časová osa → PACIENT.
- Od **1. 1. 2026 povinný v každém KOC** (min. 1,0 úvazku, Věstník MZD 11/2025
  čl. 6); zdravotnické vzdělání NENÍ podmínkou (min. SŠ/VOŠ/VŠ).
- Pracuje **na písemné vyžádání lékařů**, objednává indikovanou plánovanou péči,
  využívá "v plném rozsahu NIS", dokumentuje v záznamu o koordinování.
- **Nerozhoduje o léčbě.** 3 typy: K1 před KOC (fast-track, největší úspora),
  K2 uvnitř KOC (podklady pro MDT), K3 po léčbě (návazná péče).
- MOU: **17 000 intervencí/rok** (slide-only), 1 200 edukací (slide-only);
  diagnostika **2–3 týdny místo 2 měsíců** (slide-only); FN Bulovka ~10 pacientů/týden (slide-only).
- Koordinátorské patero: pozice, mapa, spojenci, průchod, zlepšování.

## 2.9 Ostatní VZP výzvy (kontext, NESTAVÍME)
- **VZP 1 (konec života):** transparentní nástroj kvality péče na konci života;
  indikátory: systémová léčba 30/14 dní před smrtí, radioterapie v závěru, čas
  od poslední léčby; dashboard + srovnání pracovišť. VAROVÁNÍ: indikátor ≠
  kvalita — kontext (stadium, komorbidity, věk), konec léčby ≠ začátek
  paliativy, neostrakizovat, malé počty = nejistota.
- **VZP 2 (mamograf):** zvýšit účast screeningu; 2024: tisíce dopisů,
  **44,5 % nepřišlo** (uncertain — v rozporu s VZP >60 % jinde; nedokládat přesně);
  4 otázky KDO má riziko / PROČ / CO s tím / JAK ověřit;
  dataset + slovník; segmentace → cílená intervence → experiment.
- **VZP💥 (adherence + koordinace):** 2 větve — adherence k prevenci;
  koordinace (koordinátoři dnes "tužka, papír, telefon, maily").
  VZP řízený vstup inovací **inovace.vzp.cz** — dobré řešení do praxe, ne do šuplíku.

# 3. HODNOCENÍ A ORGANIZACE

## 3.1 Kritéria (Organizace memo + fotky)
- **Sobota — lokální, neformální (mentoři obcházejí, NE pitch na stagi):**
  1. Produkt / technologie (funguje? dává tech smysl? zajímavé využití AI?
     impressive za 24 h).
  2. Využitelnost v praxi (splnění zadání partnera, realistická nasaditelnost,
     GDPR/security, reálné NIS v nemocnicích).
  3. Inovativnost (originální spin, odlišení od konkurence/alternativ).
- **Neděle — jen postupující, formální pitch:**
  4. Škálovatelnost / dlouhodobý potenciál (ne jen vyhrát cenu a skončit;
     ambice dotáhnout, reálný dopad).
  5. Kvalita prezentace a týmu (**3 minuty pitch**, destilace hodnoty pro
     netechnické + zdravotní publikum vč. předsedy vlády / ministra;
     **tým jde na stage celý — prezentují všichni**).
- Otázka "nápad vs. provedení" zůstala v záznamech bez odpovědi; organizátor:
  porota s AI agenty čeká vyšší kvalitu než loni.

## 3.2 Logistika (Brno)
- **Dnes v 19:00** deadline potvrdit výzvu + složení týmu (jinak nelze postoupit; memo-only, ověřit kde).
- Přespání na místě (karimatky, vyhrazená místnost); ráno ~8:00 restart.
- Další zásadní deadline ~13:00 = resume workshopu ve VTT (ne submit; ověřit přesný čas a místo).
- Odevzdání přes submit formulář (URL unverified/garbled — ASR slyšelo `subwit.caton.cz`,
  pravděpodobně překlep; ověřit na místě) + popis projektu/týmu + odkazy/repo/obrázek.
- Komunikace: Slack hlavní kanál + kanál výzvy + Tech Help Desk.
- Každá výzva posílá **1 vítěze do celostátního finále Praha (neděle)** —
  společný vlak zdarma + proplacení cesty zpět (memo-only); čas do neděle 14:00 na ladění pitche (memo-only).
- Boilerplate/UI komponenty z před-Rakathonu povoleny, ale **transparentně
  deklarovat** co vzniklo před vs během; submissions se publikují všem.
- Data výzev nejpozději při startu hackování do Slack kanálu výzvy;
  veřejná data povolena. **VZP data jen pro VZP výzvu.**
- Azure: vlastní Resource Group per tým, role jen Contributor (RBAC/Key Vault
  řešit přes Slack s Michalem MSFT); modely přes sdílený APIM endpoint + API key
  (`aka.ms/rakathon2026`), klíč v `api-key` headeru, **nikdy do frontendu**;
  modely gpt-6.1-sol/astra/luna, grok-4.7, DeepSeek-V4-Pro, Kimi-K2.7-Code,
  MAI-Thinking-1; rozpočet ~100–200 USD/tým; 429 = backoff; 401 = revoke.
- Lokální modely nejsou nabízeny. Cloud LLM na zdravotní data: smí se, pokud
  zadavatel potvrdí anonymní/syntetická data (většina výzev taková je) —
  **ověřit se zadavatelem**. Na demo stačí lokál; Azure není povinný pro hlavní
  cenu (jen pro cenu partnera).

## 3.3 Ceny a motivace (Vzp meta)
- **100 000 / 50 000** + hodina s generálním ředitelem + šance dostat se do
  **inovačního fast-tracku** ("jedna z nejlepších věcí, které z hackathonu
  mohou vzejít"). Příklad: projekt začal na hackathonu → pokračoval → miliony.
- Vzkaz: nemyslet jen "soutěž měst", zamakat (Brno vs Praha na finále),
  přemýšlet co s projektem dál i bez výhry.

## 3.4 Lidé a kontakty
- **G3 mentoři (slajd):** doc. MUDr. Zuzana Bielčíková, Ph.D.; Ing. Klára
  Vaňková; Mgr. Tereza Chrástová; RNDr. Marián Rybář, Ph.D., MHA;
  Mgr. Michaela Tůmová; MUDr. Michaela Klimeš Lipánová.
- Konzultanti pro týmy: MUDr. Petr Tůma… (příjmení useknuté na fotce) +
  koordinátor/lékaři + právo + pacient (část nečitelná — dofotit/vyžádat).
- **MSFT koučové:** Michal Marušan (AI/Azure/Copilot), Simon Procházka
  (prototyp), Olena Vasylenko (onkologická/biologická data, AI — relevantní),
  Bernardo Sunderhus (frontend/UX/React — relevantní).
- **InterSystems:** Praha Ondřej + Gabriel, Ostrava Dan Kutáč, Brno Daniil Drozdov.
- NCEZ/EHDS: Michal Opatřil (LinkedIn konzultace), Hynek Kružík (HL7 ČR).
- MZ: MUDr. Ondřej Franěk (NCEZ), ministr (poradce Rybář).
- Pondělí 19. 10. 2026 IPVZ Praha (vítězný tým v plném počtu); 16.–20. 11.
  HL7 Malaga; HoF Pisa 19.–21. 10.

---
---

# 4. B1 DETAIL (kontext, NESTAVÍME — rozhodnutí týmu)

- Přednášející: Vítězslav Dušek + Anička (dětská onkologie + analytika).
- Slajdy: AI podpora výkonnosti JIP (nezpožděné alarmy, signál jako informace,
  Beth Israel 130k pobytů, TRV 246k hodin, SIGN 9 signálů/5 jevů;
  FN Brno 1 799 hospitalizací, 31 551 pacientodnů) — kvanta bez krytí
  v challange_context, brát jako foto/team-interpretace, necitovat přesně.
- Datový model B1: A event-log hospitalizace (emergency, sepse, překlady,
  lůžka, propuštění/death, primární dg.) → B prognóza (rizikové skóre,
  propuštění %, mortalita %, délka 1–3 dny) → C odchylky (prognóza vs realita,
  lékař adjustuje plán).
- Data: MIMIC-IV (adult ICU analogie, ne pediatrie) + FN Brno; 3 propojené anonymizované soubory (pacienti +
  nádory + epizody péče/cesta) + vybrané laborky; popisky features nejasné
  (připravováno narychlo) — počítat s datovým průzkumem.
- Úkol B1: model pro predikci + business logika signalizace + UI;
  proaktivní signalizace zhoršování; jisté a přehledné předání lékaři.
- Metodika pro náš G3: pattern baseline vs reziduum (očekávaný průběh —
  Cox PH / Random Survival Forest / boosting / DeepSurv — vs odchylka,
  flag při |z-score| nad prahem) + anomaly detection; vysvětlitelnost SHAP
  top-3 + konfidence + co chybí; lékař ověřit/zamítnout + research view.
  Prognóza = FHIR RiskAssessment map (team-interpretace, bez krytí v zadání), realita = Observation/CancerDiseaseStatus.

---
---

# 5. MEDICÍNSKÝ SLOVNÍK PRO AJŤÁKA (nadmnožina z více zdrojů — není plná verze ze slovnik-pojmu.md)

## 5.1 Cesta pacienta
- **Patient Pathway** = jízdní řád léčby (klinický plán: co, v jakém pořadí,
  do kdy). **Patient Journey** = reálná zkušenost (čekání, stres, doprava,
  ztracené výsledky). Pathway je ideál, journey je realita.
- 5 fází: pre-diagnostika/uvědomění → vstup + diferenciální dg (referenční
  řetězec) → terapeutické rozhodování (MDT!) → léčba + bariéry dostupnosti →
  adherence/perzistence/outcome.
- 7 kroků onko trajektorie: prevence/záchyt → projevy/odeslání → diagnóza/
  staging/plán → léčba → follow-up → recidiva → EOL. Screening + podpůrná
  péče ve všech fázích; paliativa časně vedle kurativy (WHO, ne jen konec života). Při recidivě návrat
  k rozhodování.
- **Suspekce** = podezření, ještě ne diagnóza. **Histologie** = rozbor tkáně
  (typ nádoru). **Staging** = rozsah (I–IV). **TNM** = solidní nádory
  (T velikost, N uzliny, M metastázy); FIGO gynekologie; Lugano lymfomy;
  INSS/INRGSS neuroblastom děti.
- **MDT** = multidisciplinární tým (onkolog+chirurg+radiolog+patolog+
  koordinátor), porada jako code review; min. trojčlenný (TRUE per KDP 20,
  numerické kvórum nedokládat); kvórum řídí předseda; bez dotčené specializace
  žádné doporučení; závěr písemný, jednoznačný, do dokumentace + sdílení
  ošetřujícímu/praktikovi/pacientovi; i neshoda se dokumentuje. Indikační
  komise MOU (čtvrtek 14:00 digestivní, pondělí 12:00 GIT…), objednání přes
  konziliární ambulanci / webový formulář.
- **Remise** = ustoupila (ne vyléčena, dál sledování). **Recidiva/relapse** =
  návrat (issue se znovu otevírá). **Progrese** = zhoršování. **Response** =
  reakce na léčbu. **ECOG** = fyzička 0–4 (+ grade 5 = smrt). **Komorbidity** = další nemoci.
- **Follow-up** = dlouhodobé sledování. **Screening** = plošné hledání
  u zdravých. **Adherence/perzistence** = bere léky správně / vydrží.
  **Outcome** = výsledek. **Paliativní** = úleva vedle léčby (mitigace).
  **Podpůrná** = vedlejší účinky ve všech fázích.

## 5.2 Role a místa
- **KOC** = Komplexní onkologické centrum (15 v ČR — oficiálně KOC/ROC/NOC,
  tier-3/tier-1 neoficiální, nedokládat). **ROC** = regionální (kontroly, sledování,
  delegovaná preskripce). Místo péče se posuzuje per výkon/fáze.
  Předání 4 kroky: posouzení → převzetí (kapacita+kompetence+termín) →
  společný plán → návratové spouštěče. Do ACK krok u konkrétního vlastníka.
  ROS (regionální onkologické skupiny) v čele s KOC; Rada KOC; Národní rada.
- **Koordinátor** = project manager průchodu (ne léčby). Krajský (FN Brno/MOU).
  HOP = pacientská organizace. PanCareLIFE = pozdní následky u dětí (80 % =
  přežití; focus fertilita/sluch/QoL — ne jen "v remisi").
- Praktik = L1 support (odesílá, dostává zprávy).

## 5.3 Dokumenty a CZ eHealth
- **Propouštěcí zpráva** (incident report), **pacientský souhrn** (README),
  **eŽádanka** (stavový automat — viz kap. 8), **eZpráva** (lékařský e-mail,
  ~5 mil./rok, KNTB odesílá co 2h), **EZKarta** (profil), **SZZ** (sdílený
  záznam — jen emergentní + prevence/screening, §34a), **NCEZ** (architekt),
  **NZIS** (evidence), **NOR** (data warehouse, ne live péče; ISNO nedoloženo),
  **NPEZ** (portál, Portál lékaře/pacienta od 1.–2. 1. 2026),
  **EZD** (právní šanon poskytovatele) vs **EHR** (interoperabilní výtah) vs
  **NIS/AIS/LIS/RIS/PACS** (5 provozních systémů).
- NIS produkty: Medea/STAPRO (VFN, Olomouc), Medicalc (Plzeň, Hradec),
  FONS Enterprise (Thomayerka), AMIS*H (ÚVN), UNIS (Motol, Bulovka),
  IKIS/AGEL (Nový Jičín), CGM MEDICUS (malé), OR-CZ MARIE PACS (120+,
  deklaruje FHIR), ARIA/Eclipse/RT (radioterapie, SMART on FHIR).
- ePACS/ReDiMed (DICOM výměna, IHE XDS-I.b); WSI digitální patologie v ČR
  neověřena plošně; Sectra v ČR nedohledána.
- Centrální služby: kmenové registry (KRPZS/KRZP/KRP, REST API jen
  s certifikátem EZCA), Dočasné úložiště, Registr oprávnění, Žurnál,
  Notifikace, ELP posudky, EZCA, afinitní domény. eŽádanka povinně od
  1. 7. 2027 návrh novely — povinnost přijmout platí (vystavení dobrovolné, pilot 1. pol. 2026).
- **AAfD** = federovaný katalog — DRAFT (kniha zůstává v knihovně). **MHD**:
  ITI-65 publish / 66 lists / 67 find / 68 retrieve. PDQm/PIXm/PMIR identity,
  mCSD adresář, IUA/ATNA auth/audit, DSUBm notifikace.
- eRecept (SÚKL CÚER) / eNeschopenka (ČSSZ, ne SÚKL/CÚER); indiko.cz (indikátory, FBMI+ÚZIS pro KZP);
  PUK (kvalita pojišťoven); NZIS Open/NZIP; VZP publikace dat, VZP PLUS
  bonifikace; kódy 51881 (MDT seminář), **51887 (koordinátor, od 1. 1. 2026,
  250 Kč za výkon — bodová hodnota 0, úhradová vyhláška 2026 bod 8.5)**, 51885 (molekulární tumor board).

## 5.4 Právo
- **372/2011** zdravotní služby (§56a–56c + §63 předávání mezi poskytovateli legální; §65–66 je jen nahlížení/kopie).
- **325/2021 + novela 236/2025** elektronizace (účinnost 1. 1. 2026);
  eŽádanka/SZZ/ELP; **444/2024** dokumentace.
- **GDPR čl. 6** (titul) + **čl. 9** (citlivá data): souhlas pacienta nestačí
  univerzálně — potřeba matice rolí×účely + DPIA (čl. 35 povinná pro
  zdravotní data + AI — rizikově podmíněná per čl. 35(3)(b) + FRIA, ne automaticky) + mlčenlivost + retence; čl. 28 smlouva se zpracovatelem;
  čl. 22 pozor na plně automatizovaná rozhodnutí → držet human-in-the-loop.
- **EHDS** (platné od 26. 3. 2025; fáze: 3/2029 souhrn+eRecept/eVýdej+sekundární většina,
  3/2031 imaging/lab/propouštěcí+genomika, 3/2035 třetí země — ne "plně 2029"):
  primární (péče) vs sekundární (výzkum přes HDAB) využití;
  povinné kategorie: souhrn, eRecept/eVýdej, propouštěcí, lab, obraz
  (bez ZZS — ZZS není EHDS kategorie).
- **EU AI Act:** klinický CDS = high-risk přes čl. 6(1)+Annex I (MDR SaMD,
  ne Annex III 5a/5d) → conformity assessment, dokumentace, logging (Art. 12),
  transparentnost, human oversight (Art. 14); obecná povinnost od 2. 8. 2026 trvá,
  high-risk povinnosti Omnibus: 2. 12. 2027 (Annex III) / 2. 8. 2028 (Annex I SaMD); AI literacy od 2025.
  Art. 6(3) výjimka jen pro Annex III (profiling vždy high-risk + dok.+registrace);
  úzké procedurální úlohy (přepis → struktura) bez
  scoringu — náš agent "jen přepisuje" by mohl spadnout sem, "navrhuje" = high-risk.

---
---

# 6. SYSTÉMOVÝ PLÁN (G3 + přesah G4) — SCHVÁLENÝ SMĚR TÝMU

**Princip:** 7 modulárních bloků B1–B7, každý má 2 konektory (vstupní protokol
→ výstupní protokol). **Jediný překlad proprietární↔FHIR je v B1**; uvnitř
už jen FHIR↔FHIR přes InterSystems. Dnešní demo je 1 HTML s `var PAC` —
cílový stav to rozseká na moduly s kontrakty.
Střed pro všechny: **jedna dashboarda** (stejná data, unless GDPR) + tlačítko
s rychlým přehledem pro vlastní roli + nahoře **Spotlight** upozornění
v normálním jazyce, specializovaná podle role. Vždy dostupný AI agent běžící
kde si nemocnice vybere (lokálně / u důvěryhodné společnosti), s volitelnou
mírou dat (jména? přesný věk vs odhad?) nebo kompletně vypnutý; default nevidí
přesná data (jen IDs, na klientovi se přepíšou na reálné údaje).

## 6.1 Bloky B1–B7
- **B1 Ingest + normalizace (anti-corruption layer):** NIS/LIS/RIS/PACS +
  VZP CSV + HL7v2/CDA/PDF + eŽádanka eventy → FHIR R4 CZ Core + `$validate`;
  nevalidní → `OperationOutcome` fronta k ručnímu dočištění. Konektory:
  proprietární in / FHIR Bundle out + MHD publish/find.
- **B2 Koordinační jádro (zdroj pravdy):** `EpisodeOfCare + CarePlan +
  Task(vlastník+termín+ACK) + CareTeam`; eŽádanka stavový automat;
  timeout→eskalace (48 h žádanka / 7 d histologie; SLA per dg).
  Konektory: FHIR REST CRUD + Subscription/Flag eventy.
- **B3 Dashboard shell:** jediná read-model vrstva; role-view filtruje pohled,
  ne duplikuje data (GDPR výjimka jen pacient); Spotlight = federovaný search
  FHIR+Vector; offline cache. Konektory: `$everything` search + Spotlight API.
- **B4 MDT (XTB-WD):** Request→Schedule→Prepare→Meeting→Finalize; completeness
  gate (povinná trojice) zamyká approve; kvórum; hlasy + kvórum; výstup Tasky,
  SBAR generování. Konektory: CarePlan/Task/Appointment write +
  Provenance/AuditEvent.
- **B5 Hlídací pes:** watchdog SLA per dg (ne fixní 4 týdny);
  `Flag/DetectedIssue` + `Subscription`; agregace + digest proti alert fatigue.
  Konektory: timer trigger + Flag POST; notify webhook + ACK callback.
- **B6 Volitelný lokální AI agent (default OFF):** RAG-MCP (`getPatientJourney`,
  `searchEvidence`, `explainFlag`) + RiskAssessment/SHAP jako příspěvek, ne důkaz;
  každé tvrzení citace + nejistota + override; nikdy přímý zápis bez člověka.
  Konektory: MCP IDs-only + SQL Builder/Bulk export.
- **B7 Identita, řízení přístupu, audit, GDPR matice (TARGET; TODAY = MOCK):** RBAC per matice rolí
  (slid 48), SMART OAuth2/IUA, ATNA syslog, PIXm/PDQm, pseudonym↔identita trezor
  jen zde, tenant KOC/ROC. Konektory: SMART token + ATNA/PIXm. [MOCK v demu: login/matrice/audit/kill-switch]

## 6.2 Konektory — pravidlo hranic
- Nemocnice proprietární↔FHIR **jen v B1** (jediný překladový bod).
- Uvnitř B2–B6 **FHIR↔FHIR přes InterSystems** (Interoperability production /
  FHIR repository). Žádné paralelní proprietární zkratky do UI/AI.
- InterSystems stavební kameny: Interoperability Production (Business Service /
  Process / Operation + adaptéry HTTP/REST/SOAP/FTP/TCP/File/SQL + DTL
  transformace), SDA meziformát (CDA/HL7v2→SDA→FHIR), FHIR server (R4 REST,
  resource repository), **FHIR SQL Builder** (FHIR jako SQL tabulky bez přesunu
  dat), Bulk FHIR Coordinator ($export ndjson), FHIR Adapter + SDA↔FHIR DTL,
  Embedded Python, **Vector Search** (VECTOR typ, HNSW index, VECTOR_COSINE),
  RAG/GraphRAG + MCP (iris-agentic-dev, ai-hub-eap, medical-graphrag-assistant).
  DASTA→FHIR oficiálně nedokumentováno → custom EDI schéma + DTL přes SDA.
  HealthShare docs za loginem; AI Hub zatím EAP/community.
- Community templaty: `iris-fhir-template` (docker FHIR server),
  `FHIR-AI-Hackathon-Kit` V2 (Jupyter: FHIR→SQL→Vector→LLM→agenti→MCP),
  `iris-agentic-dev` (90+ MCP tools pro vývoj na IRIS).

## 6.3 Bezpečnost — poctivě (žádný marketing; TARGET vs TODAY: níže TARGET, TODAY = MOCK bez reálného RBAC/auditu/kill-switche)
- **E2EE jen client-side** (PII→IDs, blob store) + TEE / confidential computing
  pro náročné; jinak **TLS + RBAC + audit + minimalizace** — netvrdit E2EE nad FHIR.
- Default **IDs-only**, scope `patient/` + v2.2 filtry, **token exchange RFC 8693**
  pro agenta, mapování ID↔PII jen klient/B7 trezor (HSM/KMS, split-key, audit).
- Granularita per nemocnice: 0=OFF (default) / 1=souhrn bez PII / 2=plný kontext
  s účelem; každý stupeň logován; kill-switch jedno tlačítko (B6 stop,
  dashboard jede z cache, stav AI_DISABLED viditelný + audit).
- SMART App Launch 2.2 (patient/user/system .cruds + query-param filtry);
  Backend Services (client_credentials + JWT); PKCE + krátké tokeny.
- Audit = **AuditEvent** (security/privacy, ATNA/BALP) + **Provenance**
  (lineage dat) — immutable, retence dle AI Act Art. 12.
- LLM deployment: default on-prem open-weights (Llama/Mistral/Qwen) + lokální
  vector store; cloud jen pseudonymizovaná/UUID data jako opt-in; on-prem
  neškáluje pro startupy → alternativa dedikovaný healthcare cloud s BAA/DPA
  nebo confidential computing u trusted hosta.
- Pseudonymizace ≠ anonymizace (stále osobní data, čl. 9 trvá).
- **Cordis verdikt: NEBRAT pro hackathon.** InterSystems Cordis neexistuje
  (0 výsledků); Cordis TS framework (MIT plugin kernel) by kryl jen slupku
  B3/B6, porota boduje IRIS+FHIR+AI, learning curve 2–4 h za 0 bodů, dvě jádra
  vedle sebe = zmatek. Alternativa: contracts + tenký fhir-client + plain
  ES moduly init/destroy. Max. jeden slide vize.

## 6.4 Dashboard, Spotlight, AI agent UX (ověřené vzory)
- Jeden prioritizovaný **inbox/queue** (new/in-progress/resolved), persistent
  patient context panel, summary-first timeline (dg/stadium/biomarkery/patologie/
  imaging + časová osa); navify Tumor Board −35,4 % času MDT, −76,5 % dokumentace
  (footnote: Taiwan 2021 single-centre, −76,5 % = recording comments).
- Akce v kontextu **max ~2 kliky**, viditelný owner + due + ACK, team-based
  routing (ne vše na lékaře; AIM −12,2 zpráv/lékař/den).
- **Spotlight:** interrupt (modal) JEN vysoká závažnost + vysoká jistota +
  nízký FP + okamžitě akční; vše ostatní pasivní badge/sidebar; tiering
  severe/moderate/minor; formulace title + proč s daty + akce + důsledek +
  ack důvody; override je feature (důvod se loguje a učí); governance měří
  burden i outcome. Vendor defaulty acceptance 4–11 % — nutná lokální kalibrace.
- AI agent: human-on-the-loop (viditelné mezistavy, pause/rewind), navrhuje
  (sumarizace, prioritizace, drafty) / člověk rozhoduje (podpis, override,
  eskalace); **citace u každého tvrzení** (jinak lékaři nevěří); klinický
  narativ místo SHAP heatmap; nízká verifikační frikce (předvyplněné,
  editovatelné); UAII label + transparentnost validace/limitů + feedback loop.
- SHAP zvyšuje confidence, ne shodu; kontrafaktuál tlumí over-reliance;
  kalibrovaná confidence snižuje override (studie 87,64 % → dolů);
  HITL +7,1 % přesnost (vendor-blog, pending primary — nedokládat), −24–72 % dokumentační čas (ale jen při reálném zapojení,
  ne "podepiš co AI udělala" — pozor scapegoat-in-the-loop).
- Alert fatigue data: override 46–96 %, lékař 187 monitor warnings per patient/day
  (physician ~56; ne "180+ alertů/den"), ICU FP 80–99 % (ne 80–90 %).
  Mayo 22→15,8/+18 % DROP — bez zdroje (conflate TREWS/COMPOSER), nedokládat.

---
---

# 7. ROLE — KDO CO DĚLÁ + JAK TO DNES VIDÍ

## 7.1 Cílový stav (náš systém)
- **Praktik:** pošle podezření, vidí semafor stavu + kontakt; po MDT závěr;
  nestaginge/neplánuje. Spotlight: táhne se 21 dní / no-show.
- **Pacient + rodina:** souhlasy, docházka, potvrzování termínů; jasný plán
  (kam/kdy/co s sebou/kontakt); jen svůj případ. Spotlight: zítra CT 9:00…
- **K1:** bere na referraci, shání termíny (hlavně CT!) a výsledky, hlídá
  dovedení k vyhodnocení. Ne o léčbě. Spotlight: 2 dny bez ACK / 7 dní bez
  histologie / doprava padla.
- **K2:** kompletuje MDT podklady, bookuje, hlídá kvórum+deadline, rozešle
  závěr + Tasky. Spotlight: chybí PDL-1/staging / radiolog nepotvrdil.
- **K3:** předání do regionu, návratové spouštěče. Spotlight: X týdnů bez
  kontroly / ROC nereportuje.
- **Diagnostik (CT/BX/histologie/TNM/markery):** vyšetří, dodá zprávu+PACS
  do deadline. Spotlight: žádanky po deadline / nejasný požadavek.
- **Ošetřující onkolog:** prezentuje na MDT, navrhuje, potvrzuje místo péče
  s vysvětlením, sdělí pacientovi, řídí léčbu; vlastník kroku do ACK.
  Spotlight: region nepřevzal do 48 h / výsledek chybí 7 dní.
- **MDT + předseda:** stanoviska oborů (bez nich žádné doporučení v modalitě);
  předseda řídí/čas/kvórum/konsensus (i neshodu) + podpis. Spotlight: chybí
  klíčový člen → orientačně / vágní závěr → dopracovat.
- **ROC:** výslovně přijme (kapacita+kompetence+termín), delegovaná léčba,
  reporty do KOC, při neúčinnosti vrátí pacienta. Spotlight: k převzetí / čeká
  se na report.
- **Sestra:** objednávky, zápis, rozesílka. **Dispečink:** vůz/asistence,
  náhradník, cena předem; jen kontakt+místo, ne dg. **VZP:** úhrada +
  agregace. **IT:** RBAC, audit, kill-switch.

## 7.2 Dnešní stav (výzkum 2024–2026 — nástroje / vidí / nevidí)
- **Onkolog:** NIS svého zařízení + MDT formulář + NOR + Portál lékaře + MEDDI.
  Vidí vlastní dokumentaci + SZZ výběr. Nevidí cizí zařízení ani region po předání.
- **MDT:** nejednotné webové formuláře (část jen telefon/e-mail), RIS/PACS
  vlastní, video ad hoc. Vidí co kdo donesl. Nevidí externí podklady, obrazy
  jen na vyžádání (ePACS/ReDiMed), po MDT plnění. WSI patologie neověřena.
- **Praktik:** AIS + eZpráva + Portál lékaře + datovka. Vidí co přijde (pozdě).
  Nevidí obrazy, plnou dokumentaci, MDT závěr; zprávy často vůbec nedojdou.
- **Koordinátor:** telefon (hlavní kanál!), lokální NIS, žádosti papír/elektronicky,
  izolované piloty; jednotná platforma ani přehled kapacit NEEXISTUJE
  (Excel/Teams nedoloženy — absence nástroje je nález). Vidí své zařízení.
  Nevidí region/dopravu/převzetí; kapacity obvolává.
- **KOC/ROC:** NIS + smlouvy + brožury. Vidí vlastní kapacity. Nevidí visící předání.
- **Pacient:** EZKarta + NPEZ + telefon + papír. Vidí příběh roztříštěně
  (SZZ jen emergentní + prevence). Nevidí snímky (jen popis), patologii,
  MDT závěr centrálně.
- **Sestra:** denní seznam + telefon + papír; jen směna; ne omezení pacienta
  ani chybějící podklady. **Dispečink:** žádný centrální onko dispečink;
  PKZT/VZP-39 papír; ne konec výkonu ani potřeby.
- **VZP:** vykazovací data, PUK, INDIKO, NZIS Open, NOR, publikace, PLUS
  bonifikace. Vidí retrospektivu ("58 % čeká >6 týdnů" — slide-only, citaci opravit viz 2.3). Nevidí důvod ani live stav.
- **IT:** NIS vendoři, FHIR R4 IGs (cz.core/hdr/img/szz), TermX, kmenové registry
  (jen s EZCA certifikátem), DU, SÚKL/CÚER. Vidí logy a duplicity. Bolest:
  DASTA (dávky/registry; odkaz na DASTA web 404 — necitovat URL) vs HL7v2 (uvnitř) vs FHIR (nová výměna) — nekonvertují se samy.
  Medicalc API 2027 interní (ne otevřené); AIS FHIR nedeklarují.
- Fragmentační vzor pro všechny: svůj primární systém + papír/telefon/e-mail;
  vidí jen svou epizodu; nevidí end-to-end stav úkolu.

---
---

# 8. EŽÁDANKA — JAK FUNGUJE

- Není PDF, je to **stavový automat** (národní systém NCEZ/MZ): Vystavit
  (lékař: pacient z registrů + vyšetření + priorita + kontakt) → Uložit/odeslat
  do centrálních služeb → [Vyhledat/Načíst = operace, ne stavy] →
  **Přijmout = ACK** (kapacita = důvod vrácení do oběhu při nedostatku;
  kompetence není v specu — teprve přijetím závazná) → Vyřídit (vč. Výsledku
  jako součásti vyřízení: nález zpět ordinujícímu + praktikovi jako
  eZpráva/DocumentReference/DiagnosticReport).
- Oficiální stavy: Nová / Přijatá / Neproveditelná / Stornovaná / Dokončená /
  Expirovaná (odmítnutí není stav; rozdělení v2 nepodporováno; no-show/výpadek
  mimo spec). Immutable Bundle + 9 operací + ETag/409 + expirace 3 roky.
  Každý přechod auditován (ATNA/AuditEvent), identity z registrů, práva per role.
- Povinná 2027/28 zatím jen návrh novely; od 1. 1. 2026 povinnost přijmout,
  vystavování dobrovolné (pilot zobrazovací/konzilia/FT, labo až 2. pol. 2026).
  Nestavět vlastní žádankový systém — počítat s centrálním, náš systém je adaptér.
- V G3 mapování: `ServiceRequest` (bez accepted — jen Task.accepted; team mapping,
  ne NCEZ) + `Task` (vlastník+termín+ACK) + Subscription notifikace (team mapping,
  ne NCEZ); SLA 48 h / 7 d = demo práh (ne norma), eskalace při nepotvrzení.

---
---

# 9. FHIR ZDROJE A TERMINOLOGIE (rychlá mapa)

- **Základy:** Resource (LEGO kousek) → Profile (pravidla pro zemi) → IG
  (kuchařka) → ValueSet/CodeSystem (enum) → OperationOutcome (chyba validátoru).
  FHIR R4 stabilní (R5 STU / R6 snapshot); EHDS ukládá FHIR pro prioritní EHR;
  NCEZ REST API dle R4; CZ profily hl7.cz/fhir (STU 1.0), žádný CZ HIE IG (jen cz-core CI 1.1.0).
- **Klinické:** Patient (kdo), Encounter (návštěva), Condition (dg.),
  Observation (měření/nález/stadium), DiagnosticReport (výsledková zpráva),
  Specimen (vzorek), ImagingStudy (snímek, DICOM), Procedure (zákrok/operace/
  ozařování), MedicationRequest/Administration (předpis/podání).
- **Koordinační:** CarePlan (plán z MDT), CareTeam (kdo se stará), Task
  (Jira ticket: vlastník+termín+stav+ACK), Appointment, ServiceRequest
  (=eŽádanka), Communication, DocumentReference (obálka, ne obsah),
  Provenance/AuditEvent (git blame + log), Subscription (webhook),
  Flag/DetectedIssue (chybí podklad), QuestionnaireResponse, EpisodeOfCare,
  Bundle (transakční balík).
- **B1:** RiskAssessment (prognóza: prediction/probability/when/basis),
  MolecularSequence/GenomicsReport/Variant (DNA); mCODE genomika
  (GenomicsReport/Variant/RegionStudied); pediatrický NCPI IG
  (relativeDateTime), neuroblastom/rhabdomyosarcoma profily v mCODE (draft maturity-0).
- **Onko modely:** mCODE STU4 4.0.0 (hotové FHIR profily + terminologie +
  příklady; CancerPatient/PrimaryCancerCondition/CancerDiseaseStatus LOINC
  97509-4/CancerStage+TNM/TumorMarkerTest/Genomics/ECOG/Radiotherapy…;
  balíček hl7.fhir.us.mcode; CodeX RT STU2 2.0.0 staví na mCODE) vs European Cancer
  Common Data Model — ECCDM 1.0.0-ballot (ne ECCM; koncept+logický model, mapování hotové jen pro
  Patient/Person, zbytek progress; build.fhir.org/ig/hl7-eu/cancer-common).
  Nejsou zaměnitelné! Pro ČR + národní identifikátory a CZ profily.
- **Terminologie:** MKN-10/ICD (dg.), LOINC/NČLP (lab — v ČR výjimka NČLP),
  SNOMED CT (EU preference; v ČR jen kde dává smysl, jinak AI návrh +
  human-check; LOINC↔SNOMED ~85 % (bez zdroje — nedokládat)); DICOM (obrazy), PDF/A přílohy.
- **IHE:** MHD/MHDS dokumenty; PDQm/PIXm/PMIR identity; mCSD adresář;
  IUA/ATNA auth/audit; DSUBm notifikace; XTB-WD tumor board (PCC, ne ITI;
  Request→Schedule→Prepare→Meeting→Finalize); XDS-I.b (XDS-I deprecated 2012; ePACS).
- **InterSystems operace:** $validate/$everything/List $find/$find, Observation $lastn/$lastn,
  $export (Bulk IG, ne core — ndjson)/$expand; SMART on FHIR/OAuth2; verzování resourců; více endpointů
  v jednom namespace; FHIR SQL Builder projekce (Analyze→Spec→Projection,
  role FSB_Data_Steward (+FSB_Admin), vyžaduje Advanced Server).
- **ML pro B1:** Cox PH / RSF / DeepSurv / boosting (očekávaná křivka);
  anomaly detection; reziduum; z-score/threshold; SHAP (pozor: korelace,
  ne kauzalita); counterfactual; research view.

---
---

# 10. ZDROJE V REPU (co kde leží)

- `prezentace/`: Analyza_cesty_onkologickeho_pacienta_FBMI_final.pptx (52 sl.,
  Tichopád ČVUT — Patient Pathway/Journey, 5 fází, 7 kroků, koordinace sl. 20,
  KOC/region sl. 33–34, 4 hackathonové výzvy sl. 44–48, akceptační scénáře
  sl. 50, právo sl. 46–49); Ceske_eHealth_v_kostce.pdf (Opatřil, 22 s. — 4 vrstvy,
  EZD≠EHR, MHD, MVP pattern, Patient/DocumentReference/Task/CarePlan);
  HL7_Rakathon_2026 úvod (Kružík, 23 sl. — V2/CDA/FHIR, ECCDM, mCODE);
  Rakathon_2026-MSFT-Slides.pdf (33 s. — Azure RG, modely, VZP-only data);
  Rakathon_HoF_PHOENIX_XiA.pdf (Luc Chatty, 16 s. — HoF/PHOENIX/XiA, 6 pravidel).
- `meeting_zaznamy/`: 2× .mp4/.m4a (ignorovat) + 2× .cc.vtt + 2× newChat.txt.
  Ranní 072521 = teorie EHDS/FHIR (zadání v něm NEJSOU); odpolední 105031 =
  MSFT + InterSystems G4 + Phoenix workshop (G3/B1 zadání v něm NEJSOU;
  chybí prvních 23 min). Chat Q&A: FHIR token odpoledne (ne zítra), boilerplate povolen
  s deklarací, Contributor only, 429 backoff, lokál stačí, Azure bez vlivu
  na hodnocení, "nápad vs provedení" bez odpovědi.
- `challange_context/`: 15 fotek v prezentace/ (vše VZP G3 — B1/G4 labely v Příloze B
  jsou mislabeled, viz oprava tam) +
  12 .aac mem + 12 .txt přepisů (complete). Priority: VZP 3 (Rybář/Bielčíková/
  Vaňková), Vzp meta (motivační), Organizace-kriteria (pravidla+ceny).
  Transkripce: faster-whisper (9× small GPU stt2, 3× medium CPU stt);
  onkozro/fnmh/prodekan nespolehlivé (ověřit poslechem); fnmh+VZP💥 začínají
  až od 00:30. Prostředí: /tmp/opencode/stt, /tmp/opencode/stt2,
  /tmp/opencode/stt_transcribe.py (hotovo, procesy ukončeny).
- `slovnik-pojmu.md` (plný slovník, zdroj kap. 5). Tento `context.md` (master).
- `visual-guide/`, `visual-glossary/`, `visual-pipeline/`, `demo-dashboard/`
  (viz kap. 11).

---
---

# 11. LOKÁLNÍ ARTEFAKTY A NASAZENÍ

## 11.1 Vizuály a dema (vše tmavý fialovo-modrý hackathon styl, 0 externích requestů)
- **visual-guide/index.html** (:8081) — 6 sekcí + hero: hero G3/B1/G4, slovníček
  10 karet s IT analogiemi, timeline 7 kroků + 4 demo scénáře, checklist
  engine + eŽádanka kanban, B1 graf + SHAP, FHIR tabulka + IRIS stack,
  právo, víkendový plán.
- **visual-glossary/index.html** (:8082 + LIVE
  https://rakathonslovnik.estrogenaddict.space) — 154 karet všech pojmů,
  vyhledávání + 13 filtrů, klik-detail, kopírování, počítadlo, 🎲 flashcard
  modal, 29 FHIR resourců tabulka.
- **visual-pipeline/index.html** (:8083) — interaktivní SVG mapa toku dat
  (8 uzlů, animované tečky, toggle vrstev G3/G4/kritická cesta), swimlane
  4 rolí, tech stack 5 vrstev, 24h Gantt, 4 scénáře + rizika.
- **demo-dashboard/index.html** (:8084) — 4 záložky: koordinátor fronta
  (6 syntetických pacientů C50/C34/C18, SLA ticker, P4 ztracená histologie,
  P6 nepřevzatá péče), detail (timeline/checklist/úkoly+ACK), MDT
  (completeness bar se zámkem, SBAR + kopie, hlasování 4/4), B1 mini-view
  (scatter + SHAP). FHIR badge u údajů. Interakce: filtr→detail→odškrt→MDT.
  Mezeru proti realitě sepsal oracle: kvórum podle rolí, proklik SBAR na zdroj,
  audit místo alert(), triáž alertů, login/matrice rolí.

## 11.2 Servery (běží na pozadí)
- `prep/visual-guide` :8081 · `prep/visual-glossary` :8082 ·
  `prep/visual-pipeline` :8083 · `prep/demo-dashboard` :8084
  (vše `python3 -m http.server`, logy /tmp/opencode/*.log).
- Transerver (bea@transerver): tmux `rakathon-slovnik`, port **19231**
  (obscure, mimo 8xxx) → cloudflared `trans-tunnel`
  (`rakathonslovnik.estrogenaddict.space` → localhost:19231).
  Config /home/bea/.cloudflared/config.yml (+.bak); DNS přes
  `cloudflared tunnel route dns`; restart pkill+nohup. Pre-existing chyba
  v logu (temp.estrogenaddict.space → 18474 refused) nesouvisí s námi.

## 11.3 Klíčové externí zdroje (ověřené)
- hl7.org/fhir/R4 · hl7.cz/fhir · build.fhir.org/ig/HL7-cz/* (cz-core/hdr/img/szz)
  + /HL7-cz/cz-core (CI 1.1.0; žádný CZ HIE IG) · hl7.eu/fhir · hl7.org/fhir/us/mcode/STU4 ·
  build.fhir.org/ig/hl7-eu/cancer-common · profiles.ihe.net/ITI ·
  mzcr.atlassian.net/EPZS · health.ec.europa.eu (EHDS).
- docs.intersystems.com (irisforhealthlatest: FHIR server/SQL Builder/Bulk/
  productions/DTL/SDA/Vector Search/Embedded Python), community.intersystems.com,
  GitHub intersystems-community (fhir-template, FHIR-AI-Hackathon-Kit,
  iris-agentic-dev, ai-hub-eap, medical-graphrag-assistant, iris-ai-examples,
  iris-vector-search), openexchange (FHIR-AI-Hackathon-Kit).
- CZ: ncez.mzcr.cz, ezdravi.gov.cz, mzd.gov.cz, uzis.cz/kdp, nikez.mzcr.cz,
  Věstník MZD 11/2025, mou.cz, fnbrno.cz, indiko.cz, onconet.cz, hlaspacientu.cz,
  ezprava.net, epacs.cz, inovace.vzp.cz, aka.ms/rakathon2026.
- PHOENIX: phoenix@hl7europe.org, SYNDERAI syntetika, hospitalsonfhir.eu.

---
---

# 12. PLÁN NA 24 HODIN

- **0–3 h:** FHIR server (IRIS / Hackathon Kit) + import (VZP CSV + Pan Novák
  dokumenty + 1 neúplný případ) + první Task/CarePlan; ověřit odkaz na datasety.
- **3–8 h:** koordinační jádro (fronta dle priority, T-metriky, vlastník+ACK)
  + UI pro role (koordinátor K1 hlavní, lékař, MDT, referující PL).
- **8–14 h:** AI extrakce (DocumentReference → JSON schéma; citace + confidence +
  human-check) + kontrola úplnosti + hlídání/eskalace (48 h / 7 d).
- **14–19 h:** MDT (completeness gate, kvórum, SBAR, hlasy→Provenance) + krok 04
  (report referujícímu s kontextem + revizní automaticky + potvrzení + uzavření)
  + RAG/MCP nad FHIR (getPatientJourney) + FHIR→SQL dashboard (G4 důkaz).
- **19–24 h:** 6 bodů dema na Pan Novákovi + negativní scénář (ztracený výsledek /
  nepřevzatá péče) + validace ($validate, OperationOutcome) + pitch 3 minuty
  (celý tým) + úklid Azure RG.
- Průběžně: konzultace s mentory (T-metriky, revizní lékař, GDPR matice),
  validace s klinickým garantem (lhůty, povinná trojice, kvórum, kdo smí ACKovat).
- Demo flow 4 min: ztracená patologie → eskalace → neúplné MDT (systém přizná) →
  KOC→region potvrzení → graf čekání → audit stopa → krok 04 potvrzené předání.
  Druhá nemocnice = přepnutí FHIR base URL.

---
---

# 13. OTEVŘENÉ OTÁZKY (ověřit u organizátorů / mentorů / garantů)

1. E-mail KOC: `koordinace-hpb@vfn.cz` vs `hbp` varianta — OPEN (fotky pouze hpb,
   hbp jen v próze; nehardcodovat). Reálná schránka nebo demo placeholder?
2. Odkaz na datasety / datový slovník / seznam indikátorů — kde je (Slack?) a je live?
3. Přesné deadliny: 19:00 dnes memo-only (kde se potvrzuje?), ~13:00 zítra = resume
   workshopu ve VTT (ne submit), submit URL unverified/garbled
   (ASR `subwit.caton.cz`?), co přesně odevzdat.
4. Jména: Chrástová vs "Krástová", Vaňková vs "Wenková", Tůma celým,
   role Tůmové / Klimeš Lipánové — spelling do prezentace.
5. Ceny 100k/50k: za co přesně? Fast-track podmínky?
6. SLA prahy per dg/fáze (ACK eŽádanky? histologie/staging?) — návrh 48 h / 7 d
   je ilustrativní z dema.
7. Povinná trojice completeness + kvórum MDT — univerzální nebo per dg?
   Kdo smí odemknout approve při chybějícím podkladu + jak auditovat?
8. Kdo smí být vlastník Tasku a ACKovat převzetí KOC↔ROC (role vs osoba)?
9. Tenant model: federace (data u zdroje) vs centrální IRIS kopie?
10. AI default OFF + IDs-only: akceptuje garant užitek bez PII? Hranice stupně 2?
11. Doprava: stačí externí dispečinkový konektor, nebo plný modul
    (ceník/storno/izochrony)?
12. Cloud LLM na (syntetická?) data — explicitní souhlas zadavatele?
13. V jaké síti je pilotní KOC/region (eZpráva/eMeDocS/datovka)? Co vendor
    NIS umí dnes ve FHIR (SMART launch? write-back? RBAC?)?
14. B1 čísla z fotek ("1799 hospitalizací", "16… záznamů") a InterSystems.txt
    (jména, MDR certifikace, seznam nemocnic) — nespoléhat, ověřit u stánku.
15. Matice rolí pro dashboard (KOC koordinátor / krajský / externí / sestra /
    dispečink / řidič): titul čl. 6/9, mlčenlivost, retence — s DPO.

---
*Konec master contextu. Při změně plánu aktualizovat příslušnou kapitolu
a datum nahoře. Jedna diagnóza, šest bodů dema, princip ne integrace.*

---
---

# PŘÍLOHA A — VOICE MEMA PO JEDNOM (klíčové body)

## VZP 3 (13,5 min, medium, dobrá kvalita) — NEJDŮLEŽITĚJŠÍ
- Trojice Rybář (MZ/data) + Bielčíková (onkoložka) + Vaňková (koordinátorka).
- >50 % Ca plic k léčbě až po 8 týdnech (doloženo pro plíce; prs/pankreas slide-only);
  přechod stadia 1–2 → 3–4;
  časná stadia ~50 tis. (slide-only), pozdní mnohonásobně dražší; chyba systému.
- Koordinátor od prvního podezření ("může sedět kdekoliv, tzv. KOC");
  praktik s podezřením neví kam → referuje koordinátorovi, ten provede systémem.
- Referující nahraje existující zprávy z AIS na 1–2 kliky; AI před-připraví
  strukturovaný dokument ke kontrole/schválení/odeslání.
- Koordinátor vidí stav (nový / v řešení / čeká na doplnění), termíny,
  vlastníka; systém umí zpětně kontaktovat referujícího pro doplnění.
- Po MDT: sumář pro rozhodnutí → zpráva zpět referujícímu.
- Prezentuje celý tým (VZP 3 úvod: "prezentovat budete všichni").

## Organizace, kriteria hodnocení (10,6 min, medium)
- Dnes v 19:00 potvrdit výzvu + složení týmu, jinak nelze postoupit (memo-only).
- Sobota: produkt/tech, praxe, inovativnost (mentoři obcházejí).
- Neděle: + škálovatelnost/dopad + 3min pitch celého týmu (memo-only; ministr/vláda).
- Nocleh na místě (karimatky), ráno ~8 restart, ~13:00 = resume workshopu ve VTT (ne submit),
  submit formulář (URL unverified/garbled) + popis + repo + obrázek, Slack hlavní kanál.
- 1 vítěz výzvy do Prahy (vlak zdarma + cesta zpět — memo-only), ladění do neděle 14:00 (memo-only).

## Vzp meta (1,7 min) — motivační, žádné zadání
- Ne "soutěž měst" — zamakat, Brno vs Praha na finále; 100k/50k + hodina s GŘ
  + fast-track; projekt z hackathonu → miliony; myslet co s tím dál i bez výhry.

## Brno intro (14 min, small)
- Hack'n'Roll Brno; FN Brno/VUT/LF: stárnutí, málo personálu, náklady →
  tlak na efektivitu, AI klíčová; ekonomika rozhoduje; FN Brno nabízí data
  a testovací prostředí; témata screening→paliativa.

## FN Brno - outlier (10,4 min, small, spolehlivé)
- Najít outliery lépe/hůře než standard; Jenner/Semmelweis/Fleming motivace;
  3 propojené anonymizované soubory + laborky; popisky nejasné (narychlo);
  explorace → ověřit → proč → další kroky; **interpretovatelnost povinná**;
  ne predikce/triáž, ale podklad pro diskusi.

## VZP 2 (10 min, mamograf, spolehlivé)
- Účast screeningu; papírové pozvánky přežitek; 44,5 % nepřišlo (2024 — uncertain,
  rozpor s VZP >60 % jinde);
  různé klientky potřebují různou podporu; 4 otázky KDO/PROČ/CO/JAK ověříme;
  dataset + slovník + mentoring; segmentace → intervence → experiment.

## VZP 1 (6,5 min, konec života, spolehlivé)
- Kvalita konce života (začátek sledovaný, konec opomíjený); ~5–6 indikátorů
  (léčba 30/14 dní před smrtí, radioterapie, čas od poslední léčby);
  dashboard + srovnání + reprodukovatelnost; bonus přenos metodiky.
  VAROVÁNÍ: indikátor ≠ kvalita (stadium/komorbidity/věk), konec léčby ≠
  paliativa (není kód), neostrakizovat, malé počty = nejistota.

## Intersystems (4 min)
- Podpora inovací (startup MIT Grand Hack → inkubátor → globální zákazníci);
  technologická výzva ke kombinaci; vlastní onko IS (+MDR certifikace?) a
  data/rozhraní; reálné nasazení ve FN. "Nedělejte si 100 agentů najednou" —
  jednoduše, realizovatelně; připravit datové rozhraní/protokol.

## VZP💥💥💥 (4 min, první polovina spolehlivá)
- Adherence k prevenci + koordinace (koordinátoři "tužka, papír, telefon,
  maily"); pozdní přechod do paliativy; kvalita života, sdílení info,
  vytížení přístrojů; inovace.vzp.cz slib cesty do praxe; osobní apel
  (screeningy zachraňují životy; pro pacienty, ne jako cvičení).

## onkozro / fnmh / prodekan (nízká spolehlivost, ověřit poslechem)
- onkozro: asi nové onko centrum (září), priority, telemedicína, "jděte
  programovat". fnmh: fragment (p. Štulík?, zázemí?). prodekan: ceremoniál
  fakulty. Pro G3 bez akčních bodů.

---
---

# PŘÍLOHA B — FOTKY PO JEDNÉ (15×, vše VZP G3 v prezentace/ — B1/G4 labely níže jsou mislabeled, opraveno)

## G3 (11×)
1. `101335066` — logo wall (ne zahájení/Franěk — oprava verifikace). Věcně nic.
2. `110543910` — evoluce péče (ne VÝZVA; reálná VÝZVA je `111105250`).
3. `110632387` — kdo je koordinátor: LÉKAŘ → [??] → KOORDINÁTOR → časová
   osa → PACIENT; KOC/ROC, lékař/nelékař; koordinace-hpb mail (na fotkách pouze hpb,
   hbp jen v próze — OPEN); pilot VFN;
   NOVÉ pozice/procesy/odpovědnost/finance.
4. `110756242` — K1 hlídá čas do léčby: K1/K2/K3 kruhy, osa
   Symptom—T1→Diagnostika—T2→MDT—T3→Léčba, role PL→KOC/ROC→KOC→KOC/ROC,
   vzorec T1+T2+T3, legenda KOC/ROC/PL.
5. `110909696` — totéž + Pan Novák (viz kap. 2.7; ILUSTRATIVNÍ ZJEDNODUŠENO) + mail (pouze hpb — OPEN).
6. `111001429` — problém na 3 místech (vstup/uvnitř KOC/výstup), viz 2.4.
7. `111058433` — ideální řešení 3 sloupce (seznam / přehled / reporting),
   viz 2.5.
8. `111105250` — zadání pro týmy (křivé foto): prototyp pro koordinátora,
   využijte existující data; konzultanti Tůma…/koordinátor+lékaři/právo/
   pacient; zdroje nečitelné (dofotit).
9. `111500856` — krok 04 PŘEDÁNÍ VÝSLEDKU (flow + HOTOVO KDYŽ…), viz 2.2/2.6.
10. `111603561` — CO ODEVZDÁTE: jedna diagnóza + demo, 6 bodů (viz 2.6),
    princip ne integrace; ilustrace PATIENTS/CALENDAR/TASKS.
11. `111701186` — PODKLADY (anonymizované podklady, slovník, indikátory,
    kontext, konzultace) + MENTOŘI (6 jmen) + organizátor doplní odkaz.

## B1 (2× — MISLABELED, ve skutečnosti VZP G3 foto; kvanta = foto/team-interpretace)
12. `111157115` — AI podpora JIP: alarmy, signál jako informace, Beth Israel
    130k pobytů / TRV 246k hodin / SIGN 9 signálů, FN Brno 1 799 hospitalizací
    / 31 551 pacientodnů, predikce délky hospitalizace.
13. `111252835` — datový model A/B/C (event-log → prognóza → odchylky),
    MIMIC-IV (adult ICU analogie) + FN Brno, výzva: model + signalizace + UI; proaktivní signalizace,
    jisté předání lékaři, souhrn za hospitalizaci.

## G4 (2× — MISLABELED, ve skutečnosti VZP G3 foto)
14. `111401212` — AI pomocník: 3 bolesti (hledání napříč systémy, alert
    fatigue bez kontextu, roztříštěný přehled) → jeden vyhledávací řádek,
    klinický kontext, souhrny/časové osy. Abrahámová (Solution Partner).
15. `111446700` — INPUTY–VÝSTUPY: FHIR + OMOP (+SNOMED/LOINC/MedDRA/ATC),
    klienti TrakCare/IntelliCare/HealthShare → FHIR úložiště + AI-ready
    vrstva + jednotný obraz pacienta. Footer: základy / nad klinikou /
    pacientská cesta.

---
---

# PŘÍLOHA C — ZKRATKY (rychlý tahák)

- **Péče:** PL praktik, KOC/ROC, MDT (porada), K1/K2/K3 (před/během/po),
  T1/T2/T3 (úseky času do léčby), HPB (hepato-pankreato-biliární),
  NOR/ISNO (registr), ROS (regionální skupiny), PIN (navigace USA).
- **Data:** NIS/AIS/LIS/RIS/PACS, EZD/EHR, SZZ, NPEZ/EZKarta, DU (úložiště),
  NCEZ/NZIS/ÚZIS/KZP, DASTA, NCPeH/MyHealth@EU/EEHRxF, AAfD, HCID.
- **Standardy:** HL7 V2/CDA/FHIR (R4), IG/Profile/ValueSet/CodeSystem,
  MKN-10/ICD, LOINC/NČLP, SNOMED CT, DICOM, mCODE, ECCDM/CCM, EU Base,
  CZ Core, IHE MHD (ITI-65/66/67/68), MHDS, PDQm/PIXm/PMIR, mCSD, IUA/ATNA,
  DSUBm, XTB-WD (PCC), XDS-I.b, SBAR, OMOP, MedDRA/ATC.
- **FHIR:** Patient, Encounter, Condition, Observation, DiagnosticReport,
  Specimen, ImagingStudy, Procedure, MedicationRequest/Administration,
  CarePlan, CareTeam, Task, Appointment, ServiceRequest, Communication,
  DocumentReference, Provenance, AuditEvent, Subscription, Flag,
  DetectedIssue, QuestionnaireResponse, RiskAssessment, MolecularSequence,
  Bundle, EpisodeOfCare, OperationOutcome.
- **InterSystems:** IRIS for Health, Health Connect/Share, TrakCare,
  IntelliCare, SDA, DTL, SQL Builder, Bulk FHIR ($export), HNSW/Vector,
  RAG/MCP, AI Hub (EAP), SMART on FHIR.
- **ML:** Cox PH, RSF, DeepSurv, SHAP, RAG, HNSW.
- **Soutěž:** G1/G2/G3/G4, B1, KDP/NIKEZ, PUK, INDIKO, NZIP, DRG,
  51881/51885/51887, VZP/KZP, MOU, FN (Brno/Olomouc/Ostrava/Plzeň/Hradec/
  Motol/Bulovka/Vinohrady/Thomayerka), VFN, LF, VUT, ČVUT/FBMI, IPVZ,
  MZD/MZ, ÚOOÚ, SÚKL/CÚER, ČSSZ, NPO/IROP, EHDS/HDAB, MDR/IVDR, DPIA,
  RBAC, PKCE/JWT/OIDC, SLA/ACK, HoF/PHOENIX/XiA, APIM/RG/Copilot.

---
---

# PŘÍLOHA D — STARŠÍ MEETINGY + VÝZKUMY (stručně, detaily v původních vláknech)

## D1 Ranní meeting 072521 (teorie, Opatřil + Kružík)
- EHDS 2 řeky (primární péče / sekundární výzkum), fáze 3/2029 souhrn+eRecept/eVýdej
  → 3/2031 lab+obraz+propouštěcí+genomika → 3/2035 třetí země; 6 prioritních kategorií (bez ZZS).
- FHIR R4 základ EU (R5 STU / R6 snapshot); CZ profily hl7.cz; DASTA "zapomeňte
  pro nový vývoj"; kmenové registry (ověřovat, nestavět vlastní DB pacientů);
  MHD publish/index/find; terminologie SNOMED (mimo NČLP) vs LOINC ~85 % (bez zdroje).
- TNM jen solidní nádory; pre- vs post-koordinace; nová eŽádanka centrálně.
- Vítězný tým 19. 10. IPVZ; 16.–20. 11. Malaga (Common Cancer Model den).
- Chat: FHIR token až odpoledne; "nápad vs provedení" bez odpovědi.

## D2 Odpolední meeting 105031 (MSFT + InterSystems G4 + Phoenix)
- Data až ráno při startu (Slack kanál výzvy); veřejná data OK; boilerplate
  povolen s deklarací; submissions veřejné všem.
- Azure RG per tým (Contributor only), modely přes 1 endpoint + klíč,
  ~100–200 USD/tým, Copilot licence; 429 backoff; lokál stačí; Azure/G4 stack
  bez vlivu na hlavní hodnocení (jen na cenu partnera).
- G4 cena 1 500 € (ne 15 000 €): IRIS multimodel + Vector v SQL + 1-klik FHIR repo (R4);
  FHIR Hackathon Kit (docker + Jupyter: CSV→IRIS, FHIR CRUD, Bundle,
  FHIR→SQL, embeddings+RAG, LangChain); začít s FHIR hned; reálné NIS nebude
  (lokální simulace); přednahraná data smazat.
- Phoenix (Luc Chatty): prototyp ≠ vítězství — test = druhá nemocnice rozumí
  bez rebuildu; "We store JSON ≠ interoperable"; 6 pravidel pro 48 h
  (workflow → kontrakty → kódy → trust → test mimo demo → sdílej artefakty);
  PHOENIX spec build.fhir.org/ig/hl7-eu/cancer-common; SYNDERAI syntetika.
- Chat: Entra ID není, boilerplate ano, lokál stačí, 20 subagentů = plýtvání,
  cloud LLM jen se souhlasem zadavatele (syntetika OK), minulí vítězové =
  využití dat/FHIR + inovace nad zadání + dopad.

## D3 Co chtějí doktoři (TOP z rešerší — plné verze ve vláknech)
- MDT must-have: kompletní dokumentace předem; povinná pole/proforma +
  deadline; fixní členové per dg; kvórum řídí předseda + evidence účasti;
  video-připojení; písemný závěr + sdílení (lékař/praktik/pacient); záznam
  neshody i nereferování; role předsedy + koordinátora; urgentní referály;
  auditovatelnost. (NIKEZ KDP 20, Věstník 11/2025, NZ 2024, NHS 95 %.)
- Dealbreakery: případ bez patologie/imagingu; clear-cut případy na MDT;
  přetížené porady (<2 min/pacient); vágní závěry; chybějící radiolog/patolog
  bez náhrady; závěr co zapadne; jen in-house; návrh mimo úhradu SÚKL;
  únik dat / neoprávněná účast.
- Důvěra v AI: citace u každého tvrzení; klinický narativ (ne SHAP heatmapy);
  kontrafaktuál; kalibrovaná confidence (zelená/oranžová/červená); kvalita
  vstupů; AI jako návrh + snadný override s důvodem; audit stopa; žádný
  hromadný Accept-all; trénink (AI literacy); transparentnost validace/limitů;
  feedback loop; doménová relevance (guidelines NCCN/ESMO).
- Koordinátor TOP potřeby: jasné kompetence+hranice; podpora vedení;
  přehled kapacit/čekacích dob (hlavně zobrazovací); jednotná platforma
  KOC–ROC + jednotná databáze pacientů; tracking cesty + SLA;
  mechanismus potvrzení převzetí (dnes chybí!); "červené tlačítko" pro region;
  úhrada (250 Kč za výkon — bodová hodnota 0, úhradová vyhláška 2026 bod 8.5);
  supervize; vzdělávání + Asociace (Discord, mapa).
- Den koordinátora: referrace od lékaře → písemné vyžádání → objednává
  konzilia/CT/operace → proaktivně dohledává výsledky/termíny → hlídá MDT →
  komunikuje (PL, ambulance, sestry, diagnostika, pacient) → vyplňuje
  formuláře (MOU žádost: žadatel + pacient + dg/TNM/histologie/grade + PACS +
  cíl) → edukuje (MOU 1 200/rok). Kde ztrácí čas: telefony, termíny CT,
  kompletace zpráv, předávání mezi pracovišti, nedůvěra lékařů, administrativa
  (KOC–pojišťovna–pacient), doprava, psychická zátěž.
- KOC↔region: ROS + smlouvy + protokoly + jednotná online platforma
  (požadavek, ne realita); delegovaná preskripce (MDT v KOC → podání v ROC →
  reporty zpět → při neúčinnosti návrat); krajský koordinátor MOU (termíny
  v Brně + kraji, předání po dg., neodpovídá za medicínu); bariéry AIFP:
  sdílení ZD #1, "zkoordinovat KOC–pojišťovna–pacienta někdy nemožné",
  administrativa, chybějící smlouvy; volání po jednotné databázi.
- Doprava: ZDS jen ze zdravotních důvodů (PKZT VZP-34, indikuje lékař);
  hrazeno do nejbližšího smluvního; doprovod/dvouposádka/140 kg+ pravidla;
  propustka se nehradí; soukromé auto §37 (VZP-39); lékaři často neuznají
  únavu/nevolnost; koordinátor řeší 2h dojíždění nemožné bez doprovodu.

## D4 Demo-dashboard mock data (co je dnes v :8084)
- 6 pacientů (Nováková/Svoboda/Dvořáková/Malý/Horáková/Veselý; C50/C34/C18;
  MOU/FN Brno/KOC Zlín/Olomouc); P4 ztracená histologie (SLA −3 h);
  P6 nepřevzatá péče (Olomouc); 4 záložky (fronta/detail/MDT/B1);
  FHIR badge všude; `var PAC` jeden globál = MOCK (cílový stav: rozsekat na B1–B7).

---
---

# PŘÍLOHA E — DEMO SCÉNÁŘ A PITCH (pracovní návrh)

## E1 Demo flow ~4 minuty (Pan Novák + 1 neúplný případ)
- **0:00–0:30 Fronta:** 6 pacientů seřazených dle priority; Novák (HPB, T2
  běží, MDT 13. 1. za 2 dny); červený řádek: chybí TM výsledek, SLA −3 h.
- **0:30–1:10 Referování bez formuláře (bod 1):** PL nahraje 2 PDF na 2 kliky;
  B1 je přeloží do FHIR Bundle + `$validate`; OperationOutcome prázdný.
- **1:10–1:50 AI vytěžení + kontrola (bod 2):** extrakce (datum, UZ/CT/TM,
  histologie, stent, MDT termíny) — každé pole citace + confidence;
  chybějící TM = červený Flag "čeká na doplnění"; druhý případ ukáže
  negovaný nález ("není metastáza" ≠ "chybí výsledek").
- **1:50–2:30 Přehled + vlastník (body 3–4):** T1/T2/T3 bary, semafor,
  vlastník každého kroku + ACK stav; eskalace: region nepotvrdil 48 h (demo práh) →
  ping koordinátorovi.
- **2:30–3:20 MDT + závěr (bod 5):** completeness gate (histologie + staging
  + onkozpráva; povinná trojice per návrh, ne norma), kvórum (numericky nedokládat), SBAR souhrn s proklikem na zdroj, hlasy →
  Provenance, výstup Tasky.
- **3:20–4:00 Zpětná vazba (bod 6, FINÁLE):** referující PL dostane výsledek
  s původním kontextem (one-click), revizní lékař automaticky s AI tříděním;
  potvrzení předání → případ uzavřen; audit stopa na obrazovce.
- **G4 vsuvka 30 s (kdykoliv):** stejná data přes FHIR REST + SQL Builder
  SELECT (důkaz "stejná data dvěma cestami"); přepnutí base URL = druhá
  nemocnice; Vector RAG dotaz s citací ("Má pacient histologii?").

## E2 Pitch 3 minuty (celý tým, netechnické + zdravotní publikum)
- **0:00–0:20 Hook:** ">50 % lidí s karcinomem plic se k léčbě dostane pozdě (prs/pankreas nedokládat).
  Ne vinou nemoci, vinou systému. Pan Novák (ILUSTRATIVNÍ) měl štěstí — měl koordinátorku."
- **0:20–1:00 Problém:** 3 místa ztráty (vstup/KOC/výstup); koordinátoři dnes
  telefon + papír; MDT bez podkladů; smyčka se neuzavírá.
- **1:00–2:10 Demo:** 6 bodů na Novákovi (zrychleně 90 s) + krok 04 finále
  (potvrzené předání); T-metriky; "princip, ne integrace".
- **2:10–2:40 G4 + bezpečnost (TARGET; TODAY = MOCK):** FHIR úložiště + AI-ready vrstva; IDs-only AI
  s kill-switchem (MOCK); GDPR matice rolí (TARGET, TODAY návrh).
- **2:40–3:00 Dopad + next:** čas do léčby −týdny, koordinátor +hodiny denně;
  pilot VFN HPB; fast-track VZP; "jedna diagnóza dnes, všechny zítra".
- Každý člen týmu má 1 blok (~30 s); záložní video kdyby padla wifi;
  poděkování mentorům se správným spellingem (ověřit!).

## E3 FHIR kostra případu (ilustrativní MOCK, R4 + CZ Core; SMART/RBAC/audit = TARGET)
- Patient (Novák, pseudonym v demu) → Encounter (hospitalizace 7. 1.) →
  Condition (C25 tumor slinivky, staging) → Observation (TM, histologie) →
  DiagnosticReport (CT 12. 1.) + ImagingStudy → Procedure (stent 9. 1.,
  operace 26. 1.) → ServiceRequest (eŽádanka CT) → CarePlan (z MDT 13./20. 1.)
  + CareTeam (onkolog/chirurg/radiolog/patolog/koordinátor) + Tasky
  (vlastník+termín+ACK) → DocumentReference (MDT zpráva) → Communication
  (krok 04 referujícímu) + Provenance (hlasy) + AuditEvent (vše) +
  Flag (chybí TM) + RiskAssessment (jen B1 paralela).

---
*Konec master contextu (vč. příloh A–E). Při změně plánu aktualizovat
příslušnou kapitolu a datum nahoře. Jedna diagnóza, šest bodů dema,
princip ne integrace. Hodně štěstí Brnu na finále.*
