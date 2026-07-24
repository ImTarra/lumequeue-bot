"""
LumeQueue v4 - LFG per League of Legends e Valorant
- /lol e /valorant: cerca duo/trio/full team con modalita', ruolo, elo
- chi entra dichiara ruolo ed elo (dove ha senso), visibili nella card
- ping automatico dei ruoli liberi; /setupruoli crea ruoli e pannello
- a gruppo pieno: thread + DM con i Riot ID
"""

import os
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

DURATA_ORE = 4
TIMEZONE = ZoneInfo("Europe/Rome")  # fuso per /stasera
FINESTRA_INCASTRO_MIN = 60          # minuti di tolleranza per l'incastro orari
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PROFILI_FILE = DATA_DIR / "profili.json"
ATTIVE_FILE = DATA_DIR / "attive.json"
DISPONIBILITA_FILE = DATA_DIR / "disponibilita.json"
STORICO_FILE = DATA_DIR / "storico.json"


def carica_token() -> str:
    t = os.environ.get("DISCORD_TOKEN")
    if t and t.strip():
        return t.strip()
    f = Path(__file__).parent / "token.txt"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "Token mancante. Imposta DISCORD_TOKEN nel pannello "
        "oppure crea un file token.txt con dentro solo il token."
    )


TOKEN = carica_token()


def carica_riot_key() -> str | None:
    """Chiave Riot API, facoltativa: senza, /recap resta disattivato."""
    k = os.environ.get("RIOT_API_KEY")
    if k and k.strip():
        return k.strip()
    f = Path(__file__).parent / "riot_key.txt"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    return None


RIOT_KEY = carica_riot_key()
RIOT_ROUTING = "europe"  # EUW/EUNE -> europe; americas / asia per altre regioni

GRUPPI = {"Duo": 2, "Trio": 3, "Full team": 5}
RUOLO_LFG = "LFG"  # ruolo generico pingato per le modalita' senza ruoli

# ------------------------------- League of Legends --------------------------

LOL_MODALITA = {
    "SoloQ / DuoQ": "🏆",
    "Flex": "🛡️",
    "Normal Draft": "📋",
    "ARAM": "❄️",
    "Clash": "⚔️",
    "Custom / Scrim": "🎮",
}
LOL_RUOLI = ["Top", "Jungle", "Mid", "ADC", "Support", "Fill"]
LOL_ELO = {
    "Iron": 0x51484A, "Bronze": 0x8C5237, "Silver": 0x95A3A9,
    "Gold": 0xD6A22F, "Platinum": 0x4E9996, "Emerald": 0x2E9E5B,
    "Diamond": 0x576BCE, "Master": 0x9D4EDD, "Grandmaster": 0xC0392B,
    "Challenger": 0x27B4E8, "Non ranked": 0x7F8C8D,
}

# ------------------------------- Valorant -----------------------------------

VALO_MODALITA = {
    "Competitiva": "🏆",
    "Premier": "⚔️",
    "Unrated": "📋",
    "Swiftplay": "⚡",
    "Spike Rush": "💨",
    "Custom / Scrim": "🎮",
}
VALO_RUOLI = ["Duelist", "Controller", "Initiator", "Sentinel", "Flex"]
VALO_ELO = {
    "Iron": 0x51484A, "Bronze": 0x8C5237, "Silver": 0x95A3A9,
    "Gold": 0xD6A22F, "Platinum": 0x39A8A8, "Diamond": 0xC77DF3,
    "Ascendant": 0x2BB673, "Immortal": 0xBB3A5E, "Radiant": 0xF5D547,
    "Non ranked": 0x7F8C8D,
}

# ------------------------------- Registro giochi ----------------------------

GIOCHI = {
    "lol": {
        "nome": "League of Legends",
        "modalita": LOL_MODALITA,
        "ruoli": LOL_RUOLI,
        "jolly": "Fill",             # ruolo che non conta come duplicato
        "elo": LOL_ELO,
        "senza_ruoli": {"ARAM", "Custom / Scrim"},
        "label_ruolo": "LANE",
        "label_main": "MAIN",
        "emoji_ruoli": {},           # riempite all'avvio da carica_emoji
        "emoji_elo": {},
    },
    "valorant": {
        "nome": "Valorant",
        "modalita": VALO_MODALITA,
        "ruoli": VALO_RUOLI,
        "jolly": "Flex",
        "elo": VALO_ELO,
        "senza_ruoli": {"Spike Rush", "Custom / Scrim"},
        "label_ruolo": "RUOLO",
        "label_main": "MAIN",
        "emoji_ruoli": {},
        "emoji_elo": {},
    },
}

# ------------------------------- Emoji: matching automatico -----------------
# Le emoji vanno caricate sull'applicazione (portale sviluppatori -> Emojis).
# Regola: se il nome contiene "valorant" appartiene a Valorant, altrimenti a
# LoL; poi si cerca la parola chiave. L'ordine conta (grandmaster < master).

CHIAVI_RUOLI_LOL = [
    ("jungle", "Jungle"), ("top", "Top"), ("mid", "Mid"),
    ("support", "Support"), ("fill", "Fill"), ("bot", "ADC"), ("adc", "ADC"),
]
CHIAVI_ELO_LOL = [
    ("grandmaster", "Grandmaster"), ("master", "Master"),
    ("challenger", "Challenger"), ("diamond", "Diamond"),
    ("emerald", "Emerald"), ("platinum", "Platinum"), ("gold", "Gold"),
    ("silver", "Silver"), ("bronze", "Bronze"), ("iron", "Iron"),
]
CHIAVI_RUOLI_VALO = [
    ("duelist", "Duelist"), ("controller", "Controller"),
    ("initiator", "Initiator"), ("sentinel", "Sentinel"), ("flex", "Flex"),
]
CHIAVI_ELO_VALO = [
    ("radiant", "Radiant"), ("immortal", "Immortal"),
    ("ascendant", "Ascendant"), ("diamond", "Diamond"),
    ("platinum", "Platinum"), ("gold", "Gold"), ("silver", "Silver"),
    ("bronze", "Bronze"), ("iron", "Iron"),
]


