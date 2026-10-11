import asyncio
import logging
import math
import random
import re

import discord
from discord.ext import commands
from discord.ext.commands import has_permissions

from attendance_check import VOICE_CHANNEL_NAME
from nickname_commands import PREFIX_OBSERVER, PREFIX_WAITING

# 발로란트 5대5
TEAM_SIZE = 5
MATCH_SIZE = TEAM_SIZE * 2

# 경기 이름. 음성 채널 정원이 99명이라 경기는 최대 10개이므로 이만큼이면 충분하다.
MATCH_LABELS = "ABCDEFGHIJ"

# 관전/대기는 추첨에서 뺀다.
# parse_display_name 의 tag 가 아니라 접두어 문자열로 판정하는 이유:
# NAME_PATTERN 은 'DD ' 를 요구하므로 '관전_대기_00 홍길동' 처럼
# 접두어가 겹친 닉네임에서는 tag 를 잡지 못해 관전자가 팀에 섞인다.
EXCLUDED_PREFIXES = (PREFIX_OBSERVER, PREFIX_WAITING)

# 행운의 숫자. 결과 머리줄이 길어지는 것만 막는 용도의 자릿수 제한.
LUCKY_PATTERN = re.compile(r"\d{1,9}")

# 다시 뽑기 버튼 유효 시간(초)
REDRAW_TIMEOUT = 300

DRAW_COLOR = 0x5865F2
SPIN_COLOR = 0x9B59B6

# --- 추첨 연출 ---
# 메시지 편집은 채널당 레이트 리밋이 있어, 간격을 더 줄이면 discord.py 가 429 대기를 하며
# 프레임이 불규칙하게 끊긴다. 총 편집 횟수도 MAX_REVEAL_STEPS 로 묶는다.
SPIN_FRAMES = ("◐", "◓", "◑", "◒")
SPIN_STEPS = 3
SPIN_INTERVAL = 1.0
REVEAL_INTERVAL = 0.8

# 경기를 하나씩 공개하면 10경기(99명)에서 편집이 10번이라 연출이 10초를 넘는다.
# 경기가 많으면 여러 개를 묶어 공개해 이 횟수 안에서 끝낸다.
MAX_REVEAL_STEPS = 4

NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")

# 추첨은 모듈 전역 random 의 시드와 무관해야 한다 (같은 숫자로도 결과가 달라야 함).
# SystemRandom 은 OS 엔트로피를 쓰므로 시드 지정 자체가 불가능하다.
_rng = random.SystemRandom()

def number_mark(index: int) -> str:
    """0-based 순번을 표시용 번호로. 9개를 넘으면 이모지가 없어 숫자로 적는다."""
    if index < len(NUMBER_EMOJI):
        return NUMBER_EMOJI[index]
    return f"{index + 1}."

def collect_participants(voice_channel):
    """추첨 대상 이름 목록. 음성 채널에 보이는 이름을 그대로 쓴다.

    - 봇 제외 (음악봇 등이 대기실에 들어와도 뽑히지 않게)
    - 관전_/대기_ 제외
    - 연도가 없는 닉네임도 포함한다. 서버장은 봇이 닉네임을 바꿀 수 없어
      '[연도] [닉네임]' 룰을 적용할 수 없으므로 형식으로 거르면 매번 빠진다.
      (포인트 적립의 참가자 판정은 'DD 닉네임' 형태만 — 기준이 다르다)
    """
    return [
        member.display_name
        for member in voice_channel.members
        if not member.bot and not member.display_name.startswith(EXCLUDED_PREFIXES)
    ]

