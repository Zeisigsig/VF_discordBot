import discord
from discord.ext import commands
from discord.ext.commands import has_permissions

import logging
import re

VOICE_CHANNEL_NAME = "🔔：내전 대기실"

# 디스코드 메시지 1건의 최대 길이
MESSAGE_LIMIT = 2000

# 관전_/대기_ + DD + 닉네임
NAME_PATTERN = re.compile(r"^(관전_|대기_)?(\d{2})\s(.+)$")

def normalize(name: str) -> str:
    name = re.sub(r"\s*\(.*?\)$", "", name)
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

def chunk_lines(lines, limit: int = MESSAGE_LIMIT):
    """줄 단위로 묶어 limit를 넘지 않는 메시지 조각들로 나눈다."""
    chunks, buf, size = [], [], 0
    for line in lines:
        if buf and size + len(line) + 1 > limit:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks

def setup_attendance_command(bot: commands.Bot):
    @bot.command(name="내전")
    @has_permissions(administrator=True)
    async def check_attendance(ctx, *, user_list: str):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        # 진행 상황 표시 - 완료되면 이 메시지를 결과로 교체한다
        status = await ctx.send("⏳ 내전 인원을 확인하고 있습니다...")
        ctx.vf_status = status      # 오류 시 에러 핸들러가 회수해서 재사용
        await ctx.channel.typing()

        # 참여 대상 (XXX 기준)
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
            await status.edit(content="❌ 음성 채널을 찾을 수 없습니다.")
            return

        present_requested = set()
        removed_tags = []
        added_observer_tags = []

        # 음성 채널 유저 순회
        for member in voice_channel.members:
            tag, code, nickname = parse_display_name(member.display_name)
            norm_nick = normalize(nickname)

            # 참여 대상 유저
            if norm_nick in requested_names:
                present_requested.add(norm_nick)

                # 관전_/대기_ 태그가 붙어 있으면 제거
                if tag is not None and code:
                    new_nick = f"{code} {nickname}"
                    try:
                        await member.edit(nick=new_nick)
                        removed_tags.append(member.display_name)
                    except discord.Forbidden:
                        removed_tags.append(f"(권한 부족) {member.display_name}")

            # 참여 대상이 아닌 유저 → 관전 태그 부여
            else:
                if tag is None and code:
                    new_nick = f"관전_{code} {nickname}"
                    try:
                        await member.edit(nick=new_nick)
                        added_observer_tags.append(new_nick)
                    except discord.Forbidden:
                        added_observer_tags.append(f"(권한 부족) {member.display_name}")

        # 접속하지 않은 유저
        missing_names = requested_names - present_requested
        missing_users = []

        if missing_names:
            # 서버 전체를 한 번만 순회해 인덱스 구성
            # 동명이인은 먼저 발견된 유저를 유지
            name_index = {}
            for member in ctx.guild.members:
                key = normalize(parse_display_name(member.display_name)[2])
                name_index.setdefault(key, member.display_name)

            missing_users = [name_index.get(name, name) for name in missing_names]

        # 결과 출력
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


        chunks = chunk_lines(result)
        await status.edit(content=chunks[0])
        for extra in chunks[1:]:
            await ctx.send(extra)

    @check_attendance.error
    async def check_attendance_error(ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            msg = "⚠️ 명단이 비어 있습니다.\n사용법: `!내전 홍길동, 김철수, 김영희`"
        elif isinstance(error, commands.MissingPermissions):
            msg = "⚠️ `!내전`은 관리자만 사용할 수 있습니다."
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            logging.error("!내전 처리 실패", exc_info=original)
            msg = (
                f"❌ 처리 중 오류가 발생했습니다: `{type(original).__name__}`\n"
                "일부 유저만 반영되었을 수 있습니다. 다시 실행해도 안전합니다."
            )
        else:
            raise error

        try:
            status = getattr(ctx, "vf_status", None)
            if status is not None:
                await status.edit(content=msg)
            else:
                await ctx.send(msg, delete_after=20)
        except discord.HTTPException:
            logging.warning("!내전 오류 안내 메시지를 전송하지 못했습니다.")