def _assegna(nome: str, tag: str, chiavi_ruoli, chiavi_elo, cfg):
    for parola, ruolo in chiavi_ruoli:
        if parola in nome and ruolo not in cfg["emoji_ruoli"]:
            cfg["emoji_ruoli"][ruolo] = tag
            return
    for parola, elo in chiavi_elo:
        if parola in nome and elo not in cfg["emoji_elo"]:
            cfg["emoji_elo"][elo] = tag
            return


async def carica_emoji(bot: commands.Bot):
    try:
        lista = await bot.fetch_application_emojis()
    except discord.HTTPException as err:
        print(f"Impossibile leggere le emoji dell'app: {err}")
        return

    for emoji in lista:
        nome = emoji.name.lower()
        tag = f"<:{emoji.name}:{emoji.id}>"
        if "valorant" in nome or "valo" in nome:
            _assegna(nome, tag, CHIAVI_RUOLI_VALO, CHIAVI_ELO_VALO,
                     GIOCHI["valorant"])
        else:
            _assegna(nome, tag, CHIAVI_RUOLI_LOL, CHIAVI_ELO_LOL,
                     GIOCHI["lol"])

    for gid, cfg in GIOCHI.items():
        mancanti = [r for r in cfg["ruoli"] if r not in cfg["emoji_ruoli"]]
        mancanti += [e for e in cfg["elo"]
                     if e not in cfg["emoji_elo"] and e != "Non ranked"]
        print(f"[{cfg['nome']}] emoji: {len(cfg['emoji_ruoli'])} ruoli, "
              f"{len(cfg['emoji_elo'])} elo."
              + (f" Mancanti: {', '.join(mancanti)}" if mancanti else ""))


def con_emoji(mappa: dict, valore: str) -> str:
    e = mappa.get(valore, "")
    return f"{e} {valore}".strip()


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------


def leggi(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def scrivi(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


profili = leggi(PROFILI_FILE, {})
# profili[uid] = {"riot_id": ..., "lol": {"ruolo","elo","main"}, "valorant": {...}}
attive = leggi(ATTIVE_FILE, {})
disponibilita = leggi(DISPONIBILITA_FILE, [])
# [{"user","guild","canale","gioco","quando","nota"}]
storico = leggi(STORICO_FILE, [])
# [{"id","guild","gioco","membri":[ids],"data","voti":{uid: +1/-1}}]


def serate_insieme(a: int, b: int) -> int:
    return sum(1 for s in storico if a in s.get("membri", []) and b in s.get("membri", []))


def chiave(channel_id: int, message_id: int) -> str:
    return f"{channel_id}:{message_id}"


def trova_membro(dati: dict, user_id: int):
    for m in dati["membri"]:
        if m["id"] == user_id:
            return m
    return None


def cfg_di(dati: dict) -> dict:
    return GIOCHI[dati.get("gioco", "lol")]


# ----------------------------------------------------------------------------
# Ruoli del server (per i ping)
# ----------------------------------------------------------------------------


def ruolo_per_nome(guild: discord.Guild, nome: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=nome)


def ruoli_liberi(dati: dict) -> list[str]:
    cfg = cfg_di(dati)
    occupati = {m.get("ruolo") for m in dati["membri"] if m.get("ruolo")}
    return [r for r in cfg["ruoli"] if r != cfg["jolly"] and r not in occupati]


def testo_ping(guild: discord.Guild, dati: dict) -> str:
    cfg = cfg_di(dati)
    if dati["modalita"] in cfg["senza_ruoli"]:
        r = ruolo_per_nome(guild, RUOLO_LFG)
        return r.mention if r else ""
    menzioni = []
    for nome in ruoli_liberi(dati):
        r = ruolo_per_nome(guild, nome)
        if r:
            menzioni.append(r.mention)
    return " ".join(menzioni)


# ----------------------------------------------------------------------------
# Card
# ----------------------------------------------------------------------------


def riga_membro(guild: discord.Guild, dati: dict, m: dict) -> str:
    cfg = cfg_di(dati)
    utente = guild.get_member(m["id"])
    riga = utente.mention if utente else f"<@{m['id']}>"

    if dati["modalita"] not in cfg["senza_ruoli"]:
        extra = []
        if m.get("ruolo"):
            extra.append(con_emoji(cfg["emoji_ruoli"], m["ruolo"]))
        if m.get("elo"):
            extra.append(con_emoji(cfg["emoji_elo"], m["elo"]))
        if extra:
            riga += f" — {' · '.join(extra)}"

    if m["id"] == dati["autore"]:
        riga += " *(host)*"
    else:
        n = serate_insieme(m["id"], dati["autore"])
        if n:
            riga += f" · 🔁 {n}"
    return riga


def crea_card(guild: discord.Guild, dati: dict, stato: str = "aperta") -> discord.Embed:
    cfg = cfg_di(dati)
    posti = GRUPPI[dati["gruppo"]]
    emoji_mod = cfg["modalita"].get(dati["modalita"], "🎮")
    senza_ruoli = dati["modalita"] in cfg["senza_ruoli"]

    if stato == "pieno":
        titolo = f"{emoji_mod} {dati['modalita']} — GRUPPO COMPLETO ✅"
        colore = 0x57F287
    elif stato == "chiusa":
        titolo = f"{emoji_mod} {dati['modalita']} — CHIUSA"
        colore = 0x3B3B3B
    elif stato == "scaduta":
        titolo = f"{emoji_mod} {dati['modalita']} — SCADUTA ⏳"
        colore = 0x3B3B3B
    else:
        titolo = f"{emoji_mod} {dati['modalita']} — CERCO {dati['gruppo'].upper()} 🔎"
        colore = 0x5865F2 if senza_ruoli else cfg["elo"].get(dati["elo"], 0x5865F2)

    autore = guild.get_member(dati["autore"])
    nome = dati.get("riot_id") or (autore.display_name if autore else "Sconosciuto")

    e = discord.Embed(title=titolo, colour=colore)
    if autore:
        e.set_author(name=f"{nome} · {cfg['nome']}",
                     icon_url=autore.display_avatar.url)

    if not senza_ruoli:
        if dati.get("main"):
            e.add_field(name=cfg["label_main"], value=f"**{dati['main']}**",
                        inline=True)
        if dati.get("ruolo"):
            e.add_field(
                name=cfg["label_ruolo"],
                value=f"**{con_emoji(cfg['emoji_ruoli'], dati['ruolo'])}**",
                inline=True,
            )
        if dati.get("elo"):
            e.add_field(
                name="ELO",
                value=f"**{con_emoji(cfg['emoji_elo'], dati['elo'])}**",
                inline=True,
            )

    righe = [riga_membro(guild, dati, m) for m in dati["membri"]]
    righe += ["— *posto libero*"] * (posti - len(dati["membri"]))
    e.add_field(
        name=f"SQUADRA {len(dati['membri'])}/{posti}",
        value="\n".join(righe),
        inline=False,
    )

    if dati.get("nota"):
        e.add_field(name="Note", value=dati["nota"][:200], inline=False)

    if stato == "aperta":
        e.set_footer(text=f"Scade tra {DURATA_ORE}h · premi Entra per unirti")
    elif stato == "pieno":
        e.set_footer(text="Gruppo al completo — controllate i DM")
    return e


# ----------------------------------------------------------------------------
# Voto di fine serata (memoria dei duo)
# ----------------------------------------------------------------------------


class BottoneVoto(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"duo:vote:(?P<sid>\d+):(?P<val>up|down)",
):
    def __init__(self, sid: int, val: str):
        super().__init__(
            discord.ui.Button(
                label="Bella serata" if val == "up" else "Meh",
                emoji="👍" if val == "up" else "👎",
                style=discord.ButtonStyle.success if val == "up"
                else discord.ButtonStyle.secondary,
                custom_id=f"duo:vote:{sid}:{val}",
            )
        )
        self.sid = sid
        self.val = val

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]), match["val"])

    async def callback(self, interaction: discord.Interaction):
        sessione = next((s for s in storico if s.get("id") == self.sid), None)
        if sessione is None:
            return await interaction.response.send_message(
                "Sessione non trovata nello storico.", ephemeral=True
            )
        if interaction.user.id not in sessione.get("membri", []):
            return await interaction.response.send_message(
                "Solo chi ha giocato in questo gruppo può votare.", ephemeral=True
            )
        sessione.setdefault("voti", {})[str(interaction.user.id)] = (
            1 if self.val == "up" else -1
        )
        scrivi(STORICO_FILE, storico)
        await interaction.response.send_message(
            "Voto registrato! Puoi cambiarlo ripremendo l'altro bottone.",
            ephemeral=True,
        )


