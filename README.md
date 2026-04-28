# Boiler Solar Controller — Home Assistant Custom Integration

Integrare personalizată pentru Home Assistant care controlează automat două boilere electrice pe baza surplusului de energie solară. Când panourile fotovoltaice produc mai mult decât consumi, integrarea pornește rezistențele boilerelor ca să folosești energia gratuită în loc să o injectezi în rețea.

---

## Cuprins

- [Cum e structurat codul](#structura-codului)
- [Cum funcționează](#cum-functioneaza)
- [Entități create](#entitati-create)
- [Instalare](#instalare)
- [Configurare (setup wizard)](#configurare)
- [Setări ajustabile din dashboard](#setari-ajustabile)

---

## Structura codului

```
custom_components/boiler_ha/
├── __init__.py        — setup/teardown al config entry-ului, inițializează runtime store
├── config_flow.py     — wizard de configurare (3 pași) + options flow + reconfigure
├── const.py           — toate constantele: chei config, valori implicite, string-uri status
├── coordinator.py     — logica de control (DataUpdateCoordinator), polling + reactiv
├── number.py          — entități Number (slider/input) pentru setări ajustabile live
├── sensor.py          — entități Sensor: status text, temperatură, solar, rețea
├── switch.py          — entități Switch: „Control automat" per boiler
├── manifest.json      — metadata HACS/HA (domain, version, iot_class)
└── translations/
    ├── en.json        — etichete UI în engleză
    └── ro.json        — etichete UI în română
```

### `__init__.py` — Entry point

La `async_setup_entry` se inițializează un **runtime store** în `hass.data[DOMAIN][entry_id]` cu valorile din options (temperaturi maxime, prag surplus, putere rezistență). Acest store e un dict mutable în memorie — entitățile `number` și `switch` îl modifică direct fără a recrea config entry-ul.

Se instanțiază `BoilerCoordinator`, se face primul refresh, apoi se înregistrează platformele (`switch`, `number`, `sensor`).

La `async_unload_entry` se anulează subscripțiile de stare și se eliberează datele din `hass.data`.

### `coordinator.py` — Creierul integrației

`BoilerCoordinator` extinde `DataUpdateCoordinator` și rulează logica de control în două moduri:

1. **Polling** — la fiecare 30 de secunde
2. **Reactiv** — prin `async_track_state_change_event` pe senzori (solar, rețea, temperaturi); orice schimbare a unuia dintre acești senzori declanșează imediat un refresh

### `config_flow.py` — Wizard de configurare

Setup în 3 pași, plus options flow și reconfigure flow:

| Pas                   | Ce configurezi                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Step 1 – user**     | Nume boiler, releu Shelly (switch), senzor temperatură, senzor consum real (opțional) — pentru fiecare boiler |
| **Step 2 – solar**    | Senzor producție solar, senzor rețea, convenția semnului senzorului de rețea, senzor tensiune (opțional)      |
| **Step 3 – settings** | Temperaturi maxime, prag minim surplus, putere nominală rezistențe                                            |

Options flow permite editarea setărilor din Step 3 fără a reinstala integrarea. Reconfigure flow permite schimbarea entităților (relee, senzori) fără a reinstala.

### `sensor.py`, `switch.py`, `number.py` — Entități HA

Toate entitățile extind `CoordinatorEntity` și se actualizează automat când coordinatorul publică date noi. Entitățile `switch` și `number` folosesc în plus `RestoreEntity` pentru a-și recupera ultima valoare după un restart al HA.

---

## Cum funcționează

### Calculul surplusului virtual

Valoarea centrală a logicii este **surplusul virtual** — câtă energie solară ar fi disponibilă dacă am opri boilerele:

```
surplus_virtual = export_retea
                + putere_boiler1  (dacă boilerul 1 e pornit)
                + putere_boiler2  (dacă boilerul 2 e pornit)
```

Senzorul de rețea poate raporta cu semn pozitiv fie importul, fie exportul — se configurează la setup prin opțiunea **convenție senzor rețea** și poate fi suprascrisă ulterior din options flow.

### Logica de decizie (per ciclu)

1. **Protecție la supraîncălzire (întotdeauna activă, indiferent de modul auto)**
   - Dacă `temp1 >= max_temp_1` și releul 1 e pornit → oprire imediată
   - La fel pentru boilerul 2

2. **Control automat Boiler 1** (are prioritate)

   ```
   pornire  dacă: surplus_virtual >= prag_minim  ȘI  temp1 < max_temp_1
   oprire   dacă: surplus_virtual < prag_minim  SAU  temp1 >= max_temp_1
   ```

3. **Control automat Boiler 2** (pornește doar dacă rămâne surplus după boilerul 1)

   ```
   surplus_ramas = surplus_virtual - putere_boiler1  (dacă B1 e pornit)
   pornire  dacă: surplus_ramas >= prag_minim  ȘI  temp2 < max_temp_2
   ```

4. Dacă modul **auto e dezactivat** pentru un boiler, releul lui nu e atins — controlul e manual.

### De ce „surplus virtual"?

Dacă am folosi direct `export_retea`, un boiler pornit ar masca surplusul real — s-ar opri imediat după ce pornește. Surplusul virtual adaugă înapoi puterea boilerelor active, simulând situația „dacă le-aș opri". Astfel sistemul e stabil și reacționează corect când alți consumatori intră în priză.

---

## Entități create

| Entitate                             | Tip                  | Descriere                                                                                                               |
| ------------------------------------ | -------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `sensor.status_<boiler>`             | Sensor (text)        | Starea curentă: Încălzire / Standby / Temperatură atinsă / Fără producție solară / Control manual / Senzor indisponibil |
| `sensor.temperatura_<boiler>`        | Sensor (°C)          | Temperatura boilerului (oglindește senzorul configurat)                                                                 |
| `sensor.consum_<boiler>`             | Sensor (W)           | Consum curent: valoare reală din senzor (dacă e configurat) sau putere nominală × stare releu                           |
| `sensor.productie_solara`            | Sensor (W)           | Producția panourilor fotovoltaice                                                                                       |
| `sensor.putere_retea`                | Sensor (W)           | Putere rețea: pozitiv = import, negativ = export                                                                        |
| `switch.control_automat_<boiler>`    | Switch               | Activează/dezactivează controlul solar automat per boiler                                                               |
| `number.temperatura_maxima_<boiler>` | Number (°C, 30–95)   | Temperatura maximă țintă                                                                                                |
| `number.prag_minim_surplus_solar`    | Number (W, 0–10 000) | Surplusul minim necesar pentru a porni orice boiler                                                                     |
| `number.putere_nominala_<boiler>`    | Number (W, 0–10 000) | Puterea nominală a rezistenței (folosită în calculul surplusului virtual și ca fallback pentru consum)                  |

---

## Instalare

### Prin HACS

1. Adaugă repository-ul ca sursă personalizată în HACS → **Integrations**
2. Caută „Boiler Solar Controller" și instalează
3. Repornește Home Assistant

### Manual

```bash
cp -r custom_components/boiler_ha  <config_dir>/custom_components/
```

Repornește Home Assistant.

---

## Configurare

**Settings → Devices & Services → Add Integration → Boiler Solar Controller**

Urmează wizard-ul în 3 pași descris mai sus. După setup, integrarea apare ca un singur dispozitiv cu toate entitățile listate.

Setările pot fi modificate oricând din **Configure** fără a reinstala integrarea. Entitățile releu și senzori pot fi reasignate din **Reconfigure**.

---

## Setări ajustabile

Toate valorile de mai jos pot fi modificate live din dashboard (entitățile `number`) sau din **Configure** (options flow) fără restart:

| Setare                        | Implicit | Descriere                                                                                  |
| ----------------------------- | -------- | ------------------------------------------------------------------------------------------ |
| Temperatură maximă Boiler 1/2 | 90 °C    | Boilerul se oprește când atinge această temperatură                                        |
| Prag minim surplus solar      | 800 W    | Sub acest surplus, niciun boiler nu pornește                                               |
| Putere nominală Boiler 1/2    | 1500 W   | Puterea rezistenței, folosită în calculul surplusului virtual și ca fallback pentru consum |

> **Histerezis**: după atingerea temperaturii maxime, boilerul nu repornește decât când temperatura scade cu 5 °C sub țintă. Histerezisul e ignorat automat dacă targetul e modificat de user sau dacă e activă prioritatea de tensiune mare.

---

## Release

### Pași pentru publicarea unui release nou

1. **Actualizează versiunea** în `custom_components/boiler_ha/manifest.json`:

   ```json
   "version": "1.x.y"
   ```

2. **Commit** modificările:

   ```bash
   git add .
   git commit -m "Release v1.x.y"
   ```

3. **Creează un tag Git** cu același număr de versiune:

   ```bash
   git tag v1.x.y
   git push origin main --tags
   ```

4. **Creează un GitHub Release**:
   - Mergi la repository → **Releases** → **Draft a new release**
   - Selectează tag-ul `v1.x.y` creat la pasul anterior
   - Titlu: `v1.x.y`
   - Descriere: copiază ce s-a schimbat (din jurnal)
   - Publică release-ul

5. **HACS** va detecta automat noul release după câteva minute. Utilizatorii cu integrarea instalată vor vedea notificarea de update în HA.

> **Notă**: HACS folosește tag-urile Git ca versiuni. Tag-ul trebuie să coincidă exact cu `version` din `manifest.json` (ex. ambele `1.2.0`, nu `v1.2.0` vs `1.2.0`).
