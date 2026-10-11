import asyncio
import json
import logging
import re
from pathlib import Path

import discord
from discord.ext import commands
from discord.ext.commands import has_permissions

from nickname_commands import PREFIX_OBSERVER, PREFIX_WAITING

# 디스코드 닉네임 최대 길이
NICK_LIMIT = 32

# 어떤 접두어 조합이 붙어 있어도 '[연도2자리] [닉네임]' 기본형을 찾아낸다.
# 가장 앞쪽의 "두자리숫자 + 공백" 부터 끝까지를 기본형으로 본다.
BASE_PATTERN = re.compile(r"\d{2}\s.+$")

# 설치된 패널 위치를 기억한다.
# 실행 위치(systemd WorkingDirectory)에 의존하지 않도록 모듈 기준 경로를 쓴다.
STATE_PATH = Path(__file__).resolve().parent / "panel_state.json"

# 재설치 확인 대기 시간(초)
CONFIRM_TIMEOUT = 30

# 버튼 응답(ephemeral)을 몇 초 후 자동으로 치울지.
# 유저가 "메시지 닫기"를 누르지 않아도 응답이 쌓이지 않게 하기 위함.
AUTO_DISMISS_SECONDS = 10

MODE_OBSERVER = "관전"
MODE_WAITING = "대기"
MODE_RESET = "초기화"

PREFIXES = {
    MODE_OBSERVER: PREFIX_OBSERVER,
    MODE_WAITING: PREFIX_WAITING,
}

def extract_base(display_name: str):
    """어떤 상태의 닉네임에서든 기본형을 복원한다. 복원 불가하면 None.

    '00 홍길동'           -> '00 홍길동'
    '관전_00 홍길동'      -> '00 홍길동'
    '관전_대기_00 홍길동' -> '00 홍길동'   (겹친 접두어 정리)
    'ㅁㄴㅇ00 홍길동'     -> '00 홍길동'   (실수로 붙은 문자 제거)
    '홍길동'              -> None         (연도가 없어 복원 불가)
    """
    m = BASE_PATTERN.search(display_name)
    return m.group(0) if m else None

def resolve_nickname(current: str, mode: str):
    """(바꿀 닉네임, 안내 문구) 를 돌려준다. 바꿀 필요가 없으면 첫 값이 None.

    기본형으로 되돌린 뒤 목표 접두어를 붙이는 방식이라,
    접두어가 겹치거나 깨진 상태에서도 항상 정상 상태로 수렴한다.
    """
    base = extract_base(current)
    if base is None:
        return None, (
            f"⚠️ 닉네임에서 `[연도] [닉네임]` 형식을 찾을 수 없습니다: `{current}`\n"
            "관리자에게 닉네임 정리를 요청해주세요."
        )

    if mode == MODE_RESET:
        if current == base:
            return None, f"이미 기본 닉네임입니다: `{base}`"
        return base, f"🔄 초기화했습니다: `{base}`"

    prefix = PREFIXES[mode]

    # 이미 해당 모드면 그대로 둔다. 텍스트 명령(!ㄱㅈ / !ㄷㄱ)과 동일한 동작이며
    # 해제는 [초기화] 로만 한다.
    # 단 깨진 상태(예: '관전_대기_00 홍길동')는 접두어가 정확히 일치하지 않으므로
    # 아래로 내려가 '관전_00 홍길동' 으로 정규화된다.
    if current == prefix + base:
        return None, f"이미 {mode} 모드입니다."

    return prefix + base, f"✅ {mode}: `{prefix}{base}`"

# asyncio.create_task 의 결과를 들고 있지 않으면 GC 될 수 있어 참조를 보관한다.
_dismiss_tasks = set()

async def _dismiss_later(interaction: discord.Interaction, delay: float):
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except discord.HTTPException:
        # 유저가 이미 닫았거나 토큰(15분)이 만료된 경우
        pass

def schedule_dismiss(interaction: discord.Interaction, delay: float = None):
    """ephemeral 응답을 delay 초 후 자동으로 삭제하도록 예약한다.

    기본 인자에 상수를 직접 쓰면 import 시점에 값이 고정되므로 None 으로 받아
    호출 시점에 AUTO_DISMISS_SECONDS 를 읽는다.
    """
    if delay is None:
        delay = AUTO_DISMISS_SECONDS
    task = asyncio.create_task(_dismiss_later(interaction, delay))
    _dismiss_tasks.add(task)
    task.add_done_callback(_dismiss_tasks.discard)

def load_panel_state():
    """저장된 패널 위치를 (channel_id, message_id) 로 돌려준다. 없으면 (None, None)."""
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return int(data["channel_id"]), int(data["message_id"])
    except FileNotFoundError:
        return None, None
    except (ValueError, KeyError, TypeError, OSError) as e:
        # json.JSONDecodeError 는 ValueError 하위
        logging.warning("패널 상태 파일을 읽을 수 없습니다 (%s). 미설치로 간주합니다.", e)
        return None, None

