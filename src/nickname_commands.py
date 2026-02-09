import discord
from discord.ext import commands

# 접두어
PREFIX_OBSERVER = "관전_"
PREFIX_WAITING = "대기_"

WATCH_COMMANDS = ["!ㄱㅈ", "!rw", "!관전", "!rhkswjs", "!RW", "!ㄲㅉ", "!RHKSWJS"]
WAIT_COMMANDS  = ["!ㄷㄱ", "!er", "!대기", "!eorl" ,"!ER", "!ㄸㄲ", "!EORL"]
RESET_COMMANDS = ["!ㄱㄱ", "!rr", "!RR", "!ㄲㄲ"]

def generate_new_nickname(current: str, add: str, remove: str) -> str:
    return add + current[len(remove):] if current.startswith(remove) else add + current

async def change_status(ctx, member: discord.Member, mode: str):
    current_nick = member.nick or member.name

    if mode == "관전":
        if current_nick.startswith(PREFIX_OBSERVER):
            return "이미 관전 모드입니다."
        new_nick = generate_new_nickname(current_nick, PREFIX_OBSERVER, PREFIX_WAITING)

    elif mode == "대기":
        if current_nick.startswith(PREFIX_WAITING):
            return "이미 대기 모드입니다."
        new_nick = generate_new_nickname(current_nick, PREFIX_WAITING, PREFIX_OBSERVER)

    elif mode == "초기화":
        if current_nick.startswith(PREFIX_OBSERVER):
            new_nick = current_nick[len(PREFIX_OBSERVER):]
        elif current_nick.startswith(PREFIX_WAITING):
            new_nick = current_nick[len(PREFIX_WAITING):]
        else:
            return "초기화할 접두어가 없습니다."
    else:
        return "알 수 없는 모드입니다."

    if len(new_nick) > 32:
        return f"닉네임이 너무 깁니다 ({len(new_nick)}자)."

    try:
        await member.edit(nick=new_nick)
        return f"{mode} 모드로 전환되었습니다: {new_nick}"
    except discord.Forbidden:
        return "❌ 권한 부족으로 닉네임을 바꿀 수 없습니다."
    except discord.HTTPException as e:
        return f"❌ 오류: {e}"

async def safe_delete(message: discord.Message):
    try:
        await message.delete()
    except discord.Forbidden:
        pass

def setup_nickname_commands(bot: commands.Bot):
    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        content = message.content.strip()

        if content in WATCH_COMMANDS:
            result = await change_status(message, message.author, "관전")
            await message.channel.send(f"{message.author.mention} {result}", delete_after=5)
            await safe_delete(message)
            return

        if content in WAIT_COMMANDS:
            result = await change_status(message, message.author, "대기")
            await message.channel.send(f"{message.author.mention} {result}", delete_after=5)
            await safe_delete(message)
            return

        if content in RESET_COMMANDS:
            result = await change_status(message, message.author, "초기화")
            await message.channel.send(f"{message.author.mention} {result}", delete_after=5)
            await safe_delete(message)
            return

        await bot.process_commands(message)

    @bot.command(name="rw")
    async def rw(ctx):
        result = await change_status(ctx, ctx.author, "관전")
        await ctx.send(f"{ctx.author.mention} {result}", delete_after=5)

    @bot.command(name="er")
    async def er(ctx):
        result = await change_status(ctx, ctx.author, "대기")
        await ctx.send(f"{ctx.author.mention} {result}", delete_after=5)

    @bot.command(name="rr")
    async def rr(ctx):
        result = await change_status(ctx, ctx.author, "초기화")
        await ctx.send(f"{ctx.author.mention} {result}", delete_after=5)