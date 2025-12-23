import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import random
import json
from discord.ui import View, button

# ----------------------------
# Configuration et token
# ----------------------------
load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# IDs des channels et catégories
# ----------------------------
GAME_CHANNELS = [
    1452784979799965986,  # 8s
    1452784786644140144   # 6s
]

CATEGORY_6S = 1452784432330313889
CATEGORY_8S = 1452783820876157094

STAFF_CHANNEL_ID = 1452993054561665206  # <-- ton channel staff

temporary_voice_channels = set()

# ----------------------------
# Gestion ELO et matchs
# ----------------------------
ELO_FILE = "elo.json"
MATCHES_FILE = "matches.json"
MATCH_COUNTER_FILE = "match_counter.json"

def load_elo():
    if not os.path.exists(ELO_FILE):
        return {}
    with open(ELO_FILE, "r") as f:
        return json.load(f)

def save_elo(data):
    with open(ELO_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_elo(user_id):
    elos = load_elo()
    if str(user_id) not in elos:
        elos[str(user_id)] = {"elo": 1000, "matches": 0}
        save_elo(elos)
    return elos[str(user_id)]["elo"]

def set_elo(user_id, value):
    elos = load_elo()
    if str(user_id) not in elos:
        elos[str(user_id)] = {"elo": value, "matches": 0}
    else:
        elos[str(user_id)]["elo"] = value
    save_elo(elos)

def increment_match_count(user_id):
    elos = load_elo()
    if str(user_id) not in elos:
        elos[str(user_id)] = {"elo": 1000, "matches": 0}
    elos[str(user_id)]["matches"] += 1
    save_elo(elos)

def get_match_count(user_id):
    elos = load_elo()
    if str(user_id) in elos:
        return elos[str(user_id)]["matches"]
    return 0

def load_matches():
    if not os.path.exists(MATCHES_FILE):
        return {}
    with open(MATCHES_FILE, "r") as f:
        return json.load(f)

def save_matches(data):
    with open(MATCHES_FILE, "w") as f:
        json.dump(data, f, indent=4)

matches = load_matches()

# ----------------------------
# Compteur de match lisible
# ----------------------------
def load_match_counter():
    if not os.path.exists(MATCH_COUNTER_FILE):
        return {"counter": 0}
    with open(MATCH_COUNTER_FILE, "r") as f:
        return json.load(f)

def save_match_counter(data):
    with open(MATCH_COUNTER_FILE, "w") as f:
        json.dump(data, f, indent=4)

match_counter = load_match_counter()

def get_next_match_number():
    match_counter["counter"] += 1
    save_match_counter(match_counter)
    return match_counter["counter"]

# ----------------------------
# Classe pour les boutons de vote
# ----------------------------
class MatchResultView(View):
    def __init__(self, match_id):
        super().__init__(timeout=None)
        self.match_id = match_id

    @button(label="🏆 J'ai gagné", style=discord.ButtonStyle.success)
    async def win(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.match_id, "win")

    @button(label="❌ J'ai perdu", style=discord.ButtonStyle.danger)
    async def lose(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.match_id, "lose")

    @button(label="🆘 Contact staff", style=discord.ButtonStyle.secondary)
    async def staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        match = matches.get(str(self.match_id))
        if not match:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return

        team1_players = ", ".join([f"<@{m}>" for m in match["team1"]])
        team2_players = ", ".join([f"<@{m}>" for m in match["team2"]])
        match_number = match.get("match_number", self.match_id)

        await interaction.response.send_message("🆘 Staff appelé, match en attente.", ephemeral=True)
        staff_channel = interaction.guild.get_channel(STAFF_CHANNEL_ID)
        if staff_channel:
            await staff_channel.send(
                f"⚠️ **Match #{match_number}** — Assistance demandée par {interaction.user.mention}\n"
                f"**Team 1:** {team1_players}\n"
                f"**Team 2:** {team2_players}"
            )

# ----------------------------
# Fonctions de vote et résultat
# ----------------------------
async def handle_vote(interaction, match_id, vote):
    match = matches.get(str(match_id))
    if not match:
        await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
        return
    if match.get("locked"):
        await interaction.response.send_message("⛔ Match déjà verrouillé.", ephemeral=True)
        return
    user_id = interaction.user.id
    if user_id not in match["team1"] + match["team2"]:
        await interaction.response.send_message("❌ Tu ne fais pas partie de ce match.", ephemeral=True)
        return
    match["votes"][user_id] = vote
    save_matches(matches)
    await interaction.response.send_message("✅ Vote enregistré", ephemeral=True)
    await check_match_result(interaction, match_id)

async def check_match_result(interaction, match_id):
    match = matches.get(str(match_id))
    if not match:
        return
    team1_votes = [match["votes"].get(uid) for uid in match["team1"]]
    team2_votes = [match["votes"].get(uid) for uid in match["team2"]]

    if all(v == "lose" for v in team1_votes if v) and len(team1_votes) == len(match["team1"]):
        await finalize_match(interaction, match_id, winner=2)
    elif all(v == "lose" for v in team2_votes if v) and len(team2_votes) == len(match["team2"]):
        await finalize_match(interaction, match_id, winner=1)
    elif any(v == "win" for v in team1_votes) and any(v == "win" for v in team2_votes):
        match["locked"] = True
        save_matches(matches)
        await interaction.channel.send("⚠️ Conflit détecté — un staff doit intervenir.")

async def finalize_match(interaction, match_id, winner):
    match = matches.get(str(match_id))
    if not match:
        return
    match["locked"] = True
    save_matches(matches)

    winning_team = match["team1"] if winner == 1 else match["team2"]
    losing_team = match["team2"] if winner == 1 else match["team1"]

    avg_elo = sum(get_elo(m) for m in winning_team) / len(winning_team)

    for m in winning_team:
        elo = get_elo(m)
        match_count = get_match_count(m)
        gain = 15 if elo >= avg_elo else 25
        if match_count < 10:
            gain *= 2
        set_elo(m, elo + gain)
        increment_match_count(m)

    for m in losing_team:
        elo = get_elo(m)
        match_count = get_match_count(m)
        loss = 10 if elo >= avg_elo else 20
        if match_count < 10:
            loss *= 2
        set_elo(m, elo - loss)
        increment_match_count(m)

    await interaction.channel.send(f"🏆 **Team {winner} gagne !**\nELO mis à jour.")

# ----------------------------
# Événement bot prêt
# ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}")

# ----------------------------
# Commandes
# ----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong")

@bot.command()
async def elo(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_elo = get_elo(member.id)
    await ctx.send(f"📊 {member.display_name} a {user_elo} d'ELO.")

@bot.command()
async def play(ctx):
    # Vérifie si l'auteur est dans un channel vocal
    if not ctx.author.voice:
        await ctx.send("❌ Tu dois être dans un channel vocal pour lancer un match.")
        return

    channel = ctx.author.voice.channel

    # Vérifie si le channel est dans les channels de jeu autorisés
    if channel.id not in GAME_CHANNELS:
        await ctx.send("❌ Ce channel n'est pas un channel de jeu autorisé.")
        return

    # Récupère uniquement les membres présents dans ce channel
    members = list(channel.members)
    if len(members) < 2:
        await ctx.send("❌ Il faut au moins 2 joueurs pour lancer un match.")
        return

    # Mélange les joueurs et trie par ELO décroissant
    random.shuffle(members)
    members.sort(key=lambda m: get_elo(m.id), reverse=True)

    team1, team2 = [], []
    elo1, elo2 = 0, 0
    for m in members:
        if elo1 <= elo2:
            team1.append(m.id)
            elo1 += get_elo(m.id)
        else:
            team2.append(m.id)
            elo2 += get_elo(m.id)

    teams = [team1, team2]
    overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False)}
    voc_channels = []
    category = ctx.guild.get_channel(CATEGORY_8S if channel.id == 1452784979799965986 else CATEGORY_6S)

    for i, team in enumerate(teams, start=1):
        voc = await ctx.guild.create_voice_channel(
            f"Team {i} - {len(team)}",
            user_limit=len(team),
            overwrites=overwrites,
            category=category
        )
        voc_channels.append(voc)
        temporary_voice_channels.add(voc.id)
        for member_id in team:
            member_obj = ctx.guild.get_member(member_id)
            if member_obj:
                await member_obj.move_to(voc)

    embed = discord.Embed(title="🏆 Équipes créées !", color=discord.Color.blue())
    for i, team in enumerate(teams, start=1):
        mentions = "\n".join([f"- <@{m}>" for m in team])
        embed.add_field(name=f"Team {i}", value=mentions, inline=True)
    embed.set_footer(text=f"Channels voc temporaires créés dans la catégorie {category.name} !")

    match_id = ctx.message.id
    match_number = get_next_match_number()
    matches[str(match_id)] = {
        "team1": team1,
        "team2": team2,
        "votes": {},
        "locked": False,
        "match_number": match_number
    }
    save_matches(matches)

    view = MatchResultView(match_id)
    await ctx.send(embed=embed)
    await ctx.send("📊 Votez votre résultat ci-dessous :", view=view)