def save_panel_state(channel_id: int, message_id: int):
    STATE_PATH.write_text(
        json.dumps({"channel_id": channel_id, "message_id": message_id}, indent=2),
        encoding="utf-8",
    )

async def fetch_existing_panel(bot: commands.Bot, channel_id, message_id):
    """저장된 패널 메시지를 찾아 (메시지, 오류문구) 를 돌려준다.

    (Message, None) - 패널이 살아있음
    (None, None)    - 기록 없음 / 채널 없음 / 메시지 삭제됨  -> 미설치로 간주
    (None, str)     - 권한·통신 문제로 확인 불가             -> 중복 설치 위험, 중단해야 함
    """
    if channel_id is None or message_id is None:
        return None, None

    channel = bot.get_channel(channel_id)
    if channel is None:
        return None, None

    try:
        return await channel.fetch_message(message_id), None
    except discord.NotFound:
        # 누가 패널 메시지를 수동으로 지운 경우 -> 미설치로 간주
        return None, None
    except discord.Forbidden:
        return None, f"<#{channel_id}> 의 메시지를 읽을 권한이 없습니다"
    except discord.HTTPException as e:
        return None, f"조회 실패 ({e})"

class ConfirmReinstall(discord.ui.View):
    """패널을 다른 채널로 옮길지 묻는 일회용 확인 버튼."""

    def __init__(self, author_id: int):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.author_id = author_id
        self.result = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 명령을 실행한 관리자만 선택할 수 있게 한다
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "⚠️ 명령을 실행한 관리자만 선택할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="예, 여기로 옮기기", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="아니오", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        await interaction.response.defer()
        self.stop()

