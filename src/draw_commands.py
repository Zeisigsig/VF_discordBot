import asyncio
import logging
import random
import re

import discord
from discord.ext import commands
from discord.ext.commands import has_permissions

from attendance_check import VOICE_CHANNEL_NAME
from nickname_commands import PREFIX_OBSERVER, PREFIX_WAITING
from status_panel import schedule_dismiss

# 10명을 한 팀으로 묶는다. 5:5 밸런싱은 봇이 하지 않고 그 10명이 모여서 직접 한다.
TEAM_SIZE = 10

# 관전/대기는 추첨에서 뺀다.
# parse_display_name 의 tag 가 아니라 접두어 문자열로 판정하는 이유:
# NAME_PATTERN 은 'DD ' 를 요구하므로 '관전_대기_00 홍길동' 처럼
# 접두어가 겹친 닉네임에서는 tag 를 잡지 못해 관전자가 팀에 섞인다.
EXCLUDED_PREFIXES = (PREFIX_OBSERVER, PREFIX_WAITING)

DRAW_COLOR = 0x5865F2

# 추첨 연출: "입력 중..." 을 이만큼 띄운 뒤 결과를 한 번에 보낸다.
# 글자 단위 타이핑은 디스코드에서 불가능하다 — 메시지 편집이 채널당 초당 1회 수준으로 제한되므로
# 수백 번의 편집이 필요한 연출은 레이트 리밋에 막힌다. 편집을 아예 쓰지 않는 쪽을 택했다.
TYPING_DELAY = 1.2

# '내 팀 확인' 버튼이 살아 있는 시간(초). 만료되면 버튼이 비활성화된다.
# 인터랙션이 있을 때마다 갱신되므로 누르는 사람이 있으면 계속 연장된다.
MY_TEAM_TIMEOUT = 1800

# 본인에게만 보이는 응답을 몇 초 후 자동으로 치울지
DISMISS_SECONDS = 5

NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")

# 추첨은 모듈 전역 random 의 시드와 무관해야 한다 (같은 입력으로도 결과가 달라야 함).
# SystemRandom 은 OS 엔트로피를 쓰므로 시드 지정 자체가 불가능하다.
_rng = random.SystemRandom()

def number_mark(index: int) -> str:
    """0-based 순번을 표시용 번호로. 9개를 넘으면 이모지가 없어 숫자로 적는다."""
    if index < len(NUMBER_EMOJI):
        return NUMBER_EMOJI[index]
    return f"{index + 1}."

def entry_name(entry):
    """팀 구성원을 표시용 이름으로. 빈자리는 Member 가 아니라 문자열이다."""
    return entry if isinstance(entry, str) else entry.display_name

def collect_participants(voice_channel):
    """추첨 대상 Member 목록.

    - 봇 제외 (음악봇 등이 대기실에 들어와도 뽑히지 않게)
    - 관전_/대기_ 제외
    - 연도가 없는 닉네임도 포함한다. 서버장은 봇이 닉네임을 바꿀 수 없어
      '[연도] [닉네임]' 룰을 적용할 수 없으므로 형식으로 거르면 매번 빠진다.
      (포인트 적립의 참가자 판정은 'DD 닉네임' 형태만 — 기준이 다르다)
    """
    return [
        member
        for member in voice_channel.members
        if not member.bot and not member.display_name.startswith(EXCLUDED_PREFIXES)
    ]

def split_teams(participants):
    """참가자를 10명 단위 팀으로 나눈다. participants 는 1명 이상이어야 한다.

    앞 팀부터 10명씩 꽉 채우고 남는 인원은 마지막 팀에 둔다. 인원을 고르게 퍼뜨리지
    않는 이유는 10명이 모여야 한 경기가 서기 때문이다 — 23명을 8/8/7 로 나누면
    세 팀 모두 경기를 열 수 없다.
    모자란 자리는 '대기 - N' 으로 채운다. 빈자리가 몇 개인지가 그 줄 수로 바로 보인다.
    """
    pool = list(participants)
    _rng.shuffle(pool)

    teams = [pool[i:i + TEAM_SIZE] for i in range(0, len(pool), TEAM_SIZE)]

    last = teams[-1]
    for i in range(TEAM_SIZE - len(last)):
        last.append(f"대기 - {i + 1}")

    return teams

def build_team_index(teams):
    """{user_id: 팀 번호} — '내 팀 확인' 버튼이 쓴다."""
    return {
        entry.id: number
        for number, team in enumerate(teams, start=1)
        for entry in team
        if not isinstance(entry, str)
    }

def format_team(team, number: int):
    """팀 하나. 이름은 한 줄에 하나씩 세로로 쌓는다.

    **코드박스를 쓰지 않는다** — 코드블록 안은 마크다운이 적용되지 않아 글자를 키울 수 없고,
    기본 본문보다 작게 렌더링된다. 디스코드에서 본문을 키우는 수단은 `#`·`##`·`###` 헤딩뿐이다.
    그래서 팀 번호를 `##` 로 키우고 이름은 본문 크기로 둔다.

    이름을 인용줄(`> `)로 묶는 이유는 왼쪽에 세로선이 생겨 팀이 한 블록으로 떨어져 보이기
    때문이다. 글머리표(`- `)는 빈자리 라벨(`대기 - 1`)과 하이픈이 겹쳐 지저분해진다.

    코드박스가 막아주던 마크다운을 직접 막아야 한다 — `_`·`*`·`~` 가 들어간 닉네임이
    기울임·취소선으로 깨지지 않게 escape 한다.
    """
    lines = [f"## {number}팀"]
    lines += [f"> {discord.utils.escape_markdown(entry_name(e))}" for e in team]
    return "\n".join(lines)