def draw_matches(names):
    """참가자 이름 목록을 경기별 (1팀, 2팀) 로 나눈다. names 는 1명 이상이어야 한다.

    앞 경기부터 5:5 로 꽉 채우고, 남는 인원은 마지막 경기 두 팀에 번갈아 넣는다.
    순서대로 채우면 한쪽 팀이 전원 빈자리가 되어 몇 명 남았는지가 안 보인다.
    빈자리 번호는 경기 구분 없이 1부터 이어 붙인다.
    """
    pool = list(names)
    _rng.shuffle(pool)

    match_count = math.ceil(len(pool) / MATCH_SIZE)
    matches = []

    for i in range(match_count - 1):
        block = pool[i * MATCH_SIZE:(i + 1) * MATCH_SIZE]
        matches.append((block[:TEAM_SIZE], block[TEAM_SIZE:]))

    last = ([], [])
    for i, name in enumerate(pool[(match_count - 1) * MATCH_SIZE:]):
        last[i % 2].append(name)

    filler = 1
    for team in last:
        while len(team) < TEAM_SIZE:
            team.append(f"빈자리_{filler}")
            filler += 1

    matches.append(last)
    return matches

def build_teams_embed(names, matches, lucky, shown=None):
    """추첨 결과 Embed. shown 을 주면 앞쪽 shown 개 경기만 담는다 (순차 공개용).

    경기 수는 처음부터 전부 적는다. 몇 경기가 더 나올지 보이는 편이 기다리기 낫다.
    """
    if shown is None:
        shown = len(matches)
    done = shown >= len(matches)

    summary = f"{len(names)}명 · {len(matches)}경기"
    if lucky is not None:
        summary += f" · 🍀 행운의 숫자 {lucky}"
    lines = [summary]

    # 빈자리는 마지막 경기에만 생기므로 그 경기가 공개될 때 같이 알린다
    remainder = len(names) - (len(matches) - 1) * MATCH_SIZE
    if done and remainder < MATCH_SIZE:
        lines.append(
            f"-# ⚠️ {MATCH_LABELS[len(matches) - 1]} 경기는 실인원 {remainder}명입니다"
            f" (빈자리 {MATCH_SIZE - remainder})"
        )

    embed = discord.Embed(
        title="🎲 내전 팀 추첨",
        description="\n".join(lines),
        color=DRAW_COLOR,
    )
    for label, (team1, team2) in zip(MATCH_LABELS, matches[:shown]):
        embed.add_field(
            name=f"{label} 경기",
            value=f"**1팀** {' · '.join(team1)}\n**2팀** {' · '.join(team2)}",
            inline=False,
        )
    if done:
        embed.set_footer(text=f"다시 뽑기는 {REDRAW_TIMEOUT // 60}분 안에 누를 수 있습니다")
    return embed

def spin_embed(frame: int, count: int):
    """'추첨 중' 프레임. 결과는 이미 확정돼 있고 이건 연출일 뿐이다."""
    return discord.Embed(
        title=f"{SPIN_FRAMES[frame % len(SPIN_FRAMES)]} 추첨 중...",
        description=f"{count}명",
        color=SPIN_COLOR,
    )

def reveal_steps(total: int):
    """경기를 몇 개까지 공개한 프레임을 만들지의 목록. 편집 횟수를 MAX_REVEAL_STEPS 로 묶는다.

    3경기 -> [1, 2, 3]  (한 경기씩)
    10경기 -> [3, 6, 9, 10]  (세 경기씩 묶어 4번에)
    """
    size = math.ceil(total / min(total, MAX_REVEAL_STEPS))
    return [min(i + size, total) for i in range(0, total, size)]

def draw_frames(names, matches, lucky):
    """(대기 시간, Embed) 프레임 목록. 첫 프레임은 대기 없이 바로 보여준다."""
    frames = [(0.0, spin_embed(0, len(names)))]
    for i in range(1, SPIN_STEPS):
        frames.append((SPIN_INTERVAL, spin_embed(i, len(names))))
    for shown in reveal_steps(len(matches)):
        frames.append((REVEAL_INTERVAL, build_teams_embed(names, matches, lucky, shown)))
    return frames

