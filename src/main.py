import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

# 서브 모듈 import
from nickname_commands import setup_nickname_commands
from attendance_check import setup_attendance_command

# 로딩 및 로깅
logging.basicConfig(level=logging.INFO)
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable not set")

# 인텐트
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

# 봇 초기화
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")
    await bot.tree.sync()

# 서브 모듈 초기화
setup_nickname_commands(bot)
setup_attendance_command(bot)

# 실행
bot.run(TOKEN)