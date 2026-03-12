import discord
from discord import app_commands
import aiohttp
import asyncio
import json
import io
from datetime import datetime, timedelta
import os

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

# OsintCat
OSINTCAT_BASE = "https://api.osintcat.com"
OSINTCAT_KEY = ""

# Snusbase (using Auth header per docs)
SNUSBASE_BASE = "https://api.snusbase.com"
SNUSBASE_KEY = ""  # Your key

BOT_TOKEN = ""
OWNER_ID = 1420365808965648415

WHITELIST_FILE = "whitelist.json"
BLACKLIST_FILE = "blacklist.json"
LICENSES_FILE = "licenses.json"

# Load data helpers
def load_data(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Invalid JSON in {file}")
    return default

whitelist = load_data(WHITELIST_FILE, [])
blacklist = load_data(BLACKLIST_FILE, [])
licenses = load_data(LICENSES_FILE, {})

def save_data():
    with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump(whitelist, f, indent=2)
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(blacklist, f, indent=2)
    with open(LICENSES_FILE, "w", encoding="utf-8") as f:
        json.dump(licenses, f, indent=2)

# ────────────────────────────────────────────────
# BOT SETUP
# ────────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user} | Ready at {datetime.utcnow().isoformat()}")

def has_access(uid: int) -> bool:
    return uid not in blacklist and uid in whitelist

# ────────────────────────────────────────────────
# OWNER COMMANDS (whitelist/blacklist) – unchanged
# ────────────────────────────────────────────────
def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)

@tree.command(name="whitelist_add", description="Add user to whitelist (owner only)")
@is_owner()
@app_commands.describe(user="User")
async def whitelist_add(interaction: discord.Interaction, user: discord.Member):
    uid = user.id
    if uid in blacklist:
        await interaction.response.send_message(f"{user.mention} is blacklisted.", ephemeral=True)
        return
    if uid not in whitelist:
        whitelist.append(uid)
        save_data()
    await interaction.response.send_message(f"{user.mention} whitelisted.", ephemeral=True)

@tree.command(name="whitelist_remove", description="Remove from whitelist (owner only)")
@is_owner()
@app_commands.describe(user="User")
async def whitelist_remove(interaction: discord.Interaction, user: discord.Member):
    uid = user.id
    if uid in whitelist:
        whitelist.remove(uid)
        save_data()
    await interaction.response.send_message(f"{user.mention} removed from whitelist.", ephemeral=True)

@tree.command(name="blacklist_add", description="Add to blacklist (owner only)")
@is_owner()
@app_commands.describe(user="User")
async def blacklist_add(interaction: discord.Interaction, user: discord.Member):
    uid = user.id
    if uid not in blacklist:
        blacklist.append(uid)
        if uid in whitelist:
            whitelist.remove(uid)
        save_data()
    await interaction.response.send_message(f"{user.mention} blacklisted.", ephemeral=True)

@tree.command(name="blacklist_remove", description="Remove from blacklist (owner only)")
@is_owner()
@app_commands.describe(user="User")
async def blacklist_remove(interaction: discord.Interaction, user: discord.Member):
    uid = user.id
    if uid in blacklist:
        blacklist.remove(uid)
        save_data()
    await interaction.response.send_message(f"{user.mention} removed from blacklist.", ephemeral=True)

# ────────────────────────────────────────────────
# REDEEM COMMAND
# ────────────────────────────────────────────────
@tree.command(name="redeem", description="Redeem a lifetime key")
@app_commands.describe(key="Your key (BS-XXXX-XXXX-XXXX)")
async def cmd_redeem(interaction: discord.Interaction, key: str):
    uid = interaction.user.id
    if uid in blacklist:
        await interaction.response.send_message("Blacklisted.", ephemeral=True)
        return

    key = key.strip().upper()
    if key not in licenses:
        await interaction.response.send_message("Invalid key.", ephemeral=True)
        return

    lic = licenses[key]
    if lic.get("user") and lic["user"] != uid:
        await interaction.response.send_message("Key already used by someone else.", ephemeral=True)
        return

    if uid not in whitelist:
        whitelist.append(uid)
    lic["user"] = uid
    lic["redeemed_at"] = datetime.utcnow().isoformat()
    save_data()

    await interaction.response.send_message(
        "**Success!** Lifetime access granted.",
        ephemeral=True
    )

# ────────────────────────────────────────────────
# HELPER: Send formatted JSON file
# ────────────────────────────────────────────────
async def send_formatted_json(interaction, data, filename_prefix, query, search_type):
    # Extract hits count safely (works for both OsintCat and Snusbase)
    hits = 0
    if isinstance(data, dict):
        # Snusbase style
        if "size" in data:
            hits = data["size"]
        # OsintCat style
        elif "total_hits" in data:
            hits = data["total_hits"]
        elif "results" in data:
            # Count entries across all tables/groups
            results = data["results"]
            if isinstance(results, dict):
                for table_entries in results.values():
                    if isinstance(table_entries, list):
                        hits += len(table_entries)

    nice = {
        "summary": {
            "queried_by": str(interaction.user),
            "query": query,
            "type": search_type,
            "time": datetime.utcnow().isoformat() + "Z",
            "source": "Snusbase" if "snus" in filename_prefix.lower() else "OsintCat",
            "hits": hits,
            "took_ms": data.get("took", "N/A") if isinstance(data, dict) else "N/A"
        },
        "results": [],
        "raw": data
    }

    # Flatten results for nicer view (optional - you can remove if you prefer raw)
    if isinstance(data, dict) and "results" in data:
        results_flat = []
        results_data = data["results"]
        if isinstance(results_data, dict):
            for table_name, entries in results_data.items():
                for entry in entries:
                    nice_entry = {"table": table_name, **entry}
                    results_flat.append(nice_entry)
        nice["results"] = results_flat

    json_str = json.dumps(nice, indent=4, ensure_ascii=False)
    safe_q = "".join(c for c in query if c.isalnum() or c in "-_@")[:40].replace("@", "_at_")
    filename = f"{filename_prefix}_{search_type}_{safe_q}.json"
    file = discord.File(io.StringIO(json_str), filename=filename)

    await interaction.followup.send(
        content=f"**{interaction.user.mention}** → {search_type.upper()} search for **{query}** • **Hits:** {hits}",
        file=file
    )