def prepare_draw(guild):
    """(참가자 목록, 경기 목록, 오류문구) 를 돌려준다. 명령과 '다시 뽑기' 가 함께 쓴다.

    연출을 시작하기 전에 결과를 확정한다. 프레임마다 다시 뽑으면
    중간에 스쳐 지나간 팀이 최종 결과와 달라져 보는 사람이 혼란스럽다.
    """
    channel = discord.utils.get(guild.voice_channels, name=VOICE_CHANNEL_NAME)
    if channel is None:
        return None, None, "❌ 음성 채널을 찾을 수 없습니다."

    names = collect_participants(channel)
    if not names:
        return None, None, (
            f"❌ {channel.mention} 에 추첨할 인원이 없습니다.\n"
            "`관전_`·`대기_` 가 아닌 참가자가 있어야 합니다."
        )

    return names, draw_matches(names), None

async def play_frames(frames, view, edit):
    """첫 프레임 이후를 순서대로 갱신한다. 마지막 프레임에서 버튼 잠금을 푼다.

    edit(embed, view) 는 명령(메시지 편집)과 버튼(인터랙션 응답)에서 경로가 달라 콜백으로 받는다.
    """
    last = len(frames) - 1
    for index in range(1, len(frames)):
        delay, embed = frames[index]
        await asyncio.sleep(delay)
        if index == last:
            view.set_locked(False)
        try:
            await edit(embed, view)
        except discord.HTTPException as e:
            # 연출 도중 결과 메시지가 지워진 경우. 남은 프레임은 보여줄 곳이 없다.
            logging.info("추첨 연출 중단: %s", e)
            view.set_locked(False)
            return

class RedrawView(discord.ui.View):
    """결과 메시지에 붙는 '다시 뽑기' 버튼.

    패널과 달리 영구 View 가 아니다 (custom_id 없음 + timeout 있음).
    팀뽑기는 닉네임을 읽기만 해서 다시 돌려도 안전하므로 재설치 확인 같은 장치가 필요 없다.
    봇을 재시작하면 버튼이 죽는데, 그때는 명령을 다시 입력하면 된다.
    """

    def __init__(self, author_id: int, lucky):
        super().__init__(timeout=REDRAW_TIMEOUT)
        self.author_id = author_id
        self.lucky = lucky
        # discord.py 2.6 의 View 는 메시지 참조를 들고 있지 않아 직접 보관한다
        # (on_timeout 에서 버튼을 비활성화하려면 필요).
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "⚠️ 명령을 실행한 관리자만 다시 뽑을 수 있습니다.", ephemeral=True
            )
            return False
        return True

    def set_locked(self, locked: bool):
        for child in self.children:
            child.disabled = locked

    async def on_timeout(self):
        self.set_locked(True)
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            # 결과 메시지가 이미 지워진 경우
            pass

    @discord.ui.button(label="🔄 다시 뽑기", style=discord.ButtonStyle.primary)
    async def redraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 누를 때마다 음성 채널을 다시 읽는다. 그 사이 들어오거나 나간 사람이 반영된다.
        names, matches, error = prepare_draw(interaction.guild)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        # 연출 중에는 버튼을 잠근다. 두 번 누르면 두 연출이 같은 메시지를 번갈아 덮어쓴다.
        frames = draw_frames(names, matches, self.lucky)
        self.set_locked(True)
        await interaction.response.edit_message(embed=frames[0][1], view=self)

        async def edit(embed, view):
            await interaction.edit_original_response(embed=embed, view=view)

        await play_frames(frames, self, edit)