# ----------------------------------------------------------------------------
# Completamento gruppo
# ----------------------------------------------------------------------------


async def gruppo_completo(interaction: discord.Interaction, dati: dict,
                          messaggio: discord.Message):
    guild = interaction.guild
    cfg = cfg_di(dati)
    membri = [(m, guild.get_member(m["id"])) for m in dati["membri"]]
    membri = [(m, u) for m, u in membri if u]

    righe = []
    for m, u in membri:
        p = profili.get(str(u.id), {})
        riot = p.get("riot_id")
        riga = f"**{riot or u.display_name}**"
        if not riot:
            riga += " *(nessun Riot ID salvato — usa /profilo)*"
        if dati["modalita"] not in cfg["senza_ruoli"] and m.get("ruolo"):
            riga += (
                f" — {con_emoji(cfg['emoji_ruoli'], m['ruolo'])}"
                f" · {con_emoji(cfg['emoji_elo'], m.get('elo') or '?')}"
            )
        righe.append(riga)

    testo = "\n".join(righe)
    menzioni = " ".join(u.mention for _, u in membri)

    # memoria dei duo: registra la sessione
    sid = int(discord.utils.utcnow().timestamp())
    storico.append({
        "id": sid,
        "guild": guild.id,
        "gioco": dati.get("gioco", "lol"),
        "membri": [m["id"] for m, _ in membri],
        "data": discord.utils.utcnow().isoformat(),
        "voti": {},
    })
    scrivi(STORICO_FILE, storico)

    vista_voto = discord.ui.View(timeout=None)
    vista_voto.add_item(BottoneVoto(sid, "up"))
    vista_voto.add_item(BottoneVoto(sid, "down"))

    try:
        thread = await messaggio.create_thread(
            name=f"{cfg['nome']} — {dati['modalita']}",
            auto_archive_duration=1440,
        )
        await thread.send(
            f"Gruppo al completo! {menzioni}\n\n"
            f"**Riot ID per invitarvi nel client:**\n{testo}\n\n"
            "A fine serata votate com'è andata 👇",
            view=vista_voto,
        )
        link = thread.mention
    except (discord.Forbidden, discord.HTTPException):
        await messaggio.channel.send(
            f"Gruppo al completo! {menzioni}\n\n**Riot ID:**\n{testo}",
            view=vista_voto,
        )
        link = messaggio.channel.mention

    dm = discord.Embed(
        title="Gruppo al completo!",
        description=(
            f"**{cfg['nome']}** · {dati['modalita']} · {dati['gruppo']}\n\n{testo}"
        ),
        colour=0x57F287,
    )
    dm.add_field(name="Dove", value=f"{link} in **{guild.name}**")
    for _, u in membri:
        try:
            await u.send(embed=dm)
        except discord.Forbidden:
            pass


