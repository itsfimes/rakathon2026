# RAKATHON 2026 — MASTER CONTEXT

> Jediný source of truth: `challange_context/` — 12 .txt přepisů + 15 fotek v `prezentace/`.
> Co tam není, je vyhozeno a nahrazeno větou `MIMO SOURCE — vyhozeno (nedokládat)`.
> Tým staví **G3 (VZP Cesta pacienta) s přesahem do G4 (InterSystems)**.
> Aktualizováno: 16. 10. 2026.

---

---

# 1. PROJEKT V KOSTCE

- **Naše volba:** hlavní výzva **G3 (VZP Cesta pacienta)**, technologický přesah **G4 (InterSystems)** — dva acceptance testy jednoho produktu (rozhodnutí týmu).
- **B1 (FN Brno outlier)** technicky nestavíme; jen OUT-scope kontext, viz kap. 5 (rozhodnutí týmu; `FN Brno - outlier.txt`).
- MIMO SOURCE — vyhozeno (nedokládat).

## 1.1 Výzvy

### G3 — Cesta pacienta bez ztráty informací (VZP, hlavní)
> Sdílený případ onkologického pacienta: propojit lékaře, koordinátora a KOC, vytěžit data z dokumentace, hlídat podklady, termíny a odpovědnosti, předat výsledek MDT. Cílem je rychlejší cesta pacienta a méně administrativy.
> Zadavatel: Všeobecná zdravotní pojišťovna ČR. (parafráze zadání; `VZP 3.txt:00:11:22–00:12:20` + `foto111105250`)

### B1 — Když realita překoná prognózu (FN Brno, NESTAVÍME)
> Hledat pacienty, jejichž průběh se výrazně liší od očekávaného, a srozumitelně vysvětlit možné příčiny — podklad pro diskusi, ne predikce čerstvého pacienta ani triáž. (`FN Brno - outlier.txt:00:44:34–00:01:12` + `09:44–10:07`)