# ----------------------------
# Commande admin pour modifier l'ELO et les matchs manuellement
# ----------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setelo(ctx, member: discord.Member, elo_value: int, matches: int = None):
    elos = load_elo()
    if str(member.id) not in elos or not isinstance(elos[str(member.id)], dict):
        elos[str(member.id)] = {"elo": elo_value, "matches": 0}
    else:
        elos[str(member.id)]["elo"] = elo_value
        if matches is not None:
            elos[str(member.id)]["matches"] = matches

    save_elo(elos)
    msg = f"✅ L'ELO de {member.display_name} est maintenant {elo_value}"
    if matches is not None:
        msg += f" et le nombre de matchs est {matches}"
    await ctx.send(msg)

# ----------------------------
# Suppression automatique des vocs temporaires
# ----------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    for channel_id in list(temporary_voice_channels):
        channel = bot.get_channel(channel_id)
        if channel is None:
            temporary_voice_channels.remove(channel_id)
            continue
        if len(channel.members) == 0:
            try:
                await channel.delete()
                temporary_voice_channels.remove(channel_id)
                print(f"✅ Channel temporaire {channel.name} supprimé car vide.")
            except Exception as e:
                print(f"❌ Erreur lors de la suppression du channel {channel.name}: {e}")

# ----------------------------
# Lancer le bot
# ----------------------------
bot.run(TOKEN)