async def aggiungi_membro(interaction: discord.Interaction, k: str,
                          canale_id: int, messaggio_id: int,
                          ruolo: str | None, elo: str | None):
    dati = attive.get(k)
    if not dati:
        return "Questa richiesta non è più attiva."
    if trova_membro(dati, interaction.user.id):
        return "Sei già in questo gruppo."
    if len(dati["membri"]) >= GRUPPI[dati["gruppo"]]:
        return "Il gruppo si è riempito un attimo fa, mi spiace."

    dati["membri"].append({"id": interaction.user.id, "ruolo": ruolo, "elo": elo})

    if ruolo or elo:
        p = profili.setdefault(str(interaction.user.id), {})
        pg = p.setdefault(dati.get("gioco", "lol"), {})
        if ruolo:
            pg["ruolo"] = ruolo
        if elo:
            pg["elo"] = elo
        scrivi(PROFILI_FILE, profili)

    canale = interaction.guild.get_channel(canale_id)
    try:
        messaggio = await canale.fetch_message(messaggio_id)
    except (discord.NotFound, discord.Forbidden, AttributeError):
        dati["membri"] = [m for m in dati["membri"] if m["id"] != interaction.user.id]
        return "Non trovo più il messaggio della richiesta."

    pieno = len(dati["membri"]) >= GRUPPI[dati["gruppo"]]
    if pieno:
        await messaggio.edit(embed=crea_card(interaction.guild, dati, "pieno"),
                             view=None)
        await gruppo_completo(interaction, dati, messaggio)
        attive.pop(k, None)
    else:
        await messaggio.edit(embed=crea_card(interaction.guild, dati, "aperta"))
    scrivi(ATTIVE_FILE, attive)
    return "Sei dentro! 🤝" + (" Il gruppo è al completo, controlla i DM." if pieno else "")


# ----------------------------------------------------------------------------
# Selezione ruolo/elo per chi entra (effimera)
# ----------------------------------------------------------------------------


class SceltaIngresso(discord.ui.View):
    def __init__(self, k: str, canale_id: int, messaggio_id: int, gioco: str,
                 ruolo_default: str | None, elo_default: str | None):
        super().__init__(timeout=120)
        self.k = k
        self.canale_id = canale_id
        self.messaggio_id = messaggio_id
        self.gioco = gioco
        self.ruolo = ruolo_default
        self.elo = elo_default
        self.forza = False
        cfg = GIOCHI[gioco]

        def parziale(mappa, valore):
            s = mappa.get(valore)
            return discord.PartialEmoji.from_str(s) if s else None

        sel_ruolo = discord.ui.Select(
            placeholder=f"Il tuo {cfg['label_ruolo'].lower()}",
            options=[
                discord.SelectOption(
                    label=r,
                    emoji=parziale(cfg["emoji_ruoli"], r),
                    default=(r == ruolo_default),
                )
                for r in cfg["ruoli"]
            ],
        )
        sel_ruolo.callback = self.scegli_ruolo
        self.add_item(sel_ruolo)

        sel_elo = discord.ui.Select(
            placeholder="Il tuo elo",
            options=[
                discord.SelectOption(
                    label=e,
                    emoji=parziale(cfg["emoji_elo"], e),
                    default=(e == elo_default),
                )
                for e in cfg["elo"]
            ],
        )
        sel_elo.callback = self.scegli_elo
        self.add_item(sel_elo)

    async def scegli_ruolo(self, interaction: discord.Interaction):
        self.ruolo = interaction.data["values"][0]
        self.forza = False
        await interaction.response.defer()

    async def scegli_elo(self, interaction: discord.Interaction):
        self.elo = interaction.data["values"][0]
        await interaction.response.defer()

    @discord.ui.button(label="Conferma", style=discord.ButtonStyle.success,
                       emoji="✅", row=2)
    async def conferma(self, interaction: discord.Interaction, _):
        if not self.ruolo or not self.elo:
            return await interaction.response.send_message(
                "Scegli sia il ruolo che l'elo prima di confermare.",
                ephemeral=True,
            )

        dati = attive.get(self.k)
        cfg = GIOCHI[self.gioco]
        if dati and self.ruolo != cfg["jolly"] and not self.forza:
            occupati = {m.get("ruolo") for m in dati["membri"]}
            if self.ruolo in occupati:
                self.forza = True
                return await interaction.response.edit_message(
                    content=(
                        f"⚠️ C'è già un **{self.ruolo}** in questo gruppo. "
                        "Cambia ruolo, oppure premi di nuovo **Conferma** "
                        "per entrare lo stesso."
                    ),
                    view=self,
                )

        esito = await aggiungi_membro(
            interaction, self.k, self.canale_id, self.messaggio_id,
            self.ruolo, self.elo,
        )
        self.stop()
        await interaction.response.edit_message(content=esito, view=None)


# ----------------------------------------------------------------------------
# Bottoni sulla card
# ----------------------------------------------------------------------------


class BottoneEntra(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"duo:join:(?P<autore>\d+)",
):
    def __init__(self, autore: int):
        super().__init__(
            discord.ui.Button(
                label="Entra", emoji="🤝",
                style=discord.ButtonStyle.success,
                custom_id=f"duo:join:{autore}",
            )
        )
        self.autore = autore

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["autore"]))

    async def callback(self, interaction: discord.Interaction):
        k = chiave(interaction.channel_id, interaction.message.id)
        dati = attive.get(k)
        if not dati:
            return await interaction.response.send_message(
                "Questa richiesta non è più attiva.", ephemeral=True
            )
        if trova_membro(dati, interaction.user.id):
            return await interaction.response.send_message(
                "Sei già in questo gruppo. Usa **Esci** se hai cambiato idea.",
                ephemeral=True,
            )
        if len(dati["membri"]) >= GRUPPI[dati["gruppo"]]:
            return await interaction.response.send_message(
                "Il gruppo è già al completo.", ephemeral=True
            )

        cfg = cfg_di(dati)
        if dati["modalita"] in cfg["senza_ruoli"]:
            esito = await aggiungi_membro(
                interaction, k, interaction.channel_id, interaction.message.id,
                None, None,
            )
            return await interaction.response.send_message(esito, ephemeral=True)

        gioco = dati.get("gioco", "lol")
        p = profili.get(str(interaction.user.id), {}).get(gioco, {})
        view = SceltaIngresso(
            k, interaction.channel_id, interaction.message.id, gioco,
            p.get("ruolo"), p.get("elo"),
        )
        await interaction.response.send_message(
            "Dimmi come giochi, poi conferma:", view=view, ephemeral=True
        )


