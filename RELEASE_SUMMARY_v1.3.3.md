# Boiler Solar Controller v1.3.3

## Ce e nou

- Programul solar nu mai pornește cu o zi mai devreme.
- Activarea programului se face doar în ziua calendaristică a deadline-ului și până la ora setată.
- Când deadline-ul este într-o zi viitoare, statusul afișat este acum clar: **Programat (zi viitoare)**.
- Jurnalul diagnostic afișează explicit starea de tip „programat” pentru deadline-urile viitoare.

## Fix principal

A fost corectat comportamentul în care un target programat pentru mâine putea influența pornirea chiar de azi. Logica de schedule verifică acum atât momentul în timp, cât și ziua locală.

## Testare

- Suite completă de teste rulată cu succes.
- Rezultat: **57 passed**.
- A fost adăugat scenariu dedicat pentru cazul „programat pe mâine, nu pornește azi”.

## Upgrade

1. Actualizează integrarea la versiunea 1.3.3.
2. Repornește Home Assistant.
3. Verifică entitatea Program solar:
   - dacă deadline-ul este pe o zi viitoare, statusul trebuie să fie „Programat (zi viitoare)”; 
   - în ziua deadline-ului, statusul trece la „Program solar activ”.