def parse_map_args(raw: str):
    """'2 코로드 브리즈 어센트 선셋' -> (뽑을 개수, 맵 목록, 오류문구)

    첫 토큰이 숫자면 뽑을 개수로 본다. 맵 이름은 숫자가 아니라 충돌하지 않는다.
    숫자가 없으면 1개를 뽑는다. 공백과 쉼표를 모두 구분자로 받는다.
    """
    tokens = [t for t in re.split(r"[,\s]+", raw.strip()) if t]

    count = 1
    if tokens and tokens[0].isdigit():
        count = int(tokens[0])
        tokens = tokens[1:]

    # 같은 맵을 두 번 적었을 때 한 맵이 두 번 뽑히지 않게, 입력 순서를 지켜 중복 제거
    maps = list(dict.fromkeys(tokens))

    if not maps:
        return 0, [], (
            "⚠️ 맵을 입력해주세요.\n"
            "사용법: `!내전맵뽑 2 코로드 브리즈 어센트 선셋`"
        )
    if count < 1:
        return 0, [], "⚠️ 뽑을 개수는 1 이상이어야 합니다."
    if count > len(maps):
        return 0, [], f"⚠️ 맵 {len(maps)}개 중 {count}개는 뽑을 수 없습니다."

    return count, maps, None

async def report_error(ctx, error, command_name: str, usage: str = None):
    """!내전 의 에러 핸들러와 같은 방식으로, 실패를 콘솔에만 남기지 않고 화면에 안내한다."""
    if isinstance(error, commands.MissingPermissions):
        msg = f"⚠️ `{command_name}`은 관리자만 사용할 수 있습니다."
    elif isinstance(error, commands.MissingRequiredArgument) and usage:
        msg = usage
    elif isinstance(error, commands.CommandInvokeError):
        logging.error("%s 처리 실패", command_name, exc_info=error.original)
        msg = (
            f"❌ 처리 중 오류가 발생했습니다: `{type(error.original).__name__}`\n"
            "다시 실행해도 안전합니다."
        )
    else:
        raise error

    try:
        await ctx.send(msg, delete_after=20)
    except discord.HTTPException:
        logging.warning("%s 오류 안내 메시지를 전송하지 못했습니다.", command_name)

def setup_draw_commands(bot: commands.Bot):
    @bot.command(name="내전팀뽑")
    @has_permissions(administrator=True)
    async def draw_teams(ctx, lucky: str = None):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if lucky is not None and not LUCKY_PATTERN.fullmatch(lucky):
            await ctx.send(
                "⚠️ 행운의 숫자는 9자리 이하의 숫자만 됩니다.\n"
                "사용법: `!내전팀뽑` 또는 `!내전팀뽑 13`",
                delete_after=20,
            )
            return

        names, matches, error = prepare_draw(ctx.guild)
        if error is not None:
            await ctx.send(error, delete_after=20)
            return

        frames = draw_frames(names, matches, lucky)
        view = RedrawView(ctx.author.id, lucky)
        view.set_locked(True)        # 연출이 끝나면 play_frames 가 풀어준다
        view.message = await ctx.send(embed=frames[0][1], view=view)

        async def edit(embed, view_):
            await view.message.edit(embed=embed, view=view_)

        await play_frames(frames, view, edit)

    @draw_teams.error
    async def draw_teams_error(ctx, error):
        await report_error(ctx, error, "!내전팀뽑")

    @bot.command(name="내전맵뽑")
    @has_permissions(administrator=True)
    async def draw_maps(ctx, *, raw: str):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        count, maps, error = parse_map_args(raw)
        if error is not None:
            await ctx.send(error, delete_after=20)
            return

        picked = _rng.sample(maps, count)
        remaining = [m for m in maps if m not in picked]

        embed = discord.Embed(
            title="🗺️ 맵 추첨",
            description=f"{len(maps)}개 중 {count}개",
            color=DRAW_COLOR,
        )
        embed.add_field(
            name="뽑힌 맵",
            value="\n".join(f"{number_mark(i)} {m}" for i, m in enumerate(picked)),
            inline=False,
        )
        if remaining:
            embed.add_field(name="제외", value=" · ".join(remaining), inline=False)

        await ctx.send(embed=embed)

    @draw_maps.error
    async def draw_maps_error(ctx, error):
        await report_error(
            ctx, error, "!내전맵뽑",
            usage=(
                "⚠️ 맵을 입력해주세요.\n"
                "사용법: `!내전맵뽑 2 코로드 브리즈 어센트 선셋`"
            ),
        )