### G4 — Technologie InterSystems (side-challenge)
> Technologická výzva ke kombinaci s kteroukoli hlavní výzvou (`Intersystems.txt:03:48–04:00`). Cena **1 500 €** (meeting `105031_Recording.cc.vtt` 01:37:02 challenge web + ASR garble „patnáct 100 €"; v `Intersystems.txt` přepisu nedoloženo — ověřit u stánku). FHIR server k dispozici + lokální simulace interoperability v IRISu, FHIR R4 (meeting `105031_Recording.cc.vtt` 01:34:27–01:38:33; v `Intersystems.txt` přepisu nedoloženo). Data na FHIR převést přes REST (meeting `105031_Recording.cc.vtt` 01:42:39–01:43:32); začít rovnou s FHIR = rozhodnutí týmu (návrh, ne požadavek zadání). Věcně: FHIR úložiště + AI-ready vrstva + jednotný obraz pacienta (`foto111446700`). Rada: nedělat 100 agentů najednou — jednoduše, realizovatelně (`Intersystems.txt:00:12–00:16`); připravit datové rozhraní/protokol (`Intersystems.txt:00:20–00:28`).

---

---

# 2. G3 — PŘESNÉ ZADÁNÍ (VZP 3 + fotky)

Přednášející trojice: Rybář (MZ / poradce ministra, data) + Bielčíková (onkoložka) + Vaňková (živá koordinátorka) (`VZP 3.txt:00:00:35–00:01:02`; jména spelling OPEN — ASR přepis dává Ryba/Krástová/Wenková/Bělčíkova, ověřit, `VZP 3.txt:00:00:16–00:00:35`).

## 2.1 Motivace
- Více než polovina lidí s karcinomem plic se k léčbě nedostane dříve než do 8 týdnů (`VZP 3.txt:00:01:12–00:01:22`); mezitím přechod stadia 1–2 → 3–4, tedy z léčitelného do neléčitelného (`VZP 3.txt:00:01:22–00:01:35`).
- Nemůže za to nemoc ani příhoda — může za to systém, který neumí koordinovat pacienta včas k léčbě (`VZP 3.txt:00:01:35–00:01:42`).
- Časná stadia stojí ~50 tisíc, pozdní mnohonásobně víc (`VZP 3.txt:00:01:47–00:01:52`, slide).
- VZP s MZ spolupracuje na hrazení výkonů koordinátora (`VZP 3.txt:00:02:36–00:02:43`).
- MIMO SOURCE — vyhozeno (nedokládat).

## 2.2 Čtyři úkoly softwaru
1. **01 PŘEVZÍT** — vzít existující dokumentaci z ambulance referujícího lékaře a převzít ji bez vytváření dalšího rozsáhlého formuláře, s nejmenší prací (`VZP 3.txt:00:06:14–00:07:56` + `00:07:48–00:07:56`; `foto111105250`).
2. **02 VYTĚŽIT** — AI dokumentaci přetřídí do předem připraveného strukturovaného dokumentu; lékař ho zkontroluje, schválí a odešle koordinátorovi (`VZP 3.txt:00:08:44–00:09:04`); koordinátorovi se ukáže, co chybí a co je třeba dodělat (`VZP 3.txt:00:06:52–00:07:00`).
3. **03 KOORDINOVAT** — koordinátor vidí stav případu (nový / v řešení / čeká na doplnění), termíny a kdo má odpovědnost (`VZP 3.txt:00:09:30–00:10:18`); systém umí zpětně kontaktovat referujícího lékaře pro doplnění (`VZP 3.txt:00:09:06–00:09:14`).
4. **04 PŘEDAT ZPĚT** — po MDT vznikne zpráva/postup, koordinátor ji předá zpět referujícímu (často praktikovi) lékaři, aby se dozvěděl, jak to s pacientem bude dál (`VZP 3.txt:00:10:56–00:11:20`); před MDT systém připraví sumář informací, ze kterého se rozhoduje (`VZP 3.txt:00:10:22–00:11:20`) (`foto111500856`); větev + revizní lékař (dostane informaci automaticky) (`foto111500856`).

## 2.3 Metrika: čas do léčby = T1 + T2 + T3
- Cesta: symptom → diagnostika → MDT → léčba; každý interval má svou časovou jednotku a pro pacienta platí, že čím kratší čas, tím větší šance na vyléčení (`VZP 3.txt:00:03:34–00:04:18`).
- Vzorec **T1+T2+T3**, osa Symptom —T1→ Diagnostika —T2→ MDT —T3→ Léčba, role PL/SPECIALISTA → KOC/ROC → KOC → KOC/ROC; koordinátor K1 hlídá čas do léčby (`foto110756242` + `foto110909696` titulek `Koordinátor K1 hlídá čas do léčby`).
- MIMO SOURCE — vyhozeno (nedokládat).

## 2.4 Problém na třech místech
1. **Na vstupu:** praktici posílají dokumentaci neúplně; koordinátor tráví většinu času dohledáváním dat po republice místo koordinace (`VZP 3.txt:00:05:20–00:05:48`).
2. **Uvnitř KOC:** shánění termínů a výsledků, příprava MDT bez kompletních podkladů (`VZP 3.txt:00:05:20–00:05:48`; `foto111001429`).
3. **Na výstupu:** referující lékař se nedozví, jak MDT rozhodlo, a pacient s ním zůstává dál (`VZP 3.txt:00:11:04–00:11:20`; `foto111001429`).

## 2.5 Ideální řešení (akceptační kritéria UI)
- Aplikace, kde lékař na první pohled vidí prioritu pacienta, vybere ho a nahraje zprávy s minimem práce (`VZP 3.txt:00:07:28–00:07:56`).
- Koordinátor vidí stav, termíny a odpovědnost za každý krok (`VZP 3.txt:00:10:04–00:10:18`); tři sloupce seznam / přehled / reporting (`foto111058433`).

## 2.6 Demo MUSÍ ukázat (6 povinných bodů)
1. Referování pacienta do KOC bez dalšího formuláře (krok 01).
2. AI vytěžení s kontrolou úplnosti (krok 02).
3. Přehled případů se stavem a termínem (krok 03).
4. Vlastník každého dalšího kroku (krok 03).
5. Strukturovaný závěr KOC/MDT (krok 04).
6. Zpětná vazba a potvrzené předání (krok 04).
(`foto111603561`; body 1–6 jsou parafrází kap. 2.2)
- **Výstup: jedna diagnóza a funkční demo. Rakathon ověří princip, produkční integrace patří do další fáze.** (`foto111603561`)

## 2.7 Referenční případ Pan Novák (ILUSTRATIVNÍ)
- Pan Novák 60 let: 5.1.2026 zežloutnul → volá PL; 6.1. UZ břicha (tumor slinivky) + PL aktivuje koordinátora KOC; 7.1. hospitalizace; 9.1. stent do žlučových cest + histologie; 12.1. CT, TM; 13.1. 1. MDT, 20.1. 2. MDT; 26.1. operován (`foto110909696`).
- Celý příběh včetně dat je **ILUSTRATIVNÍ zjednodušení, ne medián reálné praxe** (`foto110909696`; `VZP 3.txt:00:04:30–00:04:38` „jak to může vypadat", `VZP 3.txt:90-91`). 5.1.→26.1. = 21 dní je (demo součet z dat slajdu, ne norma).
- Kontakt `koordinace-hpb@vfn.cz` — přímo na slajdu (`foto110909696`); hbp jen v próze: OPEN, nehardcodovat, ověřit u garanta.
- Pilot VFN HPB = testovací persona/data; koordinátor KOC/ROC, lékař i nelékař (`foto110632387`).
- MIMO SOURCE — vyhozeno (nedokládat).

## 2.8 Kdo je koordinátor (obecná role K1, bez K2/K3 splitu)
- Koordinátor K1 hlídá čas do léčby — fáze K1 = před léčbou (`foto110909696` titulek; K2 = během léčby, K3 = po léčbě jsou fáze osy, ne separátní role pro demo).
- Člověk, který už od prvního podezření provází pacienta systémem; může sedět kdekoliv, tzv. při KOC / komplexním onkologickém centru (`VZP 3.txt:00:02:01–00:02:11`).
- Praktik s podezřením často neví kam dál → referuje koordinátorovi, ten pacienta provede systémem rychle, dokud je rakovina léčitelná (`VZP 3.txt:00:02:15–00:02:31`).
- KOC nově odpovídají za to, aby se pacient dostal včas k léčbě (`VZP 3.txt:00:03:22–00:03:34`); koordinátor dělá veškerou organizační práci kolem diagnostiky (`VZP 3.txt:00:03:56–00:04:02`).
- Diagram: LÉKAŘ → [odeslání] → KOORDINÁTOR → časová osa → PACIENT (`foto110632387`).
- MIMO SOURCE — vyhozeno (nedokládat).

## 2.9 Ostatní VZP výzvy (kontext, NESTAVÍME)
- **VZP 1 (konec života):** transparentní nástroj kvality péče na konci života; indikátory léčby 30/14 dní před smrtí, radioterapie v závěru, čas od poslední léčby; indikátor ≠ kvalita — interpretovat v kontextu, neostrakizovat (`VZP 1.txt:01:10–02:10` + `03:40–05:00`).
- **VZP 2 (mamograf):** zvýšit účast screeningu; papírové pozvánky přežitek; 44,5 % oslovených 2024 nepřišlo; 4 otázky KDO/PROČ/CO/JAK ověříme; dataset + slovník; segmentace → intervence → experiment (`VZP 2.txt:02:07–05:00` + `07:44–09:15`).
- **VZP💥 (adherence + koordinace):** zvednout adherenci k prevenci; koordinátoři dnes "tužka, papír, telefon, maily"; řízený vstup inovací `inovace.vzp.cz` — dobré řešení do praxe, ne do šuplíku (`VZP💥💥💥.txt:00:30–01:15` + `02:34–03:05`).

---

---

# 3. HODNOCENÍ A ORGANIZACE

## 3.1 Kritéria (`Organizace, kriteria hodnocení.txt`)
- **Sobota — neformální walkthrough, NE pitch na stagi:** mentoři obcházejí týmy (`00:01:45–00:02:03`). Tři kritéria: (1) produkt/technologie — funguje, dává tech smysl, zajímavé využití AI, impressive za 24 h (`00:06:13–00:06:41`); (2) využitelnost v praxi — splnění zadání partnera, realistická nasaditelnost, GDPR/security, reálné nemocniční systémy (`00:06:48–00:07:17`); (3) inovativnost — originální spin, odlišení od konkurence (`00:07:33–00:07:59`).
- **Neděle — jen postupující, formální pitch:** (4) škálovatelnost / dlouhodobý potenciál (`00:08:21–00:08:54`); (5) kvalita prezentace a týmu — **3 minuty pitch** pro netechnické i zdravotní publikum (`00:09:08–00:09:26`).
- **Na stage jde celý tým — prezentují všichni** (`VZP 3.txt:00:00:12–00:00:16`; memo-only; v `Organizace.txt` nedoloženo — garbled).
- MIMO SOURCE — vyhozeno (nedokládat).

## 3.2 Logistika (Brno)
- **Dnes v 19:00** deadline potvrdit výzvu + složení týmu, jinak nelze postoupit (`Organizace.txt:00:00:42–00:01:00`).
- Přespání na místě (karimatky, vyhrazená místnost); ráno restart ~8:00 (`Organizace.txt:00:01:07–00:01:25`).
- Odevzdání přes submit formulář: popis projektu + popis týmu + odkazy/repo/obrázek (`Organizace.txt:00:02:32–00:02:51`; URL v přepisu garbled — ověřit na místě).
- Komunikace: Slack — hlavní kanál + kanál výzvy (`Organizace.txt:00:03:14–00:03:37`).
- Každá výzva posílá **1 vítěze do celostátního finále v Praze**; společný vlak zdarma + proplacení cesty zpět (`Organizace.txt:00:03:48–00:03:59`).
- Azure: vlastní Resource Group per tým, role Contributor (RBAC/Key Vault dotaz v chatu bez písemné odpovědi — ověřit na místě); modely přes sdílený APIM endpoint — výběr z portálu (per MSFT demo např. gpt-6.1-sol/astra/luna, grok-4.7, DeepSeek-V4-Pro, Kimi-K2.7-Code, MAI-Thinking-1; přesné deployment názvy viz portál, v repo nedoloženo — ověřit v portálu); budget ~100–200 USD na tým (meeting `105031_Recording.cc.vtt` 00:46:51–00:47:07 + 00:56:27–00:56:49; není garantováno — ověřit aktuální limit v portálu); použití Azure nemá vliv na hodnocení výzev (meeting `105031_Recording.cc.vtt` 01:07:41–01:09:12 „Ne, nemá" — mluvená odpověď na chat dotaz; vendor ceny MS/InterSystems výjimkou); demo stačí na lokále (chat MSFT: „stačí lokál").
- MIMO SOURCE — vyhozeno (nedokládat).

## 3.3 Ceny a motivace (`Vzp meta.txt`)
- **100 000 / 50 000** + hodina s generálním ředitelem + šance dostat se do inovačního fast-tracku (`00:00:14–00:00:36` + `00:00:42–00:00:47`).
- Vzkaz: nemyslet jen "soutěž měst", zamakat; přemýšlet, co s projektem dál i bez výhry (`00:00:05–00:00:14` + `00:01:04–00:01:18`).

## 3.4 Lidé a kontakty
- G3 přednášející: Rybář + Bielčíková + Vaňková (`VZP 3.txt:00:00:35–00:01:02`; spelling vs ASR Ryba/Krástová/Wenková/Bělčíkova — ověřit); mentoři a konzultanti + podklady viz `foto111701186` a `foto111105250`.
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 4. B1 DETAIL (kontext, NESTAVÍME — rozhodnutí týmu)

- Hledat outliery — pacienty lepší/horší, než standard čeká; motivace Jenner / Semmelweis / Fleming (`FN Brno - outlier.txt:01:28–04:40`).
- 3 propojené anonymizované soubory (pacienti + nádory + epizody péče/cesta) + vybrané laborky; popisky nejasné, počítat s datovým průzkumem (`FN Brno - outlier.txt:06:48–08:40`).
- **Interpretovatelnost povinná**; nejde o predikci čerstvého pacienta ani triáž, ale o podklad pro diskusi: projít 4 kroky, ověřit, vysvětlit proč, navrhnout další kroky (`FN Brno - outlier.txt:08:40–10:07`).
- Brno intro: tlak na efektivitu, AI klíčová; ekonomika rozhoduje — řešení musí být ekonomicky udržitelné (`Brno intro.txt:09:43–10:20`).
- onkozro / fnmh / prodekan: nespolehlivé přepisy, pro G3 bez akčních bodů (`onkozro.txt`, `fnmh.txt`, `prodekan.txt`).
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 5. MEDICÍNSKÝ SLOVNÍK

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 6. SYSTÉMOVÝ PLÁN (G3 + přesah G4) — směr týmu, detail viz `architecture.md`

- **B1 Ingest:** nahrání existující dokumentace bez formuláře → FHIR Bundle (`VZP 3.txt:00:06:14–00:07:56`; mapování do Bundle = návrh G4/IRIS design, not VZP requirement).
- **B2 Koordinační jádro:** fronta případů se stavem, termínem, vlastníkem a ACK; T1+T2+T3 (`VZP 3.txt:00:09:30–00:10:18`; `foto110756242`; Task.owner = K1/KOC fronta, diagnostik = performer via ServiceRequest — návrh týmu).
- **B3 Dashboard:** jeden přehled, role-view (`?role=` mock, návrh týmu; `foto111058433`).
- **B4 MDT:** sumář pro rozhodnutí + zpráva zpět referujícímu i reviznímu lékaři (auto) (`VZP 3.txt:00:10:22–00:11:20`; `foto111500856`); completeness gate + kvórum + SBAR + Provenance = interní návrh týmu, not VZP term (povinná trojice není norma — říct porotě i v demo scriptu).
- **B5 Hlídací pes:** hlídání termínů; práh 48 h (demo práh, ILUSTRATIVNÍ, návrh, ne norma) / 7 d (demo práh, ILUSTRATIVNÍ, návrh, ne norma) = demo prahy týmu, ne normy (návrh týmu).
- **B6 AI agent:** vytěžení + kontrola úplnosti s human-check (`VZP 3.txt:00:08:44–00:09:04`; AI koncept grounded `VZP 3.txt:142-156` + `:190-218`); default OFF, IDs-only, kill-switch (návrh týmu).
- **B7 Přístup a audit:** v demu MOCK; produkční RBAC/GDPR mimo scope dema (rozhodnutí týmu; řekni porotě nahlas).
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 6A. VIZE TÝMU (TARGET — [NÁVRH TÝMU], není zadání VZP 3)

> Tato kapitola je unikátní vize týmu, jasně oddělená od přesného zadání VZP 3 v kap. 2. Citace k `challange_context/` zachovány tam, kde existují; zbytek je označen [NÁVRH TÝMU].

## 6A.1 Důraz InterSystems (G4) [NÁVRH TÝMU]
- **FHIR R4 server** [NÁVRH TÝMU]: CRUD + Bundle transaction + `$validate` (pipe syntax) + `$everything` (Patient/Encounter) + `$find`/`$lastn`/`$expand` — základ úložiště; FHIR server k dispozici + lokální simulace v IRISu (`meeting 105031_Recording.cc.vtt 01:34:27–01:38:33`; kombinace s hlavní výzvou `Intersystems.txt:03:48–04:00`).
- **Bulk `$export` async ndjson** [NÁVRH TÝMU]: export kohorty bez blokování FHIR REST.
- **SQL Builder bez přesunu dat** [NÁVRH TÝMU]: Analyze → Spec → Projection nad stejným úložištěm (`FSB_Data_Steward`, `/csp/fhirsql`); FHIR úložiště + AI-ready vrstva (`foto111446700`).
- **Vector Search** [NÁVRH TÝMU]: typ VECTOR + HNSW Cosine + `VECTOR_COSINE` (-1..1) pro RAG s citací.
- **Production** [NÁVRH TÝMU]: BS/BP/BO + adaptéry HTTP/SOAP/File/FTP/TCP/SQL/Kafka + DTL transformace.
- **SDA** [NÁVRH TÝMU]: HL7v2/CDA → SDA → FHIR, výstup jen R4.
- **MHD ITI-65/66/67/68** [NÁVRH TÝMU]: ověřit HealthShare, netvrdit podporu.
- **SMART 2.2 + IUA/ATNA** [NÁVRH TÝMU]: TARGET pro produkci, dnes MOCK (viz 6A.2).
- **PIXm/PDQm (`$match`)** [NÁVRH TÝMU]: stotožnění pacienta napříč zdroji.
- **MCP** [NÁVRH TÝMU]: `iris-agentic-dev`, `ai-hub-eap` b162, `Hackathon-Kit` jako AI nástrojová vrstva. Rada držet jednoduše, ne 100 agentů (`Intersystems.txt:00:12–00:16`); datové rozhraní/protokol (`Intersystems.txt:00:20–00:28`).

## 6A.2 Bezpečnost: E2EE ideál, poctivě [NÁVRH TÝMU]
- Ideál E2EE, poctivě: **E2EE jen client-side blob** [NÁVRH TÝMU]; jinak TLS + RBAC + audit + minimalizace.
- **IDs-only default** [NÁVRH TÝMU]: AI vidí jen pseudonymní ID; mapování na klientovi / B7 trezor.
- **Granularita 0=OFF / 1=souhrn / 2=plný** [NÁVRH TÝMU]: volitelná míra dat pro AI per nemocnice.
- **Kill-switch + SMART token + `audit.jsonl` MOCK** [NÁVRH TÝMU]: dnes MOCK, produkce SMART + vault + DPIA + audit (viz porotní věta 6A.8).

## 6A.3 Modularita: každý blok 2 konektory [NÁVRH TÝMU]
- Každý blok B1–B7: **IN protokol → OUT protokol** [NÁVRH TÝMU].
- **B1 jediný překlad proprietární↔FHIR** [NÁVRH TÝMU]; uvnitř B2–B6 jen FHIR↔FHIR přes IRIS. Nahrání bez formuláře (`VZP 3.txt:00:06:14–00:07:56`; `foto111105250`); mapování do Bundle = návrh.
- **B1 ingest** [NÁVRH TÝMU] → **B2 jádro** (Task + ACK + T1T2T3; stav/termíny/vlastník `VZP 3.txt:00:09:30–00:10:18`; T-osa `foto110756242`) → **B3 dashboard read-model** [NÁVRH TÝMU] → **B4 MDT gate** (sumář pro rozhodnutí + zpráva zpět `VZP 3.txt:00:10:22–00:11:20`; gate/kvórum = návrh) → **B5 watchdog** (demo prahy 48 h / 7 d, ILUSTRATIVNÍ návrh) → **B6 AI MCP** (`getPatientJourney`/`searchEvidence`/`explainFlag`/`draftSBAR`) [NÁVRH TÝMU] → **B7 identita/audit/trezor** (dnes MOCK) [NÁVRH TÝMU].

## 6A.4 Ease of use: jedna dashboarda [NÁVRH TÝMU]
- **Jedna dashboarda, stejná data unless GDPR** [NÁVRH TÝMU]; role-view tlačítkem `?role=` (MOCK); tři sloupce (`foto111058433`); stav/termíny/vlastník (`VZP 3.txt:00:10:04–00:10:18`).
- **Spotlight plain jazyk per role** [NÁVRH TÝMU]: modal jen severe + confidence ≥ 0,85 + akce do 24 h, jinak jen badge.
- **Max 2 kliky** [NÁVRH TÝMU]; fronta ve sloupcích **Priorita | Pacient | Fáze | Další+vlastník | Due | Status** [NÁVRH TÝMU].

## 6A.5 AI: vždy available [NÁVRH TÝMU]
- AI **vždy available** jako volitelný agent, **hosting per nemocnice** (lokál/trusted) [NÁVRH TÝMU]; před-připraví dokument, člověk zkontroluje/schválí/odešle (`VZP 3.txt:00:08:44–00:09:04`).
- **Volitelná míra dat, default IDs-only** (viz 6A.2) [NÁVRH TÝMU].
- **Confidence prahy 0,75/0,5 + citace** [NÁVRH TÝMU]: ≥ 0,75 návrh, 0,5–0,75 human-check, < 0,5 zahodit; každý výrok s citací (koncept grounded `VZP 3.txt:142-156` + `:190-218`).
- **Nikdy přímý write; forbidden auto-send/finalize a cloud s PII** [NÁVRH TÝMU].

## 6A.6 Per-role důležitost (vize persony = [NÁVRH TÝMU])
- **Praktik:** upload + závěr zpět bez formuláře (`VZP 3.txt:00:06:14–00:07:56` + `00:11:04–00:11:20`) [NÁVRH TÝMU: formulace persony].
- **K1:** fronta + eskalace, hlídá čas do léčby (`foto110909696` titulek; `VZP 3.txt:00:09:30–00:10:18`) [NÁVRH TÝMU].
- **Diagnostik-pracoviště:** Tasky s performer via ServiceRequest [NÁVRH TÝMU].
- **Onkolog:** SBAR sumář [NÁVRH TÝMU] (sumář pro MDT `VZP 3.txt:00:10:22–00:10:52`).
- **MDT:** kvórum + podpis [NÁVRH TÝMU].
- **ROC:** převzetí na ose (`foto110756242`) [NÁVRH TÝMU].
- **Pacient (Novák, ILUSTRATIVNÍ):** plain plán [NÁVRH TÝMU] (`foto110909696`).
- **Revizní lékař:** auto-export informace (`foto111500856`; `VZP 3.txt:00:10:56–00:11:20`) [NÁVRH TÝMU].
- **Sestra/dispečink:** konektor objednávek [NÁVRH TÝMU].
- **VZP:** agregace T-metrik (T1+T2+T3 `foto110756242`) [NÁVRH TÝMU].
- **IT:** RBAC/audit/kill-switch/baseURL (dnes MOCK) [NÁVRH TÝMU].

## 6A.7 Interní komunikace [NÁVRH TÝMU]
- **Production/DTL/SDA → FHIR REST → SQL Builder + Vector + Subscription/webhook + `$export`** [NÁVRH TÝMU].
- **G4 30 s:** REST vs SQL stejná data (bez přesunu), baseURL switch = 2. nemocnice, RAG s citací (meeting `105031_Recording.cc.vtt` 01:34:27–01:38:33; `foto111446700`) [NÁVRH TÝMU: scénář].

## 6A.8 G4 vsuvka + porotní věta
- G4 vsuvka 30 s kdykoliv v demu (viz 6A.7) [NÁVRH TÝMU].
- **Porotní věta (říct nahlas):** „Dnes princip na syntetikách bez reálného RBAC; produkce SMART + vault + DPIA + audit; prahy/gate/kvórum demo, ne norma." [NÁVRH TÝMU].

---

# 7. ROLE — KDO CO DĚLÁ V DEMU

- **Referující lékař (často praktik):** nahraje existující zprávy bez dalšího formuláře, s nejmenší prací; po MDT dostane výsledek zpět (`VZP 3.txt:00:06:14–00:07:56` + `00:07:48–00:07:56` + `00:11:04–00:11:20`; `foto111105250`).
- **Koordinátor:** vidí stav/termíny/vlastníka, dohledává podklady, připraví MDT, předá zprávu zpět (`VZP 3.txt:00:06:52–00:07:00` + `00:09:30–00:10:18`).
- **MDT + KOC:** projedná případ v multidisciplinárním týmu, vydá rozhodnutí/zprávu (`VZP 3.txt:00:10:22–00:11:04`).
- **Region (ROC):** role na ose cesty (`foto110756242`); detaily předání = návrh týmu.
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 8. EŽÁDANKA

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 9. FHIR ZDROJE A TERMINOLOGIE

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 10. ZDROJE V REPU (co kde leží)

- `challange_context/`: 12 .txt přepisů (complete) + 15 fotek v `prezentace/` (vše VZP G3). Priority: VZP 3 (zadání), Vzp meta (motivace), Organizace-kriteria (pravidla). OUT scope: VZP 1, VZP 2, VZP💥, FN Brno-outlier, Brno intro, onkozro, fnmh, prodekan. Klíčové fotky: `111105250` zadání, `110909696` Novák, `110756242` T-osa, `111001429` problém, `111058433` ideál, `111500856` krok 04, `111603561` 6 bodů dema, `111701186` podklady+mentoři, `111446700` FHIR/AI-ready.
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 11. LOKÁLNÍ ARTEFAKTY A NASAZENÍ

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 12. PLÁN NA 24 HODIN

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# 13. OTEVŘENÉ OTÁZKY (ověřit u organizátorů / mentorů / garantů)

1. E-mail KOC `koordinace-hpb@vfn.cz` — na slajdu (`foto110909696`); hbp jen v próze — OPEN, nehardcodovat, ověřit u garanta.
2. Podklady/datasety/slovník pro konkrétního pacienta — kde jsou a jsou live? (`VZP 3.txt:00:12:36–00:12:55`; `foto111701186`).
3. Přesné deadliny a submit: 19:00 confirm kde? submit URL v přepisu garbled (`Organizace.txt:00:00:42–00:01:00` + `00:02:32–00:02:51`).
4. Spelling jmen (Rybář vs ASR Ryba? Bielčíková vs Krástová/Bělčíkova? Vaňková vs Wenková? role) do prezentace (`VZP 3.txt:00:00:16–00:00:35`; `foto111701186`).
- MIMO SOURCE — vyhozeno (nedokládat).

---

---

# PŘÍLOHA A — VOICE MEMA PO JEDNOM (zdrojové shrnutí)

## VZP 3 (hlavní zadání G3)
- Trojice Rybář (MZ/data) + Bielčíková (onkoložka) + Vaňková (koordinátorka) (`00:00:35–00:01:02`; spelling vs ASR Ryba/Krástová/Wenková/Bělčíkova — ověřit).
- >50 % Ca plic k léčbě až po 8 týdnech; přechod stadia 1–2 → 3–4; chyba systému (`00:01:12–00:01:42`).
- Koordinátor od prvního podezření; praktik referuje koordinátorovi (`00:02:01–00:02:31`).
- Nahrání existující dokumentace bez dalšího formuláře, s nejmenší prací; AI před-připraví dokument ke kontrole/schválení/odeslání (`00:06:14–00:09:04`; `foto111105250`).
- Koordinátor vidí stav/termíny/vlastníka; zpětné kontaktování referujícího (`00:09:06–00:10:18`).
- Po MDT sumář pro rozhodnutí + zpráva zpět referujícímu (`00:10:22–00:11:20`).
- Prezentuje celý tým (`00:00:12–00:00:16`; memo-only; v `Organizace.txt` nedoloženo).

## Organizace, kriteria hodnocení (pravidla)
- 19:00 potvrdit výzvu + tým (`00:00:42–00:01:00`); nocleh na místě, ráno ~8 (`00:01:07–00:01:25`).
- Sobota walkthrough, 3 kritéria produkt/praxe/inovativnost (`00:01:45–00:02:03` + `00:06:13–00:07:59`).
- Neděle +škálovatelnost +3min pitch (`00:08:21–00:09:26`); submit formulář + Slack (`00:02:32–00:03:37`); 1 vítěz do Prahy, vlak zdarma (`00:03:48–00:03:59`).

## Vzp meta (motivace)
- 100k/50k + hodina s GŘ + fast-track; myslet co s projektem dál i bez výhry (`00:00:05–00:01:18`).

## Brno intro / FN Brno-outlier / VZP 1 / VZP 2 / VZP💥 / onkozro / fnmh / prodekan
- Viz kap. 2.9 a 4 (OUT scope, NESTAVÍME).

---

---

# PŘÍLOHA B — FOTKY (15×, `prezentace/`)

1. `101335066` — logo wall, věcně nic.
2. `110543910` — evoluce péče (kontext).
3. `110632387` — kdo je koordinátor (diagram + mail + pilot VFN).
4. `110756242` — T-osa T1+T2+T3 + role.
5. `110909696` — Pan Novák ILUSTRATIVNÍ.
6. `111001429` — problém na 3 místech.
7. `111058433` — ideální řešení 3 sloupce.
8. `111105250` — zadání pro týmy.
9. `111157115` — JIP/outlier kontext (B1).
10. `111252835` — datový model outlier (B1).
11. `111401212` — AI pomocník (bolesti → jeden řádek).
12. `111446700` — FHIR + OMOP → FHIR úložiště + AI-ready.
13. `111500856` — krok 04 předání výsledku.
14. `111603561` — co odevzdat: 1 diagnóza + 6 bodů dema, princip ne integrace.
15. `111701186` — podklady + mentoři.

---

---

# PŘÍLOHA C — ZKRATKY

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# PŘÍLOHA D — STARŠÍ MEETINGY + VÝZKUMY

MIMO SOURCE — vyhozeno (nedokládat).

---

---

# PŘÍLOHA E — DEMO SCÉNÁŘ A PITCH (pracovní návrh týmu, grounded kostra)

- Demo = 6 bodů z kap. 2.6 na Panu Novákovi (ILUSTRATIVNÍ), celý průchod od referování po potvrzené předání (`foto111603561`; `VZP 3.txt:00:11:22–00:12:20`); B4 gate/kvórum/SBAR + B5 prahy + `?role=` mock = interní návrh týmu, not VZP term — říct porotě nahlas.
- G4 vsuvka 30 s: stejná data přes FHIR REST i SQL; přepnutí base URL = druhá nemocnice; RAG dotaz s citací (meeting `105031_Recording.cc.vtt` 01:34:27–01:38:33; `foto111446700`; návrh týmu).
- Pitch 3 minuty, celý tým (memo-only; `VZP 3.txt:00:00:12–00:00:16`), pro netechnické i zdravotní publikum (`Organizace.txt:00:09:08–00:09:26`).
- MIMO SOURCE — vyhozeno (nedokládat).

---
*Konec master contextu. Jediný source of truth je `challange_context/` (12 .txt + 15 fotek). Jedna diagnóza, šest bodů dema, princip ne integrace.*
