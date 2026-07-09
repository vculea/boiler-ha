---
name: release
description: 'Publică un release nou pentru boiler-ha. Folosește când: userul cere "release", "versiune nouă", "publică", "tag release", "pregătește release". Skill-ul rulează automat testele, determină versiunea următoare, actualizează manifest.json, face commit, tag și push fără input suplimentar din partea userului.'
argument-hint: 'Opțional: tipul bump-ului (patch/minor/major) sau versiunea exactă (ex. 1.6.0)'
---

# Release boiler-ha

## Când să folosești
- Userul cere un release nou, fără să specifice detalii
- Modificările din working tree sau față de ultimul tag trebuie publicate

## Procedură completă (fără input din partea userului)

### 1. Verifică starea repo-ului
```bash
cd /c/PROJECTS/boiler-ha
git status
git log --oneline -5
```
Notează ultima versiune din tag-uri (`git describe --tags --abbrev=0`).

### 2. Determină versiunea următoare
- Citește versiunea curentă din `custom_components/boiler_ha/manifest.json` (câmpul `version`)
- Aplică bump **patch** implicit (x.y.Z → x.y.Z+1) dacă userul nu specifică altfel
- Bump **minor** (x.Y.0) dacă s-au adăugat funcționalități noi
- Bump **major** (X.0.0) dacă există breaking changes
- Dacă userul a dat o versiune exactă ca argument, folosește-o direct

### 3. Rulează toate testele
```bash
/c/Users/vculea/AppData/Local/uv/cache/archive-v0/4d4B5uzJsREP_OVsFbXYb/Scripts/pytest.exe tests/ -q
```
**Oprește-te** dacă testele eșuează — nu continua cu release-ul.

> Dacă pytest-ul de mai sus nu mai există (cache uv regenerat), găsește-l cu:
> `find /c/Users/vculea/AppData/Local/uv/cache -name "pytest.exe" | head -3`

### 4. Actualizează versiunea în manifest.json
Editează `custom_components/boiler_ha/manifest.json`:
```json
"version": "X.Y.Z"
```

### 5. Construiește mesajul de commit
Analizează `git diff HEAD` pentru a identifica ce s-a schimbat și formulează un mesaj scurt în română:
```
Release vX.Y.Z — <descriere scurtă a ce s-a schimbat>
```
Exemple de mesaje bune:
- `Release v1.5.1 — fix prioritate temp<50% respecta fereastra solara/schedule`
- `Release v1.5.0 — adauga ratio prioritate temperatura configurabil`
- `Release v1.4.2 — hotfix NameError solar_window_done nedefinit`

### 6. Commit, tag și push
```bash
git add -A
git commit -m "Release vX.Y.Z — <descriere>"
git tag vX.Y.Z
git push origin main --tags
```

> **Important HACS**: tag-ul Git (`vX.Y.Z`) și câmpul `version` din `manifest.json` (`X.Y.Z`) trebuie să fie consistente — HACS le compară pentru detectarea update-urilor.

### 7. Pasul manual final — GitHub Release
Informează userul că trebuie să creeze manual GitHub Release:
1. Mergi la repository → **Releases** → **Draft a new release**
2. Selectează tag-ul `vX.Y.Z`
3. Titlu: `vX.Y.Z`
4. Descriere: ce s-a schimbat (din mesajul de commit)
5. Publică release-ul

HACS va detecta automat noul release după câteva minute.

## Structura proiectului (referință rapidă)
```
custom_components/boiler_ha/
├── manifest.json     ← versiunea se actualizează DOAR AICI
└── coordinator.py    ← logica principală de control

tests/
├── conftest.py
├── test_control_logic.py
├── test_solar_schedule.py
├── test_temp_hysteresis.py
└── test_voltage_boost.py
```

## Pattern versiuni folosite până acum
| Tag       | Tip    | Descriere                                      |
|-----------|--------|------------------------------------------------|
| v1.5.1    | patch  | fix prioritate temp<50% + fereastra solara     |
| v1.5.0    | minor  | adaugat ratio prioritate temperatura           |
| v1.4.2    | patch  | hotfix NameError solar_window_done             |
| v1.4.1    | patch  | histereza dupa target + combobox ore fereastra |
| v1.4.0    | minor  | fereastra solara zilnica                       |
| v1.3.6    | patch  | overvoltage handling + tests                   |
