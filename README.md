# TornIntel

A Python CLI for pulling Torn faction data from the API and storing it in a local SQLite database. Built for analysis — sync data once, query it forever.

## Setup

### 1. Install dependencies

```bash
pip install python-dotenv requests
```

### 2. Configure API keys

Copy `.env.example` to `.env` and add your API key(s):

```bash
# .env
TORN_API_KEYS=YourKey1Here,YourKey2Here,YourKey3Here
TORN_FACTION_ID=12345
```

Multiple keys are recommended. The system automatically rotates through them and backs off when one hits a rate limit. The faction ID is used to filter leaderboards to your members only — find it in the Torn URL on your faction page.

### 3. Run your first sync

```bash
python main.py sync attacks --mode backfill
```

This walks backward through all available attack history (~10 months) and saves everything to `data/tornintel.db`.

---

## Commands

### `sync` — Import data from the API

```
python main.py sync <module> --mode <mode> [options]
```

**Modules:** `attacks`, `chains`, `rankedwars`, `armoury`, `crimes`, `revives`

**Modes:**

| Mode | Description |
|------|-------------|
| `backfill` | Walk backward from now, importing everything not yet in the database. Continues until API history is exhausted or a `--from` boundary is reached. |
| `live` | Catch up from the latest known state. For `attacks` this means new attacks; for `crimes` this refreshes the current OC roster/slots snapshot. |

**Options:**

| Flag | Description |
|------|-------------|
| `--from <timestamp>` | Unix timestamp lower bound (stop here when walking backward) |
| `--to <timestamp>` | Unix timestamp upper bound (start here instead of now) |
| `--filters incoming\|outgoing` | Filter to only incoming or outgoing attacks |
| `--pages <n>` | Max pages for modules that support paged backfill (used by `crimes --mode backfill`, default: 50) |

**Examples:**

```bash
# Import all available history
python main.py sync attacks --mode backfill

# Deep attacks history pull with explicit lower boundary
# (if rate limited, rerun the same command; checkpoint resume is automatic)
python main.py sync attacks --mode backfill --from 1700000000

# Import all attacks for a specific chain's time window
# (get timestamp_start/timestamp_end from the chains table)
python main.py sync attacks --mode backfill --from 1783679454 --to 1783817462

# Import only new attacks since last sync
python main.py sync attacks --mode live

# Import all chain metadata (returns last 100 completed chains)
python main.py sync chains --mode backfill

# Import chains from a specific time period (e.g., during a ranked war)
# Use war_start and war_end timestamps from the rankedwars table
python main.py sync chains --mode backfill --from 1781956800 --to 1781969561

# Import new chains as they complete (picks up chains not yet in database)
python main.py sync chains --mode live

# Sync all ranked wars
python main.py sync rankedwars --mode backfill
```

---

### `watch` — Continuous live sync

```
python main.py watch <module> [options]
```

Runs aggressively: pulls data as fast as possible until caught up, then polls at the cooldown interval. Automatically rotates API keys on rate limits.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--cooldown <seconds>` | 5 | How long to wait between polls when fully caught up |
| `--duration <seconds>` | ∞ | Total runtime limit (omit to run forever) |

**Examples:**

```bash
# Run forever, poll every 10 seconds when caught up
python main.py watch attacks --cooldown 10

# Run for 8 hours
python main.py watch attacks --cooldown 10 --duration 28800
```

**Recommended for ongoing data collection.** Leave this running in a terminal to capture all future chain activity in real time.

---

### `sync --mode search` — Query the local database

```
python main.py sync attacks --mode search [filters] [options]
```

Read-only. Never hits the API. Query by any combination of filters — they are ANDed together. Returns up to `--limit` results (default: 25), newest first by default.

For `crimes`, search displays active OC slots and supports quick filters through existing flags:
- `--player` filters by assigned member name.
- `--item` filters by required item name (or crime name text match).

For `revives`, search uses the same generic flags with revive aliases:
- `--reviver` / `--reviver-name`
- `--target` / `--target-name`
- `--result`

Revive search prints the full hospital reason on a continuation line so long Torn reason text is not cut off.

When `--player` is used for crimes, output also includes `historical` rows sourced from crime slot history so you can see previous known OC positions with real crime names and statuses (for example `completed`), not only currently active slots.
Run `sync crimes --mode backfill` periodically to expand historical coverage from completed crimes.

**Filters:**

| Flag | Description |
|------|-------------|
| `--attacker <id>` | All attacks made by this player (numeric ID) |
| `--attacker-name <name>` | All attacks made by this player (by name, case-insensitive) |
| `--defender <id>` | All attacks against this player (numeric ID) |
| `--defender-name <name>` | All attacks against this player (by name, case-insensitive) |
| `--result <type>` | Filter by attack outcome (Attacked, Mugged, Hospitalized, Lost, Escape, Stalemate, Assist, etc.) |
| `--chain <hit#>` | All attacks that were exactly at chain hit #N |

**Options:**

| Flag | Description |
|------|-------------|
| `--limit <n>` | Max results to return (default: 25) |
| `--oldest` | Show oldest attacks first (default: newest first) |

**Examples:**

```bash
# Last 10 Mugged attacks (newest first)
python main.py sync attacks --mode search --result Mugged --limit 10

# All attacks by Ruztytitan
python main.py sync attacks --mode search --attacker-name Ruztytitan --limit 50

# Ruztytitan's Attacked results, oldest first
python main.py sync attacks --mode search --attacker-name Ruztytitan --result Attacked --oldest

# All attacks against a player
python main.py sync attacks --mode search --defender-name edelweiss03 --limit 30

# Combined: searches are ANDed
python main.py sync attacks --mode search --attacker-name Ruztytitan --result Mugged --limit 5
```

---

### `report` — Chain analysis reports

```
python main.py report attacks <report_type> --chain_id <id> [options]
```

All reports require `--chain_id` — the chain's numeric ID from the `chains` table (not the chain number like 5000). To find it:

