# LumeQueue

A private Discord LFG (looking-for-group) bot for a small Italian gaming community.
It helps members of a single Discord server find teammates for **League of Legends**
and **Valorant**.

## What it does

- `/lol` and `/valorant` — post a "looking for duo/trio/full team" card with game
  mode, role/lane, rank and main champion/agent. Other members join with one click;
  the card shows the team composition in real time.
- When a group is full, the bot opens a thread and DMs every member the group's
  Riot IDs so they can invite each other in the game client.
- `/stasera` ("tonight") — members post the time they are available; the bot
  notifies compatible players when their schedules overlap.
- `/chimica` ("chemistry") — shows how many sessions two members have played
  together, based on groups formed through the bot.
- `/recap` — posts the result of the requesting member's most recent League of
  Legends match (win/loss, champion, KDA), recognizing other server members who
  played in the same game.

## Riot API usage

The Riot API is used **only** by the `/recap` command, on demand (when a member
explicitly runs the command). No background polling, no data scraping.

Endpoints used:

| Endpoint | Purpose |
|---|---|
| `account-v1` (`/riot/account/v1/accounts/by-riot-id`) | Resolve the member's saved Riot ID to a PUUID |
| `match-v5` (`/lol/match/v5/matches/by-puuid/.../ids`, `/lol/match/v5/matches/{id}`) | Fetch the member's single most recent match |

Expected volume is very low: the bot serves one private Discord server with
fewer than 30 active members, so requests are sporadic (a handful per day).

Riot IDs are provided voluntarily by members via the `/profilo` command and are
stored only to display them in group cards and match recaps. No other personal
data is collected.

## Self-hosting

1. Create a Discord application and bot at the Discord Developer Portal, invite
   it to your server with the `bot` and `applications.commands` scopes.
2. Put your Discord bot token in a `token.txt` file next to `bot.py` (or set the
   `DISCORD_TOKEN` environment variable).
3. Optional, enables `/recap`: put your Riot API key in `riot_key.txt` (or set
   `RIOT_API_KEY`).
4. Install dependencies and run:

```bash
pip install -r requirements.txt
python bot.py
```

Runtime data (member profiles, open searches, session history) is stored in
plain JSON files under `data/`.

## Disclaimer

LumeQueue is not endorsed by Riot Games and does not reflect the views or
opinions of Riot Games or anyone officially involved in producing or managing
Riot Games properties. Riot Games and all associated properties are trademarks
or registered trademarks of Riot Games, Inc.