def build_teams_embed(participants, teams):
    """추첨 결과 Embed."""
    # 팀 번호가 ## 이므로 요약을 ### 로 두면 위계가 거꾸로 선다. 부가 정보라 작은 글씨로.
    blocks = [f"-# 총 {len(participants)}명 · {len(teams)}팀"]
    blocks += [format_team(team, number) for number, team in enumerate(teams, start=1)]

    embed = discord.Embed(
        title="🎲 내전 팀 추첨",
        description="\n".join(blocks),
        color=DRAW_COLOR,
    )
    embed.set_footer(text="아래 버튼을 누르면 본인 팀 번호를 따로 보여줍니다")
    return embed

def prepare_draw(guild):
    """(참가자 목록, 경기 목록, 오류문구) 를 돌려준다."""
    channel = discord.utils.get(guild.voice_channels, name=VOICE_CHANNEL_NAME)
    if channel is None:
        return None, None, "❌ 음성 채널을 찾을 수 없습니다."

    participants = collect_participants(channel)
    if not participants:
        return None, None, (
            f"❌ {channel.mention} 에 추첨할 인원이 없습니다.\n"
            "`관전_`·`대기_` 가 아닌 참가자가 있어야 합니다."
        )

    return participants, split_teams(participants), None

class MyTeamView(discord.ui.View):
    """결과 메시지에 붙는 '내 팀 확인' 버튼.

    봇이 각자에게 본인 팀만 보이는 메시지를 먼저 보낼 방법은 없다.
    본인에게만 보이는 응답(ephemeral)은 **그 사람이 버튼을 누른 것에 대한 답**으로만 보낼 수 있어서,
    누르는 방식이 된다. DM 은 차단해둔 사람에게 실패한다.

    영구 View 가 아니다 (custom_id 없음 + timeout 있음). 재시작하면 팀 정보가 사라지므로
    버튼도 같이 죽는 게 맞다 — 살아 있는데 "포함되지 않았습니다" 라고 답하면 더 혼란스럽다.
    """

    def __init__(self, team_index):
        super().__init__(timeout=MY_TEAM_TIMEOUT)
        self.team_index = team_index
        self.result_message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.result_message is None:
            return
        try:
            await self.result_message.edit(view=self)
        except discord.HTTPException:
            # 결과 메시지가 이미 지워진 경우
            pass

    @discord.ui.button(label="내 팀 확인", style=discord.ButtonStyle.primary)
    async def my_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        number = self.team_index.get(interaction.user.id)
        if number is None:
            await interaction.response.send_message(
                "이번 추첨에 포함되지 않았습니다.", ephemeral=True
            )
            schedule_dismiss(interaction, DISMISS_SECONDS)
            return

        await interaction.response.send_message(
            f"{interaction.user.mention} 님은 **{number}팀** 입니다",
            ephemeral=True,
            # 본인 멘션뿐이지만 멘션으로 알림이 가는 일이 없도록 못 박는다
            allowed_mentions=discord.AllowedMentions.none(),
        )
        schedule_dismiss(interaction, DISMISS_SECONDS)

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
            "사용법: `!내전맵뽑 2 코로드 브리즈 어센트 선셋`\n"
            "맵은 공백·쉼표 어느 쪽으로 구분해도 됩니다: `!내전맵뽑 2 코로드,브리즈,어센트,선셋`"
        )
    if count < 1:
        return 0, [], "⚠️ 뽑을 개수는 1 이상이어야 합니다."
    if count > len(maps):
        return 0, [], f"⚠️ 맵 {len(maps)}개 중 {count}개는 뽑을 수 없습니다."

    return count, maps, None

async def delete_command_message(ctx):
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

async def report_error(ctx, error, command_name: str, usage: str = None):
    """!내전 의 에러 핸들러와 같은 방식으로, 실패를 콘솔에만 남기지 않고 화면에 안내한다."""
    # 명령 본문이 실행되지 않은 경우(인자 누락·권한 부족)에도 명령 메시지는 치운다
    await delete_command_message(ctx)

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
    async def draw_teams(ctx):
        await delete_command_message(ctx)

        participants, teams, error = prepare_draw(ctx.guild)
        if error is not None:
            await ctx.send(error, delete_after=20)
            return

        # 결과를 먼저 확정해두고 '입력 중...' 만 띄운다. 메시지 편집을 쓰지 않으므로
        # 레이트 리밋과 무관하고, 결과는 한 번에 완성된 상태로 올라간다.
        async with ctx.channel.typing():
            await asyncio.sleep(TYPING_DELAY)

        view = MyTeamView(build_team_index(teams))
        view.result_message = await ctx.send(
            embed=build_teams_embed(participants, teams), view=view
        )

    @draw_teams.error
    async def draw_teams_error(ctx, error):
        await report_error(ctx, error, "!내전팀뽑")

    @bot.command(name="내전맵뽑")
    @has_permissions(administrator=True)
    async def draw_maps(ctx, *, raw: str):
        await delete_command_message(ctx)

        count, maps, error = parse_map_args(raw)
        if error is not None:
            await ctx.send(error, delete_after=20)
            return

        picked = _rng.sample(maps, count)

        lines = [f"### {len(maps)}개 중 {count}개"]
        # 뽑힌 맵이 제일 중요한 정보라 가장 크게 적는다
        lines += [f"## {number_mark(i)} {m}" for i, m in enumerate(picked)]

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
                "사용법: `!내전맵뽑 2 코로드 브리즈 어센트 선셋`\n"
                "맵은 공백·쉼표 어느 쪽으로 구분해도 됩니다: `!내전맵뽑 2 코로드,브리즈,어센트,선셋`"
            ),
        )