```bash
# Find chain IDs by chain number
python main.py sync chains --mode backfill   # sync first if needed
# Then query: SELECT chain_id FROM chains WHERE chain_number = 5000
```

**Report types:**

#### `chain_stats`
Overall statistics for a chain.

```bash
python main.py report attacks chain_stats --chain_id 65999465
python main.py report attacks chain_stats --chain_id 65999465 --top_n 20
```

Output includes: faction hits tracked, unique attackers, total/avg respect, success rate, duration, result breakdown (Attacked/Mugged/Lost/etc.), and a top-N attacker table showing hits, respect, avg, success rate, and chain hit range.

`--top_n` controls how many players appear in the top attackers table (default: 10). Filtered to your faction if `TORN_FACTION_ID` is set in `.env`.

#### `chain_leaderboard`
Ranked list of faction members by contribution.

```bash
python main.py report attacks chain_leaderboard --chain_id 65999465
```

Output includes: rank, name, faction, hits, total respect, success rate. Filtered to your faction automatically if `TORN_FACTION_ID` is set.

#### `chain_player`
All attacks by a specific player within a chain, with per-hit detail.

```bash
python main.py report attacks chain_player --chain_id 65999465 --player Ruztytitan
```

Output includes: summary (hits, success rate, total/avg respect, first/last hit number) and a full table of every attack — chain hit number, result, respect, defender, and timestamp.

#### `chain_hit`
Find the attacker who made a specific hit number.

```bash
python main.py report attacks chain_hit --chain_id 65999465 --hit_number 4000
```

Note: `--hit_number` matches the `chain` field in the database, which stores each attack's position within the chain (e.g. hit #4000 = the 4000th hit of that chain). Only hits your faction made are in the database.

---

## Ranked Wars — Sync & Analysis

### Syncing Ranked War Attack Data

Ranked wars are stored separately from regular attacks. To capture all attacks for a specific war:

```bash
# 1. Sync ranked war metadata first (get war IDs and timestamps)
python main.py sync rankedwars --mode backfill

# 2. Find your war — query the rankedwars table
# SELECT war_id, our_faction_name, opponent_faction_name, 
#        war_start, war_end FROM rankedwars 
# WHERE war_id = 43902

# 3. Sync attacks for that war using its timestamp window
python main.py sync attacks --mode backfill \
  --from <war_start> --to <war_end>
```

**Important:** Each attack is saved with:
- **attack_id** (primary key — unique identifier for each attack)
- **is_ranked_war** (boolean — 1 if part of a ranked war, 0 if not)
- **timestamp_started** (when the attack occurred — use this to match against war window)
- **attacker_id, defender_id** (faction IDs for comparison with ranked war factions)

You can then query attacks and ranked wars separately and compare:

```bash
# Query war attacks by timestamp
python main.py sync attacks --mode search \
  --result Attacked \
  --limit 1000

# Compare with ranked war data (stored in rankedwars table)
# SELECT * FROM rankedwars WHERE war_id = 43902
# SELECT COUNT(*), SUM(is_ranked_war) FROM attacks 
#   WHERE timestamp_started >= <war_start> AND timestamp_started <= <war_end>
```

---

## Ranked Wars Reports

Analyze faction ranked wars, including faction scores, participating attackers, and detailed breakdowns.

```
python main.py report rankedwars <report_type> --war_id <id> [options]
```

All reports require `--war_id` — the ranked war's numeric ID. Get war IDs from the `rankedwars` table:

```bash
# Sync all ranked wars first
python main.py sync rankedwars --mode backfill

# Then query available wars
# The rankedwars table has: war_id, our_faction_name, opponent_faction_name, scores, chains, timestamps, war_start, war_end
```

**Report types:**

#### `war_stats`
Overall statistics for a ranked war.

```bash
python main.py report rankedwars war_stats --war_id 43153
python main.py report rankedwars war_stats --war_id 43153 --top_n 20
```

Output includes:
- Participating factions and their scores
- War duration, start/end times, and target respect
- Winner faction
- Attack counts and statistics (total respect, average respect, success rate)
- Result breakdown (Attacked/Mugged/Lost/etc. for each faction)
- Top N attackers (default: 10) with hits, respect earned, success rate, and hit range

`--top_n` controls how many players appear in the top attackers table (default: 10).

#### `war_leaderboard`
Ranked list of attackers by contribution within a war.

```bash
python main.py report rankedwars war_leaderboard --war_id 43153
python main.py report rankedwars war_leaderboard --war_id 43153 --top_n 20
```

Output includes: rank, name, hits, total respect, success rate. Ordered by hit count (highest first). `--top_n` limits results (default: 10).

#### `war_player`
All attacks by a specific player within a ranked war.

```bash
python main.py report rankedwars war_player --war_id 43153 --player Ruztytitan
```

Output includes: summary (hits, success rate, total/avg respect) and a full table of every attack — chain hit number, result, respect, defender, and timestamp.

---

## War Payouts

Calculate and display fair payouts for faction members based on their war contributions, with support for costs (xanax, bounty), assists, and outside hits.

```
python main.py report rankedwars war_payout --war_id <id> --total_payout <$> [options]
python main.py payout rankedwars --war_id <id> --total_payout <$> [options]
```

**Parameters:**

| Flag | Description |
|------|-------------|
| `--war_id` | The ranked war's ID (required) |
| `--total_payout` | Total payout pool in dollars (required) |
| `--xanax_cost` | Xanax cost to deduct from pool (default: 0) |
| `--bounty_cost` | Bounty cost to deduct from pool (default: 0) |
| `--faction_cut` | Faction cut percentage 0-100 (default: 0) |
| `--per_assist` | Payment per assist on opposing faction (default: 0) |
| `--pay_outside_hits` | Pay for hits outside war target (0=no, 1=yes, default: 0) |

**How payouts are calculated:**

