import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

# 서브 모듈 import
from nickname_commands import setup_nickname_commands
from attendance_check import setup_attendance_command
from status_panel import setup_status_panel
from draw_commands import setup_draw_commands

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
    # print 는 stdout 이라 systemd 아래에서 블록 버퍼링된다. logging 은 stderr 로 바로 나간다.
    logging.info("✅ Bot connected as %s", bot.user)
    await bot.tree.sync()

# 다른 봇도 '!' 접두어를 쓰기 때문에 이 봇에 없는 명령이 계속 들어온다.
# 기본 핸들러는 그때마다 ERROR 를 남기므로 조용히 무시한다.
# @bot.event 가 아니라 @bot.listen 이므로 on_message 처럼 전역 슬롯을 덮어쓰지 않는다.
@bot.listen("on_command_error")
async def ignore_unknown_commands(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    # 각 명령의 @명령.error 가 이미 화면에 안내한 것은 다시 보고하지 않는다
    if ctx.command is not None and ctx.command.has_error_handler():
        return

    # 리스너가 하나라도 있으면 discord.py 의 기본 핸들러가 조기 반환하므로
    # (ext/commands/bot.py 의 on_command_error) 나머지 오류는 직접 남겨야 한다.
    logging.error("명령 처리 실패: %s", ctx.message.content, exc_info=error)

# 서브 모듈 초기화
setup_nickname_commands(bot)
setup_attendance_command(bot)
setup_status_panel(bot)
setup_draw_commands(bot)

# 실행
# log_handler=None: bot.run 이 discord 전용 핸들러를 또 붙이는 것을 막는다.
# 그대로 두면 basicConfig 의 root 핸들러와 양쪽에 찍혀 모든 로그가 두 줄씩 나온다.
bot.run(TOKEN, log_handler=None)