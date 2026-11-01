# Loom walkthrough script (target 7–8 min)

Setup before recording:
- Hosted app open, Chicago → Denver prefilled, load 42,000 lb, 25 mi interval.
- **Warm the server first:** open the app 2 minutes ahead, wait for "Server ready", and run the demo trip once so the forecast is cached.
- Editor open with `backend/routing/engine/risk.py`, `recommend.py`, `providers/alternatives.py`, `frontend/src/lib/heatmap.js`.
- Record at 1440p if you can; checkpoint colours read better.

---

### 0:00–0:30 · Intro
> "This is a weather-aware truck router. You give it an origin, destination, departure time and load weight. It builds three truck routes, checks the forecast along each one at the time the truck will actually be there, scores the risk with the brief's rules, and recommends the safest route. Django REST on the back end, React and MapLibre on the front."

### 0:30–3:00 · Live demo
1. **Form.** Type a city to show autocomplete, then use Chicago → Denver. Point at the load, the 10/25/50-mile checkpoint control and the HOS toggle. Click **Find the safest route**.
2. **Map.**
   > "Three truck routes from TomTom's truck profile, which uses the gross weight. Each dot is a weather checkpoint, coloured by risk at that truck's ETA. The black dots are Hours-of-Service rests: a 30-minute break after 8 hours of driving and 10 hours off after 11. They push the ETAs, and so the forecast hour we read, later down the route."
3. **Click a checkpoint popup.**
   > "ETA, sustained wind and gusts, rain and snow per hour, and the level. The bold row is the condition that set the level."
4. **Route cards and recommendation.**
   > "Each card shows miles per risk level, and they add up exactly to the route length. The recommendation names the key that decided it, here [read it, e.g. 'fewer High miles, 0 vs 25 on Route C']. The order is the brief's: Severe miles, High miles, average risk, then time. I added two keys in front: No Travel miles, and miles with no forecast, so a route can never win on weather it wasn't measured on."
5. **Heatmap and slider.** Drag slowly from 0 to 48 h, then press play.
   > "The shaded band is corridor risk for this load at each forecast hour, and the trucks move to where each route would be at that time. All 49 frames are built once in the browser, so scrubbing never hits the network or relays out the map. It's one texture swap per hour."
   > "Dots and shading answer different questions: a dot is the weather when the truck gets there, the shading is the weather at the slider's time."
6. **Load rule.** Change the load to 30,000, then 40,001, and replan.
   > "Load matters: 45 to 54 mph wind becomes No Travel over 30,000 lb, and 35 to 44 becomes Severe over 40,000."

### 3:00–6:30 · Code walkthrough
1. **`engine/risk.py`**
   > "The rules are data. Each band includes its lower edge, so 0.25 inches of rain is High, but the table says No Travel is strictly above 1.00, so exactly 1.00 stays Severe. Load rules only raise the wind level. The same tables go to the browser, so the heatmap classifies with exactly these rules."
   Show `shared/risk_cases.json`:
   > "36 boundary cases, run by both the Python and the JavaScript tests, so the two classifiers can't drift."
2. **`engine/recommend.py`**
   > "Strict lexicographic ranking. Miles compare at a tenth of a mile and average risk at two decimals, so float noise never decides it. Miles come from the midpoint rule: each checkpoint covers half the gap to its neighbours."
3. **`engine/weather.py`** (`sample_at`)
   > "A subtle one. Open-Meteo's wind is instantaneous, but rain and snow are totals for the preceding hour. So for a 1:20 ETA I interpolate wind between 1:00 and 2:00, and take rain from the 2:00 bucket."
4. **`providers/alternatives.py`**
   > "Routing APIs don't always return three routes on long trips. If they don't, I force detours through a point offset sideways from the route, drop near-duplicates and anything over 1.4x the fastest time. If three genuinely don't exist, the UI says so."
5. **`frontend/src/lib/heatmap.js`**
   > "The backend sends raw wind, rain and snow for a corridor grid. I interpolate the raw values per pixel and then classify, so colours change exactly where thresholds are crossed. Pixel rows are in Mercator, because that's how MapLibre stretches the image."
6. **Tests.** Run `python manage.py test routing` and `npm test` on screen.

### 6:30–7:30 · Trade-offs and close
> "Trade-offs I'd raise. Open-Meteo is free and keyless but billed per location, so each plan has a fixed location budget and repeated trips are cached. If the limit is hit, checkpoints show Unknown, never safe. Truck speed is capped at 65 mph, because uncapped routing timed trucks at about 73. The README has a table of every interpretation I made. Thanks for watching."

---

**If something goes wrong while recording:** a slow first plan means the free-tier server is waking (about a minute). An "Unknown" notice means the weather quota for that minute is used up; wait 60 seconds and replan.