1. Query only attacks up to war end timestamp (stops chains that continue after war)
2. Classify attacks:
   - **War hits**: attacks marked as `is_ranked_war=1` (contribute to respect pool)
   - **Assists**: hits on opposing faction (counted separately, flat $/assist)
   - **Outside hits**: attacks not on opposing faction (optional, if `--pay_outside_hits 1`)
3. Deduct all costs upfront: `(total - xanax - bounty - assist_costs)`
4. Calculate distribution pool: `remaining × (1 - faction_cut%)`
5. Distribute respect-based portion proportionally by player respect
6. Add assist bonuses (flat amount per assist if on opposing faction)
7. Add outside hit bonuses (if enabled, distributed by outside respect %)
8. Cap chain bonuses at player's avg_respect_per_hit (prevents overpayment)
9. Store full audit trail in payouts table

**Example with all features:**

```bash
# War with $50k pool, $5k xanax, $1k bounty, 20% cut, $50/assist
python main.py payout rankedwars --war_id 43153 --total_payout 50000 \
  --xanax_cost 5000 --bounty_cost 1000 --faction_cut 20 --per_assist 50

# Calculation:
# - Costs deducted: $5k + $1k + (assists × $50) = pool reduced
# - Remaining: (50k - 5k - 1k - assists_cost) × 0.80 = distribution pool
# - Per-player: respect% × pool + (assists × $50) + outside%
```

**Output shows:**
- War Hits (war_hits column): attacks marked as ranked war
- Assists (ast column): hits on opposing faction
- Outside (out column): hits outside war target
- Respect: earned from war hits only
- Bonus: chain bonuses (capped at avg/hit)
- %: player's share of total respect
- Payout: total player share (respect + assists + outside)

---

## Finding a Chain ID

Chain IDs are stored in the `chains` table after running `sync chains`. The `chain_number` is the sequential chain count (e.g. 5000th chain = `chain_number = 5000`), while `chain_id` is Torn's internal ID for that specific chain run.

**Note:** The Torn API only returns the most recent 100 completed chains. Use `--mode backfill` once to get your initial history, then `--mode live` to pick up new chains as they complete.

### Finding Chains by Timestamp

You can backtrack chains using timestamp ranges, just like attacks:

```bash
# Sync all available chains first
python main.py sync chains --mode backfill

# Get chains that occurred during a ranked war
python main.py sync chains --mode backfill --from 1781956800 --to 1781969561

# Then query for chains in that window
# SELECT chain_id, chain_number, respect, timestamp_start, timestamp_end 
# FROM chains 
# WHERE timestamp_start >= 1781956800 AND timestamp_start <= 1781969561
# ORDER BY timestamp_start DESC;
```

Example workflow — find all chains during War 43902:
1. Get war timestamps: `SELECT war_start, war_end FROM rankedwars WHERE war_id = 43902`
2. Import chains from that period: `python main.py sync chains --mode backfill --from 1781956800 --to 1781969561`
3. Find specific chains: `SELECT chain_id, chain_number FROM chains WHERE timestamp_start BETWEEN 1781956800 AND 1781969561`
4. Sync attacks for those chains: `python main.py sync attacks --mode backfill --from 1781956800 --to 1781969561`
5. Run reports: `python main.py report attacks chain_leaderboard --chain_id <chain_id>`

---

## Database Schema

Data is stored in `data/tornintel.db` (SQLite). Key tables:

### attacks
Every synced attack with complete details:
- **attack_id** (INTEGER, PRIMARY KEY) — Unique attack identifier from Torn API
- **attacker_id, defender_id** — Faction member IDs
- **attacker_faction_id, defender_faction_id** — Faction IDs (use to filter to war participants)
- **timestamp_started, timestamp_ended** — Attack timestamps (use to match war windows)
- **is_ranked_war** (BOOLEAN) — 1 if part of ranked war, 0 if regular attack
- **respect_gain** — Respect earned by attacker
- **chain** — Hit number within the chain (e.g., 4000 = 4000th hit)
- **result** — Attack outcome (Attacked, Mugged, Lost, Assist, etc.)
- **modifiers** — Various modifier fields (war, fair_fight, chain_bonus, etc.)

### rankedwars
Ranked war metadata and summary data:
- **war_id** — Unique ranked war identifier
- **our_faction_id, opponent_faction_id** — Faction IDs participating
- **our_score, opponent_score** — Final war scores
- **war_start, war_end** — War window timestamps (use to query attacks table)
- **winner** — ID of winning faction
- **chains** — Active chain count during war
- **timestamp** — When war data was synced

### chains
Chain metadata:
- **chain_id** — Unique chain identifier from Torn API
- **chain_number** — Sequential chain count
- **respect** — Total respect in chain
- **timestamp_start, timestamp_end** — Chain window

### payouts
Calculated war payouts:
- **war_id** — Which war this payout is for
- **player_id, player_name** — Faction member
- **respect_earned** — War respect contribution
- **hits** — Number of war hits
- **payout_total** — Calculated payout amount
- **parameters_used** — Payout calculation settings (JSON)

### Querying War Data

To find all attacks for a specific war:

```sql
-- Get war details
SELECT war_id, our_faction_id, opponent_faction_id, war_start, war_end 
FROM rankedwars 
WHERE war_id = 43902;

-- Get all attacks during that war (substitute war_start, war_end, opponent_faction_id)
SELECT attack_id, attacker_name, defender_name, respect_gain, is_ranked_war, chain
FROM attacks 
WHERE timestamp_started >= 1781956800 
  AND timestamp_started <= 1781969561 
  AND defender_faction_id = 49862
  AND is_ranked_war = 1
ORDER BY timestamp_started DESC;

-- Compare against ranked war score
SELECT COUNT(*) as total_attacks,
       SUM(CASE WHEN is_ranked_war=1 THEN 1 ELSE 0 END) as war_attacks,
       SUM(respect_gain) as total_respect
FROM attacks 
WHERE timestamp_started >= 1781956800 
  AND timestamp_started <= 1781969561 
  AND defender_faction_id = 49862;
```

