# VF_discordBot
"모여봐요 발로의 숲" Discord Bot Code

## 파일 구성
- `main.py` — 봇 구동 파일. 토큰 로드, 인텐트 설정, 서브 모듈 초기화
- `nickname_commands.py` — 관전/대기/초기화 접두어 수정 (텍스트 명령)
- `attendance_check.py` — 내전 인원 체크
- `status_panel.py` — 관전/대기/초기화 버튼 패널

## 사전 설정

### 1. 의존성
```
python3 -m venv venv
venv/bin/pip install discord.py python-dotenv
```

### 2. `.env` (저장소에 올리지 않음)
`src/.env` 에 봇 토큰을 넣는다.
```
DISCORD_BOT_TOKEN=봇토큰
```

### 3. Developer Portal 인텐트
Bot 설정에서 아래 두 개를 **켜야 한다**. 끄면 봇이 기동되지 않거나 명령이 동작하지 않는다.
- SERVER MEMBERS INTENT
- MESSAGE CONTENT INTENT

### 4. 봇 역할 권한
- `닉네임 관리` — 다른 멤버의 닉네임을 변경하는 데 필요
- `메시지 관리` — 명령 메시지 자동 삭제에 필요
- **봇 역할이 대상 멤버의 역할보다 위에 있어야 한다.** 아래에 있으면 닉네임 변경이 거부된다(서버 소유자는 변경 불가)

### 5. 런타임 파일
- `src/panel_state.json` — 설치된 패널의 채널/메시지 ID를 기억한다. 자동 생성되며 저장소에 올리지 않는다

## 닉네임 규칙
- 유저의 닉네임은 `[숫자2개(연도뒷자리)][스페이스][닉네임]` 형태로 구성되어 있어야 한다
- 기본 닉네임이 `00 홍길동` 일 경우 관전, 대기, 초기화에 따라 `관전_00 홍길동`, `대기_00 홍길동`, `00 홍길동` 으로 분류
- 이 형태가 아니면 `!내전` 집계와 버튼 패널이 해당 유저를 처리하지 못한다

## 버튼 패널
봇 전용 채널에 상시 띄워두는 패널. 텍스트 명령과 동작이 같고, **응답이 누른 본인에게만 보인다.**
응답은 10초 후 자동으로 사라지므로 직접 "메시지 닫기"를 누를 필요가 없다.

- 설치: 봇 전용 채널에서 `!패널설치` (관리자 전용, 1회만)
  - 같은 채널에서 다시 실행하면 기존 패널의 문구/버튼을 최신 코드로 갱신한다 (문구를 수정했을 때 사용)
  - 다른 채널에서 실행하면 기존 패널을 지우고 옮길지 확인한다
  - 봇을 재시작해도 기존 패널의 버튼은 계속 동작한다
- 채널 설정: `@everyone` 의 `메시지 보내기` 를 끄면 패널만 남아 깔끔하다
- 버튼
  - `관전` — `관전_` 부여. 이미 관전이면 변경하지 않고 안내만 한다
  - `대기` — `대기_` 부여. 이미 대기이면 변경하지 않고 안내만 한다
  - `초기화` — 접두어를 제거해 기본형으로 되돌린다. 접두어가 겹치거나(`관전_대기_00 홍길동`) 앞에 엉뚱한 문자가 붙은 경우도 복구한다

## 텍스트 명령어
- 기본적으로 `!` 로 시작함
- 명령 메시지와 응답은 자동으로 삭제된다 (응답은 5초 후)
- 관전 명령어
  - nickname_commands.py의 WATCH_COMMANDS 참조
  - "!ㄱㅈ", "!rw", "!관전", "!rhkswjs", "!RW", "!ㄲㅉ", "!RHKSWJS"
- 대기 명령어
  - nickname_commands.py의 WAIT_COMMANDS 참조
  - "!ㄷㄱ", "!er", "!대기", "!eorl" ,"!ER", "!ㄸㄲ", "!EORL"
- 초기화 명령어
  - nickname_commands.py의 RESET_COMMANDS 참조
  - "!ㄱㄱ", "!rr", "!RR", "!ㄲㄲ"
- 내전 인원 체크 명령어 (관리자 전용)
  - `!내전 [유저명]`
  - 유저명은 `,` 로 구분하고, **연도 없이 이름만 입력한다**
  - ex) `!내전 홍길동, 김철수, 김영희, 박민수`
  - 연도를 붙여 입력하면(`00 홍길동`) 인식되지 않으므로 주의
  - 실행하면 `⏳ 내전 인원을 확인하고 있습니다...` 가 먼저 뜨고, 완료되면 그 메시지가 결과로 바뀐다
  - 하는 일
    - 명단에 있고 음성 채널에 있는 유저 → 접두어 제거
    - 명단에 없는데 음성 채널에 있는 유저 → `관전_` 부여
    - 명단에 있는데 음성 채널에 없는 유저 → 미접속으로 보고
  - 대상 음성 채널은 `attendance_check.py` 의 `VOICE_CHANNEL_NAME` 참조

