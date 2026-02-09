import discord
from discord.ext import commands
from discord.ext.commands import has_permissions

import re

VOICE_CHANNEL_NAME = "🔔：내전 대기실"

# 관전_/대기_ + DD + 닉네임
NAME_PATTERN = re.compile(r"^(관전_|대기_)?(\d{2})\s(.+)$")

def normalize(name: str) -> str:
    return name.strip().lower()

def parse_display_name(display_name: str):
    """
    return:
        tag: '관전_' | '대기_' | None
        code: 'DD' | None
        nickname: 'XXX'
    """
    m = NAME_PATTERN.match(display_name)
    if m:
        tag, code, nickname = m.groups()
        return tag, code, nickname.strip()
    return None, None, display_name.strip()

def setup_attendance_command(bot: commands.Bot):
    @bot.command(name="내전")
    @has_permissions(administrator=True)
    async def check_attendance(ctx, *, user_list: str):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        # 1️⃣ 참여 대상 (XXX 기준)
        requested_raw = [x.strip() for x in user_list.split(",") if x.strip()]
        requested_names = {
            # normalize(x.split()[-1]) for x in requested_raw
            normalize(x) for x in requested_raw
        }

        voice_channel = discord.utils.get(
            ctx.guild.voice_channels,
            name=VOICE_CHANNEL_NAME
        )
        if not voice_channel:
            await ctx.send("❌ 음성 채널을 찾을 수 없습니다.")
            return

        present_requested = set()
        removed_tags = []
        added_observer_tags = []

        # 2️⃣ 음성 채널 유저 순회
        for member in voice_channel.members:
            tag, code, nickname = parse_display_name(member.display_name)
            norm_nick = normalize(nickname)

            # 🎯 참여 대상 유저
            if norm_nick in requested_names:
                present_requested.add(norm_nick)

                # ❌ 관전_/대기_ 태그가 붙어 있으면 제거
                if tag is not None and code:
                    new_nick = f"{code} {nickname}"
                    try:
                        await member.edit(nick=new_nick)
                        removed_tags.append(member.display_name)
                    except discord.Forbidden:
                        removed_tags.append(f"(권한 부족) {member.display_name}")

            # 👁 참여 대상이 아닌 유저 → 관전 태그 부여
            else:
                if tag is None and code:
                    new_nick = f"관전_{code} {nickname}"
                    try:
                        await member.edit(nick=new_nick)
                        added_observer_tags.append(new_nick)
                    except discord.Forbidden:
                        added_observer_tags.append(f"(권한 부족) {member.display_name}")

        # 3️⃣ 접속하지 않은 유저
        missing_names = requested_names - present_requested
        missing_users = []

        for name in missing_names:
            found = next(
                (
                    m.display_name
                    for m in ctx.guild.members
                    if normalize(parse_display_name(m.display_name)[2]) == name
                ),
                name
            )
            missing_users.append(found)

        # 4️⃣ 결과 출력
        result = []

        if missing_users:
            result.append("❌ 접속하지 않은 유저:")
            for name in missing_users:
                result.append(f"• {name}")

        if removed_tags:
            result.append("🧹 잘못된 태그를 제거한 유저:")
            for name in removed_tags:
                result.append(f"• {name}")

        if added_observer_tags:
            result.append("👁 관전 태그를 추가한 유저:")
            for name in added_observer_tags:
                result.append(f"• {name}")

        if not result:
            result.append("✅ 모든 참여 유저가 올바르게 접속해 있습니다!")

        await ctx.send("\n".join(result))