---

## API Keys & Rate Limiting

- Set multiple keys in `.env` as `TORN_API_KEYS=key1,key2,key3`
- The system uses round-robin rotation and backs off automatically when a key is rate limited
- With 3 keys you can sustain ~5 requests/second without triggering limits
- The `watch` command is designed to use all keys efficiently — it pulls data as fast as possible and only slows down when fully caught up

---

## Armoury — Track Item Usage

Sync and analyze faction armoury activity, including items used, deposited, loaned, and their costs. Track medical items (xanax, morphine, blood bags), utilities, drugs, and more across wars and chains.

### Syncing Armoury Data

```bash
# Import all recent armoury news (backfill from latest)
python main.py sync armoury --mode backfill

# Deep armoury history pull with explicit lower boundary
# (if rate limited, rerun the same command; checkpoint resume is automatic)
python main.py sync armoury --mode backfill --from 1700000000

# Get only new events since last sync
python main.py sync armoury --mode live

# Import armoury activity during a specific time period (e.g., during a war)
python main.py sync armoury --mode backfill --from 1781956800 --to 1781969561

# Continuous monitoring
python main.py watch armoury --cooldown 10
```

**Pagination Strategy:** Armoury backfill uses **timestamp-based pagination** (same as attacks), walking backward through the complete event log. Each batch's oldest timestamp becomes the boundary (`to` parameter) for the next request, ensuring complete coverage without gaps or duplicates. Backfill now walks until API history is exhausted (or until `--from` is reached) to reduce chances of missing older gaps.

**Rate limit + resume behavior (attacks and armoury):**
- Retry waits now use an escalating schedule suitable for deep pulls: **10s, 20s, 30s, 60s**.
- Torn daily read-limit responses (API code 14) are treated as rate limiting and pause safely.
- If retries are exhausted, backfill pauses cleanly, saves a checkpoint, and logs a resume command.
- On next run, if no `--to` is provided, sync automatically resumes from the saved checkpoint.
- Override schedule with `.env`: `TORN_RATE_LIMIT_RETRY_SCHEDULE=10,20,30,60`

### Armoury Event Types

The armoury system tracks five types of events:

| Event | Description |
|-------|-------------|
| `used` | Item consumed from faction armoury (e.g., xanax used during chain) |
| `filled` | Empty blood bag filled with blood |
| `deposited` | Items added to faction armoury |
| `loaned` | Items sent to a player (temporary loan) |
| `received` | Items received from a player |

`received` also includes equivalent return phrasing from armoury news (for example `returned ... to the faction armory` and `retrieved ... from <player>`), so outstanding-loan tracking closes correctly.

### Armoury Item Categories

Items are automatically categorized:

