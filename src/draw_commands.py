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

# 추첨 연출: "입력 중..." 을 이만큼 띄운 뒤 결과를 한 번에 보낸다.
# 글자 단위 타이핑은 디스코드에서 불가능하다 — 메시지 편집이 채널당 초당 1회 수준으로 제한되므로
# 수백 번의 편집이 필요한 연출은 레이트 리밋에 막힌다. 편집을 아예 쓰지 않는 쪽을 택했다.
TYPING_DELAY = 1.2

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

def format_match(team1, team2, first_team: int):
    """경기 하나를 코드박스로 적는다. 팀 번호는 경기를 넘어 이어진다 (1·2 / 3·4 / 5·6).

    코드박스 안에서는 마크다운이 적용되지 않아 글자를 키울 수 없다.
    이름에 공백이 들어갈 수 있어(`00 도굴꾼 임누리`) 구분자는 공백이 아닌 ` · ` 를 쓴다.
    """
    return (
        "```\n"
        f"{first_team}팀 : {' · '.join(team1)}\n"
        f"{first_team + 1}팀 : {' · '.join(team2)}\n"
        "```"
    )

def build_teams_embed(names, matches, lucky):
    """추첨 결과 Embed."""
    summary = f"{len(names)}명 · {len(matches)}경기"
    if lucky is not None:
        summary += f" · 🍀 행운의 숫자 {lucky}"
    blocks = [f"### {summary}"]

    for i, (team1, team2) in enumerate(matches):
        blocks.append(format_match(team1, team2, i * 2 + 1))

    # 빈자리는 마지막 경기에만 생기므로 그 경기가 공개될 때 같이 알린다.
    # 작은 글씨(-#)로 두면 정작 봐야 할 경고가 가장 안 보인다.
    remainder = len(names) - (len(matches) - 1) * MATCH_SIZE
    if remainder < MATCH_SIZE:
        last = len(matches) * 2
        blocks.append(
            f"**⚠️ {last - 1}팀·{last}팀은 실인원 {remainder}명입니다"
            f" (빈자리 {MATCH_SIZE - remainder})**"
        )

    embed = discord.Embed(
        title="🎲 내전 팀 추첨",
        description="\n".join(blocks),
        color=DRAW_COLOR,
    )
    embed.set_footer(text=f"다시 뽑기는 {REDRAW_TIMEOUT // 60}분 안에 누를 수 있습니다")
    return embed

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
        # View 는 메시지 참조를 들고 있지 않아 직접 보관한다
        # (on_timeout 에서 버튼을 비활성화하려면 필요).
        # 라이브러리가 나중에 같은 이름을 쓰더라도 충돌하지 않게 message 를 피한다.
        self.result_message = None
        # 연출(약 1.2초) 중에 다시 눌리는 것을 막는다. 버튼을 비활성화하려면 메시지 편집이
        # 한 번 더 필요하므로, 편집 없이 플래그로 막는다.
        self.drawing = False

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
        if self.result_message is None:
            return
        try:
            await self.result_message.edit(view=self)
        except discord.HTTPException:
            # 결과 메시지가 이미 지워진 경우
            pass

    @discord.ui.button(label="🔄 다시 뽑기", style=discord.ButtonStyle.primary)
    async def redraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.drawing:
            await interaction.response.send_message("⏳ 추첨 중입니다.", ephemeral=True)
            return

        # 누를 때마다 음성 채널을 다시 읽는다. 그 사이 들어오거나 나간 사람이 반영된다.
        names, matches, error = prepare_draw(interaction.guild)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        self.drawing = True
        try:
            # defer 로 먼저 응답해 3초 제한을 피한다. 화면에는 변화가 없고,
            # 그 동안 '입력 중...' 만 뜬다.
            await interaction.response.defer()
            async with interaction.channel.typing():
                await asyncio.sleep(TYPING_DELAY)
            await interaction.edit_original_response(
                embed=build_teams_embed(names, matches, self.lucky), view=self
            )
        finally:
            self.drawing = False

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

        # 결과를 먼저 확정해두고 '입력 중...' 만 띄운다. 메시지 편집을 쓰지 않으므로
        # 레이트 리밋과 무관하고, 결과는 한 번에 완성된 상태로 올라간다.
        async with ctx.channel.typing():
            await asyncio.sleep(TYPING_DELAY)

        view = RedrawView(ctx.author.id, lucky)
        view.result_message = await ctx.send(
            embed=build_teams_embed(names, matches, lucky), view=view
        )

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

        lines = [f"### {len(maps)}개 중 {count}개"]
        # 뽑힌 맵이 제일 중요한 정보라 가장 크게 적는다
        lines += [f"## {number_mark(i)} {m}" for i, m in enumerate(picked)]
        if remaining:
            lines.append(f"**제외** {' · '.join(remaining)}")

        embed = discord.Embed(
            title="🗺️ 맵 추첨",
            description="\n".join(lines),
            color=DRAW_COLOR,
        )

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