class BottoneEsci(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"duo:leave:(?P<autore>\d+)",
):
    def __init__(self, autore: int):
        super().__init__(
            discord.ui.Button(
                label="Esci",
                style=discord.ButtonStyle.secondary,
                custom_id=f"duo:leave:{autore}",
            )
        )
        self.autore = autore

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["autore"]))

    async def callback(self, interaction: discord.Interaction):
        k = chiave(interaction.channel_id, interaction.message.id)
        dati = attive.get(k)
        m = dati and trova_membro(dati, interaction.user.id)
        if not m:
            return await interaction.response.send_message(
                "Non fai parte di questo gruppo.", ephemeral=True
            )
        if interaction.user.id == dati["autore"]:
            return await interaction.response.send_message(
                "Sei l'host: usa **Chiudi** per annullare la ricerca.",
                ephemeral=True,
            )

        dati["membri"].remove(m)
        scrivi(ATTIVE_FILE, attive)
        await interaction.response.edit_message(
            embed=crea_card(interaction.guild, dati, "aperta")
        )


class BottoneChiudi(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"duo:close:(?P<autore>\d+)",
):
    def __init__(self, autore: int):
        super().__init__(
            discord.ui.Button(
                label="Chiudi", emoji="✖️",
                style=discord.ButtonStyle.danger,
                custom_id=f"duo:close:{autore}",
            )
        )
        self.autore = autore

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["autore"]))

    async def callback(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.autore
            and not interaction.user.guild_permissions.manage_messages
        ):
            return await interaction.response.send_message(
                "Solo l'host può chiudere la ricerca.", ephemeral=True
            )
        k = chiave(interaction.channel_id, interaction.message.id)
        dati = attive.pop(k, None)
        scrivi(ATTIVE_FILE, attive)
        if dati:
            embed = crea_card(interaction.guild, dati, "chiusa")
        else:
            embed = interaction.message.embeds[0]
            embed.colour = discord.Colour(0x3B3B3B)
        await interaction.response.edit_message(embed=embed, view=None)


def crea_view(autore: int) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(BottoneEntra(autore))
    v.add_item(BottoneEsci(autore))
    v.add_item(BottoneChiudi(autore))
    return v


# ----------------------------------------------------------------------------
# Auto-assegnazione ruoli
# ----------------------------------------------------------------------------


class BottoneRuolo(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"duo:role:(?P<nome>\w+)",
):
    def __init__(self, nome: str):
        super().__init__(
            discord.ui.Button(
                label=nome,
                style=discord.ButtonStyle.primary,
                custom_id=f"duo:role:{nome}",
            )
        )
        self.nome = nome

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["nome"])

    async def callback(self, interaction: discord.Interaction):
        ruolo = ruolo_per_nome(interaction.guild, self.nome)
        if ruolo is None:
            return await interaction.response.send_message(
                f"Il ruolo **{self.nome}** non esiste più: un admin deve "
                "rilanciare `/setupruoli`.",
                ephemeral=True,
            )
        try:
            if ruolo in interaction.user.roles:
                await interaction.user.remove_roles(ruolo)
                testo = f"Ruolo **{self.nome}** rimosso: niente più ping."
            else:
                await interaction.user.add_roles(ruolo)
                testo = (
                    f"Ruolo **{self.nome}** assegnato! Verrai pingato quando "
                    "qualcuno cerca quel ruolo."
                )
        except discord.Forbidden:
            testo = (
                "Non ho il permesso di gestire i ruoli, oppure il ruolo è "
                "sopra il mio nella lista: un admin deve sistemare la gerarchia."
            )
        await interaction.response.send_message(testo, ephemeral=True)


# ----------------------------------------------------------------------------
# Bot
# ----------------------------------------------------------------------------