| Category | Examples |
|----------|----------|
| Medical | Morphine, Blood Bags, First Aid Kits, Aspirin |
| Drug | XTC, Ecstasy, Cocaine, Marijuana, Opium, LSD, PCP |
| Consumable | Bottle/Can/Bag/Box consumables (beer, candy, energy drinks, snack items) |
| Utility | Crime/tool items (Lockpicks, Crowbars, Keycards, ATM Key, Card Skimmer, cutters, detectors) |
| Temporary | HEG, Grenade, Flash Grenade, Smoke Grenade, Pepper Spray, Tear Gas |
| Booster | Faction boosters and buffs (e.g. Lawyer's Business Card, Feather Hotel Coupon) |
| Weapon | Faction weapons |
| Armor | Faction armor |

Category resolution order:
1. Explicit parser rules in `modules/armoury/parser.py` (highest priority)
2. Name-pattern heuristics (for grouped names like `Bottle of ...`, `Can of ...`, `Bag of ...`)
3. Torn API `torn/items` type fallback (used when category remains `Unknown`)

The API-type fallback maps common Torn types into local categories (for example: `Alcohol`, `Candy`, and `Energy Drink` -> `Consumable`; `Primary`/`Secondary`/`Melee` -> `Weapon`; `Defensive` -> `Armor`).

### Querying Armoury Data

Search the local armoury database with flexible filtering:

```bash
# Search by player (case-insensitive)
python main.py sync armoury --mode search --player "player_name" --limit 50

# Search by event type
python main.py sync armoury --mode search --event-type used --limit 100

# Search by item name
python main.py sync armoury --mode search --item xanax --limit 50

# Search by item category
python main.py sync armoury --mode search --category Medical --limit 100

# Combine filters (AND'd together)
python main.py sync armoury --mode search --player john --item xanax --limit 25
```

Search results show: date/time, event type, player, item, category, quantity, and unit price.

Price shown in armoury search uses effective pricing in this order:
1. manual override from `prices set`
2. market average from `prices update`
3. event fallback price (or 0 if none available)

If you still see `0`, that item currently has no market/manual price available for your API access level.

### Armoury Reports

Analyze armoury activity and costs with built-in reports:

```bash
# Medical items summary (xanax, morphine, blood bags)
python main.py report armoury medical_summary

# Specific item category breakdown
python main.py report armoury category Medical

# Player armoury usage
python main.py report armoury player_usage --player 12345

# Outstanding loaned items + rough return ETA
# (shows currently outstanding loans only, not historical closed loans)
python main.py report armoury loan_tracker --limit 25
python main.py report armoury loan_tracker --player Bjornshauge --limit 25

# Period analysis (e.g., during a war)
python main.py report armoury war_costs --war_id 43902
python main.py report armoury chain_costs --chain_id 65999465

# Include a 4-day Xanax stacking window before war/chain start
# and a 3-day temporary return window after end for temp reconciliation
python main.py report armoury war_costs --war_id 43902 --stacking-days 4 --temp-return-days 3
python main.py report armoury chain_costs --chain_id 65999465 --stacking-days 4 --temp-return-days 3
```

Temporary reconciliation uses both category and item-name matching (HEG/grenade/flash/smoke/pepper/tear/molotov/claymore mine) to include temp-like rows even if category labels drift.
If `Temporary` still shows `0`, that specific war/chain window (plus `--temp-return-days`) has no matching temporary activity in your local data.

### OC Crimes Item Audit and CPR

Sync OC 2.0 recruiting/planning slots and keep CPR baselines in SQLite.

```bash
# Pull latest active OC slots and CPR data
python main.py sync crimes --mode live

# Historical CPR backfill from completed crimes (paged)
python main.py sync crimes --mode backfill --pages 80

# Audit required items vs outstanding armoury holders
python main.py report crimes oc_item_audit

# CPR report with thresholds from for context/oc_rules.json (if present)
python main.py report crimes oc_cpr

# Current faction members not in active recruiting/planning crimes
python main.py report crimes oc_outside --limit 200

# Optional local inspection using search mode
python main.py sync crimes --mode search --player ricky --limit 20

# Search player with historical positions included
python main.py sync crimes --mode search --player "OGtizzyT" --limit 50

# Sync faction revives
python main.py sync revives --mode live
python main.py sync revives --mode backfill

# Search synced revives
python main.py sync revives --mode search --reviver-name JeffBezas --limit 20
python main.py sync revives --mode search --target-id 430598 --limit 20
```

### Revives and Revive Requests

Revives are stored separately from revive requests.

- `revives` stores the raw faction revive log from Torn, including reviver details, target details, chance, result, hospital reason, and a full raw payload snapshot.
- `revive_requests` stores externally-triggered revive requests so they can later be matched to a completed revive and marked fulfilled.

Matching behavior:
- Requests are matched to the most recent successful revive for the same target after the request timestamp and within the matching window.
- Matching prefers `target_id`; `target_name` is a fallback.
- Fulfilled requests record `fulfilled_revive_id`, `revived_timestamp`, `fulfilled_at`, `fulfilled_by_id`, and `fulfilled_by_name`.
- Near-duplicate external requests for the same target/source/timestamp window are deduplicated instead of creating multiple rows.

Commands:

```bash
# Run the local listener that external tools/Tampermonkey can post to
python main.py revive_listener serve

# Add a revive request from an external timestamp source
python main.py revive_requests add --requested-at 1784336200 --target-id 430598 --requester "test-js"

# List pending or fulfilled requests
python main.py revive_requests list --status pending --limit 25
python main.py revive_requests list --status all --limit 25

# Re-run matching against already-synced revive history
python main.py revive_requests reconcile --status all --limit 25

# Remove revive requests from the database for testing/cleanup
# Default delete scope is pending only
python main.py revive_requests delete

# Remove only matching pending requests for one target
python main.py revive_requests delete --target-id 430598

# Remove all revive requests, including fulfilled ones, only when you intentionally want a full cleanup
python main.py revive_requests delete --status all
```

Delete behavior:
- `delete` removes rows from `revive_requests` directly.
- Without extra filters, it only deletes rows with `status=pending`.
- Add `--target-id`, `--target-name`, `--request-id`, `--requester-id`, or `--requester` to narrow the cleanup.
- Use `--status all` only when you want to purge both pending and fulfilled test rows.

If a target name begins with `-`, prefer `--target-id` or pass the name as `--target-name=-Plutonium-` so argparse does not read it as another flag.

### Local Tampermonkey Flow

You can run a local HTTP listener and have Tampermonkey post revive requests directly into your SQLite-backed workflow.
The userscript now does automatic endpoint discovery so end users do not need to manually configure an IP/port.

Listener endpoints:
- `GET http://127.0.0.1:8765/health`
- `POST http://127.0.0.1:8765/revive-request`

Start the listener locally:

```bash
python main.py revive_listener serve
python main.py revive_listener serve --host 127.0.0.1 --port 8765
python main.py revive_listener serve --poll-seconds 15
```

Use from another computer (LAN):

```bash
# On the machine running TornIntel, bind all interfaces
python main.py revive_listener serve --host 0.0.0.0 --port 8765
```

To keep this reachable from every computer, give the TornIntel machine a stable LAN IP:
- Best option: create a DHCP reservation in your router for the machine's MAC address.
- Alternative: set a manual static IPv4 address on the machine that stays inside your LAN subnet.
- Keep `scripts/tampermonkey/revive_request_endpoint.json` pointed at that stable IP, for example `http://10.0.0.52:8765`.

Windows quick check for the listener machine:
- Run `ipconfig` and confirm the IPv4 address is the same one used in `revive_request_endpoint.json`.
- Make sure the machine is not switching between Wi-Fi and Ethernet with different IPs.
- If the IP changes later, update the endpoint file and repush it.

Automatic endpoint discovery behavior:
- The script fetches `scripts/tampermonkey/revive_request_endpoint.json` from GitHub raw.
- If `base_urls` is present, it tries each URL in order and picks the first one that passes `/health`.
- If only `base_url` is present, it uses that single URL (legacy format).
- If not reachable, it falls back to `http://127.0.0.1:8765` and `http://localhost:8765`.

To publish one endpoint for everyone (no user setup):
- Update `scripts/tampermonkey/revive_request_endpoint.json` with one or more listener URLs.
- For mixed environments (outside + LAN), publish a public URL first, then your LAN URL as fallback.
- Example:

```json
{
  "base_urls": [
    "https://revive-listener.yourdomain.com",
    "http://10.0.0.52:8765"
  ],
  "base_url": "http://10.0.0.52:8765"
}
```

- Commit and push. Installed userscripts will auto-pick the new endpoint.

For users outside your LAN, a private LAN IP (like `10.x.x.x` or `192.168.x.x`) is never reachable directly.
Use one of these for the first `base_urls` entry:
- A public DNS name/IP with router port-forwarding (TCP 8765) to your listener machine.
- A tunnel URL (for example Cloudflare Tunnel or ngrok) that forwards to `http://127.0.0.1:8765`.

Optional admin override (not needed for normal users):
- Tampermonkey menu command: `TornIntel: Set/Clear Revive Listener Override URL`

If it still fails from another machine, verify:
- Both machines are on the same network/VPN and can ping each other.
- Windows Firewall allows inbound TCP `8765` on the TornIntel machine.
- You can open `http://<listener-ip>:8765/health` from the browser machine.

The included Tampermonkey starter script is in [scripts/tampermonkey/revive_request_local.user.js](scripts/tampermonkey/revive_request_local.user.js).

Behavior:
- The script checks `/health` first.
- If the listener is offline, it shows a clear error with the configured URL and a listener start command.
- If the listener is online, it posts the revive request JSON into `revive_requests`.
- The backend immediately attempts to match that request to an already-synced successful revive.
- While the listener is running, it also polls on a timer when pending requests exist: it runs a live revive sync and re-checks pending requests automatically.

This keeps the browser script simple while all matching and persistence stays local in TornIntel.

`oc_item_audit` sections:
- `REQUIRED ITEM LOAN HOLDERS`: cross-reference list of who currently holds required OC items (from outstanding armoury loans).
- `REQUIRED ITEM FACTION STOCK`: cross-reference of required item quantities currently in faction armoury (estimated from deposited/received/loaned/used history).
  Includes both estimated `in faction armoury` and currently `on loan` quantities for easier reconciliation.
  If a crime item was matched through a different armoury item ID, the line also shows an `alias match` annotation.
- `CORRECT HOLDER`: required item currently held by the assigned OC user.
- `FULFILLED VIA ARMOURY AVAILABILITY`: assigned slot requirement is already satisfied according to OC slot availability (`item_is_available=1`) even if that exact user-item loan pair is not present.
- `WRONG HOLDER`: required item held by a different user while needed elsewhere.
- `RETURNABLE`: loaned items not currently needed by active recruiting/planning OCs.
- `STOCK NEEDED`: item shortfalls after comparing required slots vs outstanding holders.
- `FUTURE UNASSIGNED DEMAND`: item demand from recruiting/planning slots that are not assigned yet.

`oc_item_audit` checks only active `recruiting` and `planning` crimes.
Item matching is category-agnostic and uses `item_id`, so requirements are matched even when storage categories differ (for example a crime-required item appearing under `Temporary` or `Medical` in armoury data).
When crime-required item IDs differ from armoury event IDs for the same item name, audit stock matching reconciles by item name alias to reduce false shortages.
For these mismatched-ID cases, deposited history is used as a fallback stock floor when net stock would otherwise show zero.

Item labels in audit output include both item name and item ID (`Item Name [1234]`) to make mismatches easier to inspect.
When available, item names are enriched from Torn's item catalogue (`torn/items`) so generic placeholders are reduced.

Roster handling:
- `sync crimes` refreshes `crime_members` from current faction roster every run.
- Members who leave faction are removed from this table on the next sync.
- `oc_outside` only checks current roster members, so ex-members are no longer flagged.
- `oc_outside` now prefers Torn's `members[].is_in_oc` roster flag (with DB fallback), which aligns more closely with in-game OC assignment panels.

CPR coloring in `oc_cpr`:
- Green `OK`: CPR >= minimum.
- Yellow `BORDERLINE`: CPR is 1-2 points below minimum.
- Red `LOW`: CPR is more than 2 points below minimum.

Crimes command output is colorized in terminal for faster scanning (`search`, `oc_item_audit`, `oc_outside`, `oc_cpr`, and `crime_rules show`).

### Crime Template Rules (Tier + Override Management)

Rules are stored in `data/oc_rules.json` and support both:
- Tier defaults for levels 1-10.
- Specific per-crime overrides, including per-position overrides.

Use CLI to manage rules without editing JSON directly:

```bash
# Show current template/rule state
python main.py crime_rules show

# Set tier default minimum CPR
python main.py crime_rules set_tier --tier 6 --min-cpr 72

# Set a crime-specific default minimum CPR
python main.py crime_rules set_crime --crime-name "Bidding War" --min-cpr 75

# Set a position override for a crime
python main.py crime_rules set_position --crime-name "Bidding War" --position "Bomber" --min-cpr 80

# Remove a crime override completely
python main.py crime_rules remove_crime --crime-name "Bidding War"
```

Rule priority used by `oc_cpr`:
1. Crime + position override.
2. Crime default override.
3. Tier default (1-10).
4. Fallback `0`.

This makes it easy to add new crimes over time with command-only maintenance.

`oc_cpr` compares each active slot CPR against per-level defaults and optional crime/position overrides from `for context/oc_rules.json`.

### Managing Item Prices

Item prices are used to calculate costs in armoury reports. Prices can be fetched from the Torn API or set manually.

```bash
# Update prices from API (if your key has market permissions)
python main.py prices update

# Try per-item value-price update from v2 torn/{id}/items
python main.py prices update_all

# View prices by category
python main.py prices show --category Drug
python main.py prices show --category Medical --limit 25

# Show most-used items that still have no effective price
python main.py prices missing --limit 25
python main.py prices missing --event-type used --min-uses 10 --limit 50

# Export current manual overrides to CSV
python main.py prices export_manual
python main.py prices export_manual --output data/manual_price_overrides_backup.csv

# Set a custom price for a specific item
python main.py prices set --item_id 148 --price 1500    # Xanax at $1,500
python main.py prices set --item_id 149 --price 1800    # Morphine at $1,800
```

`prices update_all` iterates each known armoury item ID and reads `value.market_price` from `v2/torn/{id}/items`, then saves that into `item_prices.market_average`.

**Note:** The Torn API item/market endpoints require higher API key permissions (access level 4+). If you don't have permissions, both `prices update` and `prices update_all` will show a graceful warning. You can still manually set prices using `prices set` for any items your faction uses.

When market access is limited, use `prices missing` to find the highest-impact items to price manually first.

**Price lookup behavior in reports:**
1. If `prices set` was used for an item, that manual override price is used
2. Otherwise, if a market price exists, that is used
3. Otherwise, price defaults to $0.00

Example workflow:
```bash
# Try to update from API (may fail if key lacks permissions — that's OK)
python main.py prices update
python main.py prices update_all

# Export the manual overrides you've set (for backup/review)
python main.py prices export_manual

# Manually set prices for items your faction commonly uses
python main.py prices set --item_id 148 --price 1500    # Xanax
python main.py prices set --item_id 149 --price 1800    # Morphine
python main.py prices set --item_id 150 --price 500     # Vicodin
python main.py prices set --item_id 161 --price 100     # Empty Blood Bag

# Now when you run reports, they'll show real costs
python main.py report armoury category --category Drug
```

### Pricing Test Cases

Use these quick tests to verify pricing commands and search display behavior.

#### Test 1 - Bulk market update command exists and handles permissions

```bash
python main.py prices update_all
```

Expected:
- If permitted: shows a success line with updated count.
- If not permitted: shows a graceful warning indicating the endpoint is unavailable for your key.

#### Test 2 - Find highest-impact missing prices

```bash
python main.py prices missing --event-type used --min-uses 10 --limit 25
```

Expected:
- Lists high-usage items with zero effective price.
- Includes suggested `prices set` commands.

#### Test 3 - Set manual prices and re-check gaps

```bash
python main.py prices set --item_id 148 --price 1500
python main.py prices set --item_id 149 --price 1800
python main.py prices missing --event-type used --min-uses 10 --limit 25
```

Expected:
- Previously missing items move off the missing list once priced.

#### Test 4 - Export manual overrides

```bash
python main.py prices export_manual
python main.py prices export_manual --output data/manual_price_overrides_backup.csv
```

Expected:
- Shows exported row count and output file path.
- CSV contains headers and one row per manual override.

#### Test 5 - Verify armoury search shows non-zero effective price

```bash
python main.py sync armoury --mode search --event-type used --item xanax --limit 10
```

Expected:
- Price column shows non-zero values (for example, `$1,500.00` after setting Xanax manually).

### Calculating Item Costs in Reports

To get accurate cost calculations in armoury reports, you need to set item prices first. See [Managing Item Prices](#managing-item-prices) above.

```bash
# 1. Set prices for commonly used items
python main.py prices set --item_id 148 --price 1500    # Xanax
python main.py prices set --item_id 149 --price 1800    # Morphine
python main.py prices set --item_id 161 --price 100     # Empty Blood Bag

# 2. Run reports — costs will now be calculated
python main.py report armoury category --category Drug
python main.py report armoury category --category Medical
python main.py report armoury player_usage --player 12345

# Output now shows:
# - Item costs per event
# - Category breakdown with totals
# - Player usage with total cost by category and event type
# - Accurate cost tracking for budget planning
```

### Tracking Costs by War/Chain

To analyze armoury spending during a specific war or chain:

```bash
# 1. Get war timestamps
# SELECT war_start, war_end FROM rankedwars WHERE war_id = 43902

# 2. Sync armoury activity during that period
python main.py sync armoury --mode backfill --from 1781956800 --to 1781969561

# 3. Set prices for items used during the war
python main.py prices set --item_id 148 --price 1500    # Xanax
python main.py prices set --item_id 149 --price 1800    # Morphine

# 4. Generate reports — costs will be calculated automatically
python main.py report armoury category --category Drug
python main.py report armoury medical_summary
python main.py report armoury loan_tracker --limit 25

# Output shows:
# - Items used with quantities and costs
# - Breakdown by category (Medical, Drug, Utility, etc.)
# - Total spend during the period
# - Per-item costs for detailed billing
```

### Armoury Database Tables

#### armoury_news
Every armoury event:
- **event_id** (INTEGER, PRIMARY KEY) — Unique event identifier
- **timestamp** — When the event occurred
- **player_id, player_name** — Faction member
- **event_type** — used, filled, deposited, loaned, received
- **item_id, item_name** — Item details
- **item_category** — Medical, Drug, Utility, Temporary, etc.
- **quantity** — How many units
- **item_price** — Unit price at time of event
- **description** — Parsed event text

#### item_prices
Item pricing reference for cost calculations in reports:
- **item_id** (INTEGER, PRIMARY KEY) — Torn item ID (see Item ID Reference Guide)
- **item_name** — Display name from armoury events
- **item_category** — Category for grouping (Medical, Drug, Utility, Temporary, etc.)
- **market_average** — Current market price from API (if available)
- **manual_override** — Custom price set via `prices set` command
- **last_updated** — When price was last updated
- **market_source** — Source of price (torn_v2_api, manual, unknown)

**How prices are used in reports:**
- If `manual_override` is set, that price is used (highest priority)
- Otherwise, if `market_average` exists, that is used
- Otherwise, price defaults to $0.00

**Populate prices:**
```bash
# Attempt to fetch from API (requires API key permissions)
python main.py prices update

# Or manually set prices for items your faction uses
python main.py prices set --item_id 148 --price 1500
python main.py prices set --item_id 149 --price 1800

# View current prices
python main.py prices show
python main.py prices show --category Drug
```

---

## Item ID Reference Guide

Item IDs are used when setting custom prices. This reference lists the most commonly used items tracked by the armoury system.

### Drugs (Category: Drug)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 148 | Xanax | Prescription painkiller, used frequently in wars |
| 150 | Vicodin | Prescription painkiller, less common than xanax |
| 151 | Tramadol | Opioid, alternative to morphine |
| 153 | XTC | Party drug |
| 154 | Ecstasy | Party drug |
| 155 | Ketamine | Dissociative drug |
| 156 | Cocaine | Stimulant drug |
| 157 | Marijuana | Cannabis |
| 158 | Opium | Narcotic |
| 159 | LSD | Hallucinogen |
| 160 | PCP | Dissociative drug |

### Medical Items (Category: Medical)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 149 | Morphine | Opioid now classified under Medical |
| 161 | Empty Blood Bag | Baseline blood bag, needs filling |
| 162 | Blood Bag : Irradiated | Special blood bag variant |
| 163 | Blood Bag : B+ | Rare positive B type |
| 164 | Blood Bag : B- | Rare negative B type |
| 165 | Blood Bag : O+ | Most common positive |
| 166 | Blood Bag : O- | Most common negative |
| 167 | Blood Bag : A+ | Common positive variant |
| 168 | Blood Bag : A- | Common negative variant |
| 169 | Blood Bag : AB+ | Rare positive variant |
| 170 | Blood Bag : AB- | Rare negative variant |
| — | Small First Aid Kit | Medical supply, no custom price yet |
| — | First Aid Kit | Medical supply, no custom price yet |
| — | Large First Aid Kit | Medical supply, no custom price yet |
| — | Aspirin | Medical supply |
| — | Paracetamol | Medical supply |

### Utilities (Category: Utility - Crime/Tools)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 2 | Lockpick | Lock picking tool |
| 3 | Crowbar | Prying tool |
| 1379 | ATM Key | Utility access item |
| 1125 | Card Skimmer | Utility crime tool |

### Consumables (Category: Consumable)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 180 | Bottle of Beer | All `Bottle of ...` items map to Consumable |
| 987 | Can of Crocozade | All `Can of ...` items map to Consumable |
| 310 | Lollipop | Candy item mapped to Consumable |
| 37 | Bag of Bon Bons | Candy item mapped to Consumable |
| 35 | Box of Chocolate Bars | Candy item mapped to Consumable |

### Weapons (Category: Weapon)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 233 | BT MP9 | SMG weapon now mapped from unknown list |
| 10 | Chainsaw | Melee weapon now mapped from unknown list |
| 7 | Dagger | Melee weapon now mapped from unknown list |
| 401 | Lead Pipe | Melee weapon now mapped from unknown list |

### Temporary (Category: Temporary)

| Item ID | Item Name | Notes |
|---------|-----------|-------|
| 242 | HEG | Explosive temporary item |
| 220 | Grenade | Explosive temporary item |
| 222 | Flash Grenade | Flash temporary item |
| 226 | Smoke Grenade | Smoke temporary item |
| 392 | Pepper Spray | Temporary combat item |
| 256 | Tear Gas | Temporary gas item |
| 1042 | Concussion Grenade | Temporary explosive |

Additional temporarys mapped in parser include Molotov Cocktail (742) and Claymore Mine (229).

### Other Common Items

Other items may be deposited or used in the armoury. If an item's ID is not in the mapping above, it will default to ID 0 and category "Unknown" until added to the system. You can still set prices manually:

```bash
# To find an item's ID, search the database:
# SELECT DISTINCT item_id, item_name FROM armoury_news 
#   WHERE item_name LIKE '%Lollipop%' LIMIT 1

# Then set its price
python main.py prices set --item_id <id> --price <amount>
```

### Finding Unmapped Item IDs

If an item appears in armoury reports but has ID 0, you can find its real ID:

```bash
# Query the database for items with ID 0
SELECT DISTINCT item_name, COUNT(*) as usage_count 
FROM armoury_news 
WHERE item_id = 0 
GROUP BY item_name 
ORDER BY usage_count DESC;

# For common items, you can add them to the parser's ITEM_ID_MAPPING
# File: modules/armoury/parser.py
# Then run the backfill script to update existing records:
python scripts/backfill_item_ids.py

# Optional: generate parser mapping suggestions automatically
# from current Unknown/missing-ID rows using Torn item metadata
python scripts/suggest_unknown_item_mappings.py
```

---

## Typical Workflow

```bash
# 1. One-time: import all history (~10 months, ~5-10 minutes)
python main.py sync chains --mode backfill
python main.py sync attacks --mode backfill
python main.py sync rankedwars --mode backfill
python main.py sync armoury --mode backfill

# 2. Set item prices for cost calculations
python main.py prices set --item_id 148 --price 1500    # Xanax
python main.py prices set --item_id 149 --price 1800    # Morphine
python main.py prices set --item_id 150 --price 500     # Vicodin
python main.py prices set --item_id 161 --price 100     # Empty Blood Bag

# 3. For ranked war analysis: get war details and find chains that occurred during it
python main.py sync rankedwars --mode backfill  # Already synced, but use this to refresh
# Query: SELECT war_id, war_start, war_end FROM rankedwars WHERE war_id = 43902
# Then backtrack chains from that period:
python main.py sync chains --mode backfill --from 1781956800 --to 1781969561

# 4. For chain analysis: find a specific chain
#    Query: SELECT chain_id, chain_number, timestamp_start, timestamp_end
#           FROM chains WHERE chain_number = 5000 ORDER BY timestamp_start DESC

# 5. Sync attacks for that chain's time window
python main.py sync attacks --mode backfill --from 1783679454 --to 1783817462

# 6. Run reports
python main.py report attacks chain_leaderboard --chain_id 65999465
python main.py report attacks chain_stats --chain_id 65999465
python main.py report attacks chain_hit --chain_id 65999465 --hit_number 4000

# 7. For ranked war analysis, run reports and payouts
python main.py report rankedwars war_stats --war_id 43153
python main.py report rankedwars war_leaderboard --war_id 43153
python main.py report rankedwars war_player --war_id 43153 --player Ruztytitan
python main.py payout rankedwars --war_id 43153 --total_payout 50000

# 8. Analyze armoury usage (now with cost tracking)
python main.py report armoury category --category Drug
python main.py report armoury category --category Medical
python main.py report armoury player_usage --player 12345
python main.py report armoury medical_summary

# 9. Keep data current going forward
python main.py watch attacks --cooldown 10
python main.py watch chains
python main.py watch armoury
```