# ────────────────────────────────────────────────
# OSINTCAT SEARCH (original)
# ────────────────────────────────────────────────
@tree.command(name="search", description="Search via OsintCat API (requires access)")
@app_commands.describe(query="Search term", search_type="Type")
@app_commands.choices(search_type=[
    app_commands.Choice(name="Email", value="email"),
    app_commands.Choice(name="Username", value="username"),
    app_commands.Choice(name="IP", value="ip"),
    app_commands.Choice(name="Password", value="password"),
    app_commands.Choice(name="Phone", value="phone"),
    app_commands.Choice(name="Domain", value="domain"),
])
async def osintcat_search(interaction: discord.Interaction, query: str, search_type: str = "email"):
    uid = interaction.user.id
    if not has_access(uid):
        await interaction.response.send_message("No access. Use /redeem.", ephemeral=True)
        return

    await interaction.response.defer()

    url = f"{OSINTCAT_BASE}/api/search/{search_type}"
    params = {search_type: query.strip()}
    headers = {"Authorization": f"Bearer {OSINTCAT_KEY}", "Accept": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    data = {"error": f"HTTP {resp.status}: {await resp.text()[:400]}"}
        except Exception as e:
            data = {"error": str(e)}

    await send_formatted_json(interaction, data, "osintcat", query, search_type)

# ────────────────────────────────────────────────
# SNUSBASE GENERAL SEARCH (/data/search)
# ────────────────────────────────────────────────
@tree.command(name="snus", description="Search via Snusbase API (requires access)")
@app_commands.describe(
    query="Search term (email/username/password/hash/ip/etc)",
    search_type="Type (email, username, password, hash, lastip, name, _domain)"
)
async def snus_search(interaction: discord.Interaction, query: str, search_type: str):
    uid = interaction.user.id
    if not has_access(uid):
        await interaction.response.send_message("No access. Use /redeem.", ephemeral=True)
        return

    await interaction.response.defer()

    url = f"{SNUSBASE_BASE}/data/search"
    payload = {
        "terms": [query.strip()],
        "types": [search_type.lower()],
        "wildcard": False
    }
    headers = {
        "Auth": SNUSBASE_KEY,  # Per docs: Auth header, not Authorization
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    data = {"error": f"HTTP {resp.status}: {await resp.text()[:400]}"}
        except Exception as e:
            data = {"error": str(e)}

    await send_formatted_json(interaction, data, "snusbase", query, search_type)

# ────────────────────────────────────────────────
# SNUSBASE HASH LOOKUP (/tools/hash-lookup)
# ────────────────────────────────────────────────
@tree.command(name="crackhash", description="Crack/lookup hash via Snusbase")
@app_commands.describe(hash_value="The hash to lookup (MD5/SHA-1/SHA-256/etc)")
async def crack_hash(interaction: discord.Interaction, hash_value: str):
    uid = interaction.user.id
    if not has_access(uid):
        await interaction.response.send_message("No access. Use /redeem.", ephemeral=True)
        return

    await interaction.response.defer()

    url = f"{SNUSBASE_BASE}/tools/hash-lookup"
    payload = {
        "terms": [hash_value.strip()],
        "types": ["hash"]
    }
    headers = {
        "Auth": SNUSBASE_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    data = {"error": f"HTTP {resp.status}: {await resp.text()[:400]}"}
        except Exception as e:
            data = {"error": str(e)}

    # Nice summary for Discord
    if isinstance(data, dict) and "results" in data and data["results"]:
        result_msg = f"**Found!** {len(data['results'])} matches in database(s). Check attached JSON."
    else:
        result_msg = "No match found or error during lookup."

    safe_hash = hash_value[:16] + "..." if len(hash_value) > 16 else hash_value
    await interaction.followup.send(
        content=f"{interaction.user.mention} • Hash lookup: `{safe_hash}`\n{result_msg}",
        file=discord.File(io.StringIO(json.dumps(data, indent=2)), filename=f"snus_hash_{safe_hash}.json")
    )

# ────────────────────────────────────────────────
# SNUSBASE DATABASE STATS (/data/stats)
# ────────────────────────────────────────────────
@tree.command(name="snusstats", description="Get Snusbase database stats")
async def snus_stats(interaction: discord.Interaction):
    uid = interaction.user.id
    if not has_access(uid):
        await interaction.response.send_message("No access. Use /redeem.", ephemeral=True)
        return

    await interaction.response.defer()

    url = f"{SNUSBASE_BASE}/data/stats"
    headers = {"Auth": SNUSBASE_KEY, "Accept": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    data = {"error": f"HTTP {resp.status}: {await resp.text()[:400]}"}
        except Exception as e:
            data = {"error": str(e)}

    json_str = json.dumps(data, indent=2)
    file = discord.File(io.StringIO(json_str), filename="snusbase_stats.json")

    await interaction.followup.send(
        content=f"{interaction.user.mention} • Snusbase database stats",
        file=file
    )

# ────────────────────────────────────────────────
# START BOT
# ────────────────────────────────────────────────
client.run(BOT_TOKEN)