class LumeQueue(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        self.add_dynamic_items(
            BottoneEntra, BottoneEsci, BottoneChiudi, BottoneRuolo, BottoneVoto
        )
        await carica_emoji(self)
        await self.tree.sync()
        pulizia.start()


bot = LumeQueue()


@bot.event
async def on_ready():
    print(f"Online come {bot.user} — {len(bot.guilds)} server")


def salta_cooldown_admin(i: discord.Interaction):
    if i.user.guild_permissions.administrator:
        return None
    return app_commands.Cooldown(1, 600)


async def crea_ricerca(
    interaction: discord.Interaction, gioco: str,
    modalita: str, gruppo: str,
    elo: str | None, ruolo: str | None, main: str | None,
    riot_id: str | None, nota: str | None,
):
    cfg = GIOCHI[gioco]
    if modalita not in cfg["senza_ruoli"] and elo is None:
        return await interaction.response.send_message(
            f"Per **{modalita}** indica il tuo `elo`.", ephemeral=True
        )

    dati = {
        "gioco": gioco,
        "autore": interaction.user.id,
        "modalita": modalita,
        "gruppo": gruppo,
        "elo": elo,
        "main": main.strip()[:40] if main else None,
        "ruolo": ruolo,
        "riot_id": riot_id.strip()[:40] if riot_id else None,
        "nota": nota,
        "membri": [{"id": interaction.user.id, "ruolo": ruolo, "elo": elo}],
        "scade": (
            discord.utils.utcnow() + datetime.timedelta(hours=DURATA_ORE)
        ).isoformat(),
    }

    p = profili.setdefault(str(interaction.user.id), {})
    if dati["riot_id"]:
        p["riot_id"] = dati["riot_id"]
    pg = p.setdefault(gioco, {})
    for campo, valore in (("main", dati["main"]), ("ruolo", ruolo), ("elo", elo)):
        if valore:
            pg[campo] = valore
    scrivi(PROFILI_FILE, profili)

    ping = testo_ping(interaction.guild, dati)
    await interaction.response.send_message(
        content=ping or None,
        embed=crea_card(interaction.guild, dati),
        view=crea_view(interaction.user.id),
        allowed_mentions=discord.AllowedMentions(roles=True),
    )
    msg = await interaction.original_response()
    attive[chiave(interaction.channel_id, msg.id)] = dati
    scrivi(ATTIVE_FILE, attive)


# ------------------------------- /lol ---------------------------------------


@bot.tree.command(name="lol", description="Cerca duo o squadra per League of Legends")
@app_commands.describe(
    modalita="Che coda vuoi fare",
    gruppo="Quante persone in totale (te compreso)",
    elo="Il tuo elo (non serve per ARAM/Custom)",
    lane="Facoltativo: la lane che giochi",
    main="Facoltativo: il tuo campione main",
    riot_id="Facoltativo: il tuo Riot ID, es. Nome#EUW",
    nota="Facoltativo: orari, obiettivi, lingua...",
)
@app_commands.choices(
    modalita=[app_commands.Choice(name=f"{v} {k}", value=k)
              for k, v in LOL_MODALITA.items()],
    gruppo=[app_commands.Choice(name=f"{k} ({v} giocatori)", value=k)
            for k, v in GRUPPI.items()],
    elo=[app_commands.Choice(name=k, value=k) for k in LOL_ELO],
    lane=[app_commands.Choice(name=r, value=r) for r in LOL_RUOLI],
)
@app_commands.checks.dynamic_cooldown(salta_cooldown_admin)
async def lol(
    interaction: discord.Interaction,
    modalita: app_commands.Choice[str],
    gruppo: app_commands.Choice[str],
    elo: app_commands.Choice[str] | None = None,
    lane: app_commands.Choice[str] | None = None,
    main: str | None = None,
    riot_id: str | None = None,
    nota: str | None = None,
):
    await crea_ricerca(
        interaction, "lol", modalita.value, gruppo.value,
        elo.value if elo else None, lane.value if lane else None,
        main, riot_id, nota,
    )


# ------------------------------- /valorant ----------------------------------


@bot.tree.command(name="valorant", description="Cerca duo o squadra per Valorant")
@app_commands.describe(
    modalita="Che coda vuoi fare",
    gruppo="Quante persone in totale (te compreso)",
    elo="Il tuo rank (non serve per Spike Rush/Custom)",
    ruolo="Facoltativo: il ruolo che giochi",
    main="Facoltativo: il tuo agente main",
    riot_id="Facoltativo: il tuo Riot ID, es. Nome#EUW",
    nota="Facoltativo: orari, obiettivi, lingua...",
)
@app_commands.choices(
    modalita=[app_commands.Choice(name=f"{v} {k}", value=k)
              for k, v in VALO_MODALITA.items()],
    gruppo=[app_commands.Choice(name=f"{k} ({v} giocatori)", value=k)
            for k, v in GRUPPI.items()],
    elo=[app_commands.Choice(name=k, value=k) for k in VALO_ELO],
    ruolo=[app_commands.Choice(name=r, value=r) for r in VALO_RUOLI],
)
@app_commands.checks.dynamic_cooldown(salta_cooldown_admin)
async def valorant(
    interaction: discord.Interaction,
    modalita: app_commands.Choice[str],
    gruppo: app_commands.Choice[str],
    elo: app_commands.Choice[str] | None = None,
    ruolo: app_commands.Choice[str] | None = None,
    main: str | None = None,
    riot_id: str | None = None,
    nota: str | None = None,
):
    await crea_ricerca(
        interaction, "valorant", modalita.value, gruppo.value,
        elo.value if elo else None, ruolo.value if ruolo else None,
        main, riot_id, nota,
    )


# ------------------------------- /profilo -----------------------------------


@bot.tree.command(name="profilo", description="Mostra o aggiorna il tuo profilo")
@app_commands.describe(riot_id="Il tuo Riot ID, es. Nome#EUW")
async def profilo(interaction: discord.Interaction, riot_id: str | None = None):
    uid = str(interaction.user.id)
    if riot_id:
        p = profili.setdefault(uid, {})
        p["riot_id"] = riot_id.strip()[:40]
        scrivi(PROFILI_FILE, profili)
        return await interaction.response.send_message(
            f"Riot ID salvato: **{p['riot_id']}**", ephemeral=True
        )
    p = profili.get(uid)
    if not p:
        return await interaction.response.send_message(
            "Non hai ancora un profilo. Usa `/lol`, `/valorant` o "
            "`/profilo riot_id:...`",
            ephemeral=True,
        )
    righe = []
    if p.get("riot_id"):
        righe.append(f"Riot ID: **{p['riot_id']}**")
    for gid in ("lol", "valorant"):
        pg = p.get(gid, {})
        if pg:
            dettagli = " · ".join(f"{v}" for v in pg.values() if v)
            righe.append(f"{GIOCHI[gid]['nome']}: **{dettagli}**")
    await interaction.response.send_message(
        "\n".join(righe) or "Profilo vuoto.", ephemeral=True
    )


# ------------------------------- /setupruoli --------------------------------


@bot.tree.command(
    name="setupruoli",
    description="(Admin) Crea i ruoli e il pannello per auto-assegnarseli",
)
@app_commands.default_permissions(administrator=True)
async def setupruoli(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Serve il permesso Amministratore.", ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    nomi_lol = [r for r in LOL_RUOLI if r != "Fill"]
    nomi_valo = [r for r in VALO_RUOLI if r != "Flex"]
    tutti = nomi_lol + nomi_valo + [RUOLO_LFG]

    creati = []
    try:
        for nome in tutti:
            if ruolo_per_nome(interaction.guild, nome) is None:
                await interaction.guild.create_role(
                    name=nome, mentionable=True,
                    reason="LumeQueue: ruoli per i ping LFG",
                )
                creati.append(nome)
    except discord.Forbidden:
        return await interaction.followup.send(
            "Mi manca il permesso **Gestisci ruoli**: aggiungilo al mio ruolo "
            "e rilancia il comando.",
            ephemeral=True,
        )

    e = discord.Embed(
        title="🔔 Notifiche ricerca gruppo",
        description=(
            "Premi i bottoni per scegliere per cosa vuoi essere pingato "
            "quando qualcuno cerca giocatori.\n"
            f"Prima riga: **LoL** · seconda riga: **Valorant** · "
            f"**{RUOLO_LFG}** per ARAM, Spike Rush e custom.\n"
            "Ripremi un bottone per togliere il ruolo."
        ),
        colour=0x5865F2,
    )
    v = discord.ui.View(timeout=None)
    for nome in nomi_lol:
        b = BottoneRuolo(nome)
        b.item.row = 0
        v.add_item(b)
    for nome in nomi_valo:
        b = BottoneRuolo(nome)
        b.item.row = 1
        v.add_item(b)
    b = BottoneRuolo(RUOLO_LFG)
    b.item.row = 2
    v.add_item(b)
    await interaction.channel.send(embed=e, view=v)

    msg = "Pannello pubblicato."
    if creati:
        msg += f" Ruoli creati: {', '.join(creati)}."
    await interaction.followup.send(msg, ephemeral=True)


# ------------------------------- /stasera -----------------------------------


def parse_ora(testo: str) -> datetime.datetime | None:
    """'21:30', '21.30', '2130' o '21' -> datetime di oggi (o domani se passata)."""
    t = testo.strip().replace(".", ":").replace(",", ":")
    if ":" not in t and t.isdigit():
        if len(t) == 4:
            t = f"{t[:2]}:{t[2:]}"
        elif len(t) == 3:
            t = f"{t[:1]}:{t[1:]}"
        else:
            t = f"{t}:00"
    try:
        h, m = (int(x) for x in t.split(":")[:2])
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        return None
    adesso = datetime.datetime.now(TIMEZONE)
    quando = adesso.replace(hour=h, minute=m, second=0, microsecond=0)
    if quando < adesso - datetime.timedelta(minutes=30):
        quando += datetime.timedelta(days=1)
    return quando


SCELTE_GIOCO = [
    app_commands.Choice(name="League of Legends", value="lol"),
    app_commands.Choice(name="Valorant", value="valorant"),
]


@bot.tree.command(
    name="stasera",
    description="Segna a che ora sei disponibile: il bot trova l'incastro per te",
)
@app_commands.describe(
    gioco="Per cosa sei disponibile",
    ora="A che ora, es. 21:30",
    nota="Facoltativo: modalità, obiettivi...",
)
@app_commands.choices(gioco=SCELTE_GIOCO)
async def stasera(
    interaction: discord.Interaction,
    gioco: app_commands.Choice[str],
    ora: str,
    nota: str | None = None,
):
    quando = parse_ora(ora)
    if quando is None:
        return await interaction.response.send_message(
            "Non capisco l'orario: scrivilo tipo `21:30`.", ephemeral=True
        )

    # una disponibilita' per gioco a testa: la nuova sostituisce la vecchia
    disponibilita[:] = [
        d for d in disponibilita
        if not (d["user"] == interaction.user.id and d["gioco"] == gioco.value)
    ]
    disponibilita.append({
        "user": interaction.user.id,
        "guild": interaction.guild_id,
        "canale": interaction.channel_id,
        "gioco": gioco.value,
        "quando": quando.isoformat(),
        "nota": nota,
    })
    scrivi(DISPONIBILITA_FILE, disponibilita)

    # cerca incastri: stesso server e gioco, orari entro la finestra
    compatibili = []
    for d in disponibilita:
        if (d["guild"] == interaction.guild_id and d["gioco"] == gioco.value
                and d["user"] != interaction.user.id):
            diff = abs((datetime.datetime.fromisoformat(d["quando"]) - quando)
                       .total_seconds()) / 60
            if diff <= FINESTRA_INCASTRO_MIN:
                compatibili.append(d)

    ora_txt = quando.strftime("%H:%M")
    cfg = GIOCHI[gioco.value]
    await interaction.response.send_message(
        f"Segnato: **{cfg['nome']}** alle **{ora_txt}**. "
        + (f"Ci sono già {len(compatibili)} persone in quella fascia!"
           if compatibili else
           "Ti avviso appena qualcuno segna un orario compatibile."),
        ephemeral=True,
    )

    if compatibili:
        menzioni = " ".join(f"<@{d['user']}>" for d in compatibili)
        orari = ", ".join(
            f"<@{d['user']}> alle "
            f"{datetime.datetime.fromisoformat(d['quando']).strftime('%H:%M')}"
            for d in compatibili
        )
        await interaction.channel.send(
            f"🔮 **Incastro trovato!** {interaction.user.mention} è disponibile "
            f"per **{cfg['nome']}** alle **{ora_txt}** — anche {orari}.\n"
            f"{menzioni} {interaction.user.mention}: uno di voi apra la card "
            f"con `/{gioco.value}` quando ci siete!",
            allowed_mentions=discord.AllowedMentions(users=True),
        )


@bot.tree.command(name="disponibili", description="Chi si è segnato per giocare oggi")
async def disponibili(interaction: discord.Interaction):
    del_server = [d for d in disponibilita if d["guild"] == interaction.guild_id]
    if not del_server:
        return await interaction.response.send_message(
            "Nessuna disponibilità segnata: sii il primo con `/stasera`!",
            ephemeral=True,
        )
    del_server.sort(key=lambda d: d["quando"])
    righe = []
    for d in del_server:
        q = datetime.datetime.fromisoformat(d["quando"]).strftime("%H:%M")
        r = f"**{q}** · {GIOCHI[d['gioco']]['nome']} · <@{d['user']}>"
        if d.get("nota"):
            r += f" — *{d['nota'][:60]}*"
        righe.append(r)
    e = discord.Embed(
        title="🌙 Disponibili oggi",
        description="\n".join(righe),
        colour=0x5865F2,
    )
    await interaction.response.send_message(embed=e)


# ------------------------------- /chimica -----------------------------------


@bot.tree.command(name="chimica", description="Quante serate hai fatto con qualcuno")
@app_commands.describe(utente="Con chi?")
async def chimica(interaction: discord.Interaction, utente: discord.Member):
    insieme = [
        s for s in storico
        if interaction.user.id in s.get("membri", [])
        and utente.id in s.get("membri", [])
    ]
    if not insieme:
        return await interaction.response.send_message(
            f"Tu e {utente.display_name} non avete ancora giocato insieme "
            "(tramite le card, almeno 👀).",
            ephemeral=True,
        )
    positivi = sum(
        1 for s in insieme
        if s.get("voti", {}).get(str(utente.id)) == 1
        and s.get("voti", {}).get(str(interaction.user.id)) == 1
    )
    ultima = max(s["data"] for s in insieme)
    ultima_txt = datetime.datetime.fromisoformat(ultima).astimezone(TIMEZONE)
    await interaction.response.send_message(
        f"🔁 Tu e {utente.mention} avete fatto **{len(insieme)}** serate insieme"
        + (f", **{positivi}** promosse da entrambi 👍" if positivi else "")
        + f". Ultima: {ultima_txt.strftime('%d/%m alle %H:%M')}.",
        ephemeral=True,
    )


# ------------------------------- /recap (Riot API, solo LoL) -----------------


@bot.tree.command(
    name="recap",
    description="Risultato della tua ultima partita LoL (serve Riot ID salvato)",
)
async def recap(interaction: discord.Interaction):
    if not RIOT_KEY:
        return await interaction.response.send_message(
            "Il recap è disattivato: manca la Riot API key. Un admin può "
            "attivarlo creando `riot_key.txt` sul pannello con dentro la "
            "chiave presa da developer.riotgames.com.",
            ephemeral=True,
        )
    p = profili.get(str(interaction.user.id), {})
    riot = p.get("riot_id")
    if not riot or "#" not in riot:
        return await interaction.response.send_message(
            "Salva prima il tuo Riot ID completo di tag con "
            "`/profilo riot_id: Nome#EUW`.",
            ephemeral=True,
        )

    await interaction.response.defer()
    nome, tag = riot.split("#", 1)
    base = f"https://{RIOT_ROUTING}.api.riotgames.com"
    headers = {"X-Riot-Token": RIOT_KEY}

    try:
        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.get(
                f"{base}/riot/account/v1/accounts/by-riot-id/{nome}/{tag}"
            ) as r:
                if r.status in (401, 403):
                    return await interaction.followup.send(
                        "La Riot API key è scaduta o non valida: va rigenerata "
                        "su developer.riotgames.com."
                    )
                if r.status == 404:
                    return await interaction.followup.send(
                        f"Riot non trova l'account **{riot}**: controlla il "
                        "Riot ID salvato con `/profilo`."
                    )
                r.raise_for_status()
                puuid = (await r.json())["puuid"]

            async with sess.get(
                f"{base}/lol/match/v5/matches/by-puuid/{puuid}/ids?count=1"
            ) as r:
                r.raise_for_status()
                ids = await r.json()
            if not ids:
                return await interaction.followup.send(
                    "Nessuna partita recente trovata per questo account."
                )

            async with sess.get(f"{base}/lol/match/v5/matches/{ids[0]}") as r:
                r.raise_for_status()
                match = await r.json()
    except aiohttp.ClientError:
        return await interaction.followup.send(
            "Riot non risponde al momento, riprova tra poco."
        )

    # mappa dei riot id salvati -> utente discord, per riconoscere i compagni
    salvati = {
        v["riot_id"].lower(): int(uid)
        for uid, v in profili.items()
        if isinstance(v, dict) and v.get("riot_id")
    }

    info = match.get("info", {})
    righe, vittoria = [], None
    for part in info.get("participants", []):
        pid = (f"{part.get('riotIdGameName', '')}"
               f"#{part.get('riotIdTagline', '')}").lower()
        if part.get("puuid") == puuid or pid in salvati:
            k = part.get("kills", 0)
            d = part.get("deaths", 0)
            a = part.get("assists", 0)
            champ = part.get("championName", "?")
            chi = f"<@{salvati[pid]}>" if pid in salvati else riot
            if part.get("puuid") == puuid:
                chi = interaction.user.mention
                vittoria = part.get("win")
            righe.append(f"{chi} — **{champ}** {k}/{d}/{a}")

    durata = info.get("gameDuration", 0)
    e = discord.Embed(
        title=("🏆 Vittoria!" if vittoria else "💀 Sconfitta")
        + f" · {info.get('gameMode', '')}",
        description="\n".join(righe) or "Nessun dato.",
        colour=0x57F287 if vittoria else 0xED4245,
    )
    e.set_footer(text=f"Durata {durata // 60} min")
    await interaction.followup.send(embed=e)


@lol.error
@valorant.error
async def errore(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Aspetta ancora {int(error.retry_after // 60) + 1} minuti.",
            ephemeral=True,
        )
    else:
        raise error


# ----------------------------------------------------------------------------
# Scadenza
# ----------------------------------------------------------------------------


@tasks.loop(minutes=5)
async def pulizia():
    adesso = discord.utils.utcnow()
    for k, dati in list(attive.items()):
        if datetime.datetime.fromisoformat(dati["scade"]) > adesso:
            continue
        canale_id, messaggio_id = map(int, k.split(":"))
        canale = bot.get_channel(canale_id)
        if canale:
            try:
                msg = await canale.fetch_message(messaggio_id)
                await msg.edit(
                    embed=crea_card(canale.guild, dati, "scaduta"), view=None
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        attive.pop(k, None)
    scrivi(ATTIVE_FILE, attive)

    # disponibilita' /stasera: via quelle passate da piu' di 2 ore
    limite = datetime.datetime.now(TIMEZONE) - datetime.timedelta(hours=2)
    prima_n = len(disponibilita)
    disponibilita[:] = [
        d for d in disponibilita
        if datetime.datetime.fromisoformat(d["quando"]) > limite
    ]
    if len(disponibilita) != prima_n:
        scrivi(DISPONIBILITA_FILE, disponibilita)


@pulizia.before_loop
async def prima():
    await bot.wait_until_ready()


bot.run(TOKEN)