## 봇 운영 환경

트래커 웹(`VF_scrim_Tracker`)과 **같은 VM 1대**에서 함께 돌아간다. 봇과 웹은 별개 서비스다.

- **인스턴스:** GCP e2-micro(1GB RAM), Ubuntu 22.04 LTS Minimal, 표준 영구디스크, swap 1GB
  - 구버전 f1-micro(봇 전용)는 2026-07-23에 삭제됨
- **서비스 유저:** `vf` — 앱은 `/home/vf/VF_discordBot` 에 clone
- **서비스:** `vf-bot.service` (웹은 `vf.service` — 혼동 주의)
- **의존성:** `discord.py` + `python-dotenv` (표준 라이브러리 외 추가 없음)
  ```
  cd ~/VF_discordBot
  uv venv
  uv pip install discord.py python-dotenv
  ```
- **토큰:** `src/.env` 의 `DISCORD_BOT_TOKEN` (`main.py` 의 `load_dotenv()` 가 WorkingDirectory 기준으로 읽음)

### ⚠️ 계정 권한 분리 — 배포 시 가장 많이 걸리는 부분

최소권한 설계라 작업에 따라 계정을 바꿔야 한다.

| 작업 | 계정 | 이유 |
|---|---|---|
| `git pull`, 파일 수정, venv | **`vf`** (`sudo su - vf`) | 레포가 `vf` 소유 |
| `systemctl` 등 시스템 작업 | **본인 GCP 계정** (`exit` 후) | `vf` 는 sudoers 에 없고 비번도 잠김 |

`vf` 상태에서 `sudo` 는 **무조건 실패**한다("try again"). 반대로 GCP 브라우저 SSH 계정은 passwordless sudo 라 `sudo` 만 제대로 붙으면 된다.

### 코드 배포 (평소 업데이트)

```
sudo su - vf
cd ~/VF_discordBot
git status          # 로컬 수정 없는지 확인
git pull
exit
```
```
sudo systemctl restart vf-bot
journalctl -u vf-bot -n 20 --no-pager
```

기동 성공 시 로그에 아래가 보인다.
```
INFO:root:관전/대기 패널 View 등록 완료
✅ Bot connected as <봇이름>
```

`git pull` 만으로는 반영되지 않는다 — 파이썬이 기동 시 코드를 메모리로 import 하므로 **반드시 restart** 가 필요하다.
패널 문구를 바꾼 경우에는 restart 후 디스코드에서 `!패널설치` 를 한 번 더 실행해야 기존 패널 메시지가 갱신된다.

### 상태 확인 / 로그

```
systemctl status vf-bot
journalctl -u vf-bot -f          # 실시간
journalctl -u vf-bot -n 100 --no-pager
sudo systemctl show vf-bot -p ActiveState,ActiveEnterTimestamp
```

### 되돌리기

```
sudo su - vf
cd ~/VF_discordBot && git reset --hard <직전커밋>
exit
sudo systemctl restart vf-bot
```

### systemd 유닛

실제 설치본은 VM 의 `/etc/systemd/system/vf-bot.service` 다. **재설치 전에 반드시 아래로 실물을 확인**할 것.

```
cat /etc/systemd/system/vf-bot.service
```

아래는 운영 기록으로부터 재구성한 참고본이다(실물과 다를 수 있음).

```
[Unit]
Description=VF Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vf
Group=vf
WorkingDirectory=/home/vf/VF_discordBot/src
ExecStart=/home/vf/VF_discordBot/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

유닛 파일을 수정했을 때:

```
sudo systemctl daemon-reload
sudo systemctl restart vf-bot
sudo systemctl status vf-bot
```

### 브라우저 SSH 주의

GCP 콘솔의 브라우저 SSH 는 긴 한 줄을 붙여넣을 때 **공백을 끼워 넣거나 heredoc 의 `EOF` 를 못 닫아** `>` 연속 프롬프트에 걸리는 경우가 있다. 명령은 짧게 끊어서 한 줄씩 넣는다.
`sudo` 가 쪼개져 떨어지면 polkit "authentication is required" 가 뜨는데, 그건 `sudo` 가 안 붙은 것이니 다시 입력하면 된다.