class StatusPanel(discord.ui.View):
    """봇 전용 채널에 상시 띄워두는 관전/대기/초기화 패널."""

    def __init__(self):
        super().__init__(timeout=None)   # timeout=None + custom_id -> 재시작 후에도 동작

    async def _respond(self, interaction: discord.Interaction, content: str):
        """결과를 누른 본인에게만 보여주고, 일정 시간 후 자동으로 치운다."""
        await interaction.edit_original_response(content=content)
        schedule_dismiss(interaction)

    async def _apply(self, interaction: discord.Interaction, mode: str):
        # 닉네임 변경이 레이트 리밋에 걸리면 디스코드의 최초 응답 제한(3초)을 넘길 수 있다.
        # 먼저 응답을 유보해 15분까지 여유를 확보한다.
        # component 인터랙션에서는 thinking=True 가 없으면 ephemeral 이 무시된다.
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 이후 응답은 edit_original_response 로 로딩 메시지를 교체한다.
        # defer 직후의 followup.send 는 같은 동작을 하지만 디스코드 문서상 deprecated 경로다.
        # ephemeral 여부는 위 defer 에서 이미 결정되므로 다시 지정하지 않는다.

        member = interaction.user
        if not isinstance(member, discord.Member):
            await self._respond(interaction, "⚠️ 서버 안에서만 사용할 수 있습니다.")
            return

        current = member.display_name
        new_nick, message = resolve_nickname(current, mode)

        if new_nick is None:
            await self._respond(interaction, message)
            return

        if len(new_nick) > NICK_LIMIT:
            await self._respond(
                interaction,
                f"⚠️ 닉네임이 {len(new_nick)}자가 되어 디스코드 제한({NICK_LIMIT}자)을 넘습니다.",
            )
            return

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            await self._respond(
                interaction,
                "❌ 권한이 부족해 닉네임을 바꿀 수 없습니다. (봇 역할이 대상보다 높아야 합니다)",
            )
            return
        except discord.HTTPException as e:
            logging.error("닉네임 변경 실패 (%s -> %s)", current, new_nick, exc_info=e)
            await self._respond(interaction, f"❌ 오류: {e}")
            return

        await self._respond(interaction, message)

    @discord.ui.button(label="관전", style=discord.ButtonStyle.success,
                       custom_id="vf:status:observer")
    async def observer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, MODE_OBSERVER)

    @discord.ui.button(label="대기", style=discord.ButtonStyle.primary,
                       custom_id="vf:status:waiting")
    async def waiting(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, MODE_WAITING)

    @discord.ui.button(label="초기화", style=discord.ButtonStyle.danger,
                       custom_id="vf:status:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, MODE_RESET)

# Embed 왼쪽 색 띠. 라이트/다크 테마 양쪽에서 읽히는 색이어야 한다.
PANEL_COLOR = 0x5865F2

def build_panel_embed() -> discord.Embed:
    """패널 Embed 를 새로 만들어 돌려준다.

    Embed 는 가변 객체라 모듈 전역에 하나만 두고 돌려쓰면
    나중에 호출부에서 필드를 덧붙일 때 서로 영향을 준다.
    """
    return discord.Embed(
        title="상태 변경",
        description=(
            "아래 버튼을 눌러 관전/대기 상태로 변경 또는 해제할 수 있습니다.\n\n"
            f"• **관전** — 닉네임 앞에 `{PREFIX_OBSERVER}` 를 붙입니다\n"
            f"• **대기** — 닉네임 앞에 `{PREFIX_WAITING}` 를 붙입니다\n"
            "• **초기화** — 접두어를 제거해 `[연도] [닉네임]` 기본형으로 되돌립니다"
            " (관전/대기 해제)\n\n"
            "-# 응답은 누른 본인에게만 보입니다."
        ),
        color=PANEL_COLOR,
    )

def setup_status_panel(bot: commands.Bot):
    registered = False

    # View 생성은 실행 중인 이벤트 루프를 요구하므로 bot.run() 전에는 만들 수 없다.
    # on_ready 는 재연결마다 다시 발생하므로 1회만 등록한다.
    # @bot.event 가 아니라 @bot.listen 이므로 다른 핸들러를 덮어쓰지 않는다.
    @bot.listen("on_ready")
    async def register_panel_view():
        nonlocal registered
        if registered:
            return
        # message_id 를 지정하지 않는다. 지정하면 저장된 기록이 실제 패널과 어긋날 때
        # 버튼이 조용히 죽는다. message_id 없이 등록하면 ViewStore 가 None 키
        # 폴백으로 조회하므로 어느 패널 메시지에서든 동작한다.
        bot.add_view(StatusPanel())
        registered = True
        logging.info("관전/대기 패널 View 등록 완료")

    @bot.command(name="패널설치")
    @has_permissions(administrator=True)
    async def install_panel(ctx):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        channel_id, message_id = load_panel_state()
        existing, error = await fetch_existing_panel(bot, channel_id, message_id)

        if error is not None:
            await ctx.send(
                f"⚠️ 기존 패널 상태를 확인할 수 없습니다: {error}\n"
                "패널이 두 개가 되지 않도록 설치를 중단했습니다.",
                delete_after=30,
            )
            return

        if existing is not None:
            # 같은 채널이면 새로 설치하지 않고 기존 패널의 문구/버튼을 갱신한다
            if existing.channel.id == ctx.channel.id:
                try:
                    await existing.edit(
                        content=None, embed=build_panel_embed(), view=StatusPanel()
                    )
                except discord.HTTPException as e:
                    logging.warning("패널 갱신 실패: %s", e)
                    await ctx.send(
                        f"❌ 기존 패널을 갱신하지 못했습니다: {e}", delete_after=30
                    )
                    return
                await ctx.send(
                    "🔄 이 채널의 패널을 최신 문구로 갱신했습니다.", delete_after=15
                )
                return

            # 다른 채널이면 옮길지 확인한다
            view = ConfirmReinstall(ctx.author.id)
            prompt = await ctx.send(
                f"⚠️ {existing.channel.mention} 에 이미 패널이 설치되어 있습니다.\n"
                f"기존 패널을 지우고 이 채널로 옮길까요? ({CONFIRM_TIMEOUT}초 내 선택)",
                view=view,
            )
            await view.wait()

            try:
                await prompt.delete()
            except discord.HTTPException:
                pass

            if not view.result:
                await ctx.send(
                    "취소했습니다. 기존 패널을 그대로 유지합니다.", delete_after=15
                )
                return

            try:
                await existing.delete()
            except discord.Forbidden:
                await ctx.send(
                    f"❌ {existing.channel.mention} 의 기존 패널을 삭제할 권한이 없습니다.\n"
                    "패널이 두 개가 되지 않도록 설치를 중단했습니다. "
                    "수동으로 삭제한 뒤 다시 시도해주세요.",
                    delete_after=30,
                )
                return
            except discord.NotFound:
                pass   # 확인하는 사이에 누가 지웠다면 그냥 진행
            except discord.HTTPException as e:
                logging.warning("기존 패널 삭제 실패: %s", e)

        message = await ctx.send(embed=build_panel_embed(), view=StatusPanel())

        try:
            save_panel_state(message.channel.id, message.id)
        except OSError as e:
            logging.error("패널 상태 저장 실패: %s", e)
            await ctx.send(
                "⚠️ 패널은 설치했지만 위치를 저장하지 못했습니다. "
                "재설치 확인 기능이 동작하지 않을 수 있습니다.",
                delete_after=30,
            )
            return

        logging.info(
            "패널 설치 완료 (channel=%s, message=%s)", message.channel.id, message.id
        )

    @install_panel.error
    async def install_panel_error(ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⚠️ `!패널설치`는 관리자만 사용할 수 있습니다.", delete_after=10)
        else:
            raise error
