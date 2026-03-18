# 생산 시스템 모니터링 봇

Supabase DB를 감시하여 이상 발생 시 **Telegram**으로 알림을 보냅니다.

---

## 감시 항목

| 항목 | 내용 |
|------|------|
| 중복 시리얼 | 동일 S/N이 활성 레코드에 2건 이상 |
| 상태 이상 | `STUCK_HOURS`시간 이상 진행 상태로 멈춰있는 레코드 |
| DB 연결 오류 | Supabase 연결 실패 |
| 데이터 정합성 | 빈 시리얼, 잘못된 상태값, 반(班) 필드 누락 |

---

## 빠른 시작

### 1단계 — Telegram 봇 만들기

1. Telegram에서 **@BotFather** 에게 `/newbot` 전송 → **Bot Token** 발급
2. 발급받은 봇에게 아무 메시지 전송
3. 아래 URL에서 `chat_id` 확인:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   → `result[0].message.chat.id` 값

---

### 2단계 — 환경변수 설정

```bash
cp monitor/.env.example monitor/.env
# .env 파일을 열어 값 채우기
```

---

### 3단계 — 실행 방법 선택

#### A) GitHub Actions (서버 불필요, 무료)

GitHub 리포지토리 → **Settings → Secrets and variables → Actions**

**Secrets** 4개 등록:
| 이름 | 값 |
|------|----|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | Supabase anon/service key |
| `TELEGRAM_BOT_TOKEN` | BotFather에서 발급받은 토큰 |
| `TELEGRAM_CHAT_ID` | getUpdates로 확인한 chat id |

**Variables** (선택):
| 이름 | 기본값 | 설명 |
|------|--------|------|
| `STUCK_HOURS` | `8` | 정체 판단 시간(h) |

푸시하면 5분마다 자동 실행됩니다.
수동 실행: **Actions → 생산 시스템 모니터링 봇 → Run workflow**

---

#### B) 로컬 / 서버 상시 실행

```bash
cd monitor
pip install -r requirements.txt
cp .env.example .env     # 값 채우기

# 상시 루프 실행
python monitor.py

# 1회만 실행
python monitor.py --once
```

백그라운드 실행 (Linux):
```bash
nohup python monitor.py > /dev/null 2>&1 &
```

---

## 알림 예시

**이상 감지 시:**
```
🚨 생산 시스템 이상 감지
🕐 2026-03-18 09:32 KST

⚠️ 중복 시리얼 2건
  • SN-00123  2개 중복  [조립중 / 검사대기]  반: 제조1반

⏰ 장시간 정체 5건  (8h 이상 미처리)
  • SN-00456  [제조2반]  불량 처리 중  2026-03-17 23:10
  ...

🔴 데이터 정합성 이슈
  • 빈 시리얼 1건 (반: 제조3반)
```

**복구 시:**
```
✅ 모든 이슈 해결됨
🕐 2026-03-18 10:15 KST
생산 시스템이 정상 상태입니다.
```

---

## 설정 값

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `STUCK_HOURS` | `8` | 정체 판단 기준 시간 |
| `CHECK_INTERVAL_SEC` | `300` | 체크 주기(초) — 루프 모드 전용 |

---

## 파일 구조

```
monitor/
├── monitor.py          # 메인 봇
├── .env.example        # 환경변수 템플릿
├── requirements.txt    # 의존성
├── monitor_state.json  # 중복 알림 방지용 상태 (자동 생성)
└── monitor.log         # 실행 로그 (자동 생성)

.github/workflows/
└── monitor.yml         # GitHub Actions 워크플로
```
