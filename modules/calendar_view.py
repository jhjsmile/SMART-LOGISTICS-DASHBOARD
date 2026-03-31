import streamlit as st
import pandas as pd
from datetime import date, timedelta
import calendar
import html as html_mod

from modules.database import (
    load_schedule, insert_schedule, update_schedule, delete_schedule,
    insert_schedule_change_log,
    insert_audit_log, _clear_schedule_cache, _clear_production_cache,
    load_realtime_ledger, load_production_plan,
    update_row,
)
from modules.auth import check_perm
from modules.utils import get_now_kst_str
from modules.constants import (
    PRODUCTION_GROUPS, CALENDAR_EDIT_ROLES, SCHEDULE_COLORS,
    PLAN_CATEGORIES, SCH_CHANGE_REASONS,
)

# =================================================================
# 캘린더 유틸리티
# =================================================================
def _xp(key: str) -> bool:
    """현재 페이지의 expander 열림 상태 반환 (없으면 False=접힘)."""
    return bool(st.session_state.get(f"_xp_{key}", False))

def _rerun(xp_key: str = None) -> None:
    """st.rerun() 래퍼.  expander 내부 버튼에서 호출하면 해당 expander 를
    다음 렌더링에서도 열린 상태(expanded=True)로 유지한다."""
    if xp_key:
        st.session_state[f"_xp_{xp_key}"] = True
    st.rerun()

def show_inline_day_panel():
    """캘린더 날짜 클릭 시 인라인으로 일정 표시 (dialog 대신)"""
    # 이 패널이 어느 캘린더 expander 안에서 열렸는지 추적
    _dp_xp_key = st.session_state.get("_cal_active_xp", "cal_weekly")

    action      = st.session_state.get("cal_action")
    action_data = st.session_state.get("cal_action_data")
    if not action or not action_data:
        return

    can_edit = st.session_state.user_role in CALENDAR_EDIT_ROLES and check_perm("생산 지표 관리", "edit")
    sch_df   = st.session_state.schedule_db

    # ── 패널 컨테이너 ─────────────────────────────────────────
    with st.container(border=True):

        # ── 수정 폼 모드 ──────────────────────────────────────
        if action == "edit":
            sch_id  = action_data
            matched = sch_df[sch_df['id'] == sch_id]
            if matched.empty:
                st.warning("일정을 찾을 수 없습니다.")
                if st.button("닫기", key="inline_edit_notfound_close"):
                    st.session_state.cal_action = None; _rerun(_dp_xp_key)
                return

            r = matched.iloc[0]
            saved_date = str(r.get('날짜', ''))

            ph1, ph2 = st.columns([8, 1])
            ph1.markdown(f" **일정 수정** — {saved_date}")
            if ph2.button("✕", key="inline_edit_close"):
                st.session_state.cal_action = None; _rerun(_dp_xp_key)

            if not can_edit:
                st.info(f"카테고리: {r.get('카테고리','')} / 모델명: {r.get('모델명','')} / 처리수: {r.get('조립수',0)}대")
                return

            save_done_key = f"edit_saved_{sch_id}"
            cur_cat = r.get('카테고리', '조립계획')
            cat_idx = PLAN_CATEGORIES.index(cur_cat) if cur_cat in PLAN_CATEGORIES else 0

            with st.form("edit_sch_form_inline"):
                cat   = st.selectbox("계획 유형 *", PLAN_CATEGORIES, index=cat_idx)
                fe1, fe2 = st.columns(2)
                model = fe1.text_input("모델명", value=str(r.get('모델명', '')))
                pn    = fe2.text_input("P/N",    value=str(r.get('pn', '')))
                ff1, ff2 = st.columns(2)
                try: _qty_val = int(float(r.get('조립수', 0))) if str(r.get('조립수', '')).strip() not in ('', 'nan', 'None') else 0
                except (ValueError, TypeError): _qty_val = 0
                qty   = ff1.number_input("처리수", min_value=0, step=1, value=_qty_val)
                ship  = ff2.text_input("출하계획", value=str(r.get('출하계획', '')))
                note  = st.text_input("특이사항", value=str(r.get('특이사항', '')))
                etc   = st.text_input("기타")
                st.markdown("---")
                dr1, dr2 = st.columns(2)
                sch_reason = dr1.selectbox("변경 사유 *(필수)", SCH_CHANGE_REASONS, key=f"ie_reason_{sch_id}")
                sch_detail = dr2.text_input("상세 내용", placeholder="예: 고객사 요청", key=f"ie_detail_{sch_id}")
                c1, c2, c3 = st.columns(3)
                save_label = " 저장 완료" if st.session_state.get(save_done_key) else " 저장"
                if c1.form_submit_button(save_label, use_container_width=True, type="primary"):
                    if not st.session_state.get(save_done_key):
                        if sch_reason == "(선택 필수)":
                            st.error("변경 사유를 반드시 선택해주세요.")
                        else:
                            note_combined = " / ".join(filter(None, [note.strip(), etc.strip()]))
                            _prev = f"유형:{r.get('카테고리','')} 모델:{r.get('모델명','')} 조립수:{r.get('조립수',0)}"
                            _next = f"유형:{cat} 모델:{model.strip()} 조립수:{int(qty)}"
                            _reason_final = sch_detail.strip() if sch_reason == "기타 (직접 입력)" and sch_detail.strip() else sch_reason
                            update_schedule(sch_id, {
                                '카테고리': cat, 'pn': pn.strip(), '모델명': model.strip(),
                                '조립수': int(qty), '출하계획': ship.strip(), '특이사항': note_combined
                            })
                            insert_schedule_change_log(
                                sch_id=sch_id, 날짜=saved_date,
                                반=str(r.get('반','')), 모델명=model.strip(),
                                이전내용=_prev, 변경내용=_next,
                                변경사유=_reason_final, 사유상세=sch_detail.strip(),
                                작업자=st.session_state.user_id
                            )
                            _clear_schedule_cache()
                            st.session_state.schedule_db    = load_schedule()
                            st.session_state[save_done_key] = True
                            _rerun(_dp_xp_key)
                if c2.form_submit_button(" 목록으로", use_container_width=True):
                    st.session_state.cal_action      = "view_day"
                    st.session_state.cal_action_data = saved_date
                    st.session_state[save_done_key]  = False
                    _rerun(_dp_xp_key)
                if c3.form_submit_button(" 삭제", use_container_width=True):
                    delete_schedule(sch_id)
                    _clear_schedule_cache()
                    st.session_state.schedule_db    = load_schedule()
                    st.session_state.cal_action     = None
                    st.session_state[save_done_key] = False
                    _rerun(_dp_xp_key)
            if st.session_state.get(save_done_key):
                st.success("저장되었습니다.")
            return

        # ── 일정 추가 폼 모드 ─────────────────────────────────
        if action == "add":
            selected_date = action_data
            ph1, ph2 = st.columns([8, 1])
            ph1.markdown(f" **일정 추가** — {selected_date}")
            if ph2.button("✕", key="inline_add_close"):
                st.session_state.cal_action = None; _rerun(_dp_xp_key)

            if not can_edit:
                st.warning("일정 추가 권한이 없습니다.")
                return

            # ── 반 선택 (폼 외부 — 변경 시 모델/품목 목록 즉시 갱신) ──
            _add_ban_key = "sch_add_ban_sel"
            if _add_ban_key not in st.session_state:
                st.session_state[_add_ban_key] = PRODUCTION_GROUPS[0]
            ban = st.selectbox("반 *", PRODUCTION_GROUPS, key=_add_ban_key)

            _ban_models  = st.session_state.group_master_models.get(ban, [])
            _ban_all_pns = list(dict.fromkeys(
                _pn for _m in _ban_models
                for _pn in st.session_state.group_master_items.get(ban, {}).get(_m, [])
            ))

            with st.form("add_sch_form_inline"):
                cat = st.selectbox("계획 유형 *", PLAN_CATEGORIES)
                fa1, fa2 = st.columns(2)

                # 모델명 — 등록 목록 드롭박스 + 직접 입력 병행
                _m_opts = [""] + _ban_models
                model_sel = fa1.selectbox("모델명 (등록 목록)", _m_opts,
                                          help="목록에서 선택하거나 아래에 직접 입력")
                model_txt = fa1.text_input("모델명 직접 입력", placeholder="목록에 없으면 여기 입력")

                # P/N — 등록 목록 드롭박스 + 직접 입력 병행
                _pn_opts = [""] + _ban_all_pns
                pn_sel = fa2.selectbox("P/N (등록 목록)", _pn_opts,
                                       help="목록에서 선택하거나 아래에 직접 입력")
                pn_txt = fa2.text_input("P/N 직접 입력", placeholder="목록에 없으면 여기 입력")

                qty_str = st.text_input("처리수", value="0", placeholder="숫자 입력")
                note    = st.text_input("특이사항")
                etc     = st.text_input("기타")

                if st.form_submit_button(" 등록", use_container_width=True, type="primary"):
                    if st.session_state.get("_sch_add_saving"):
                        st.warning("저장 중입니다. 잠시 기다려주세요.")
                    else:
                        try:
                            qty = max(0, int(qty_str.strip() or "0"))
                        except ValueError:
                            qty = 0
                        # 직접 입력 우선, 없으면 드롭박스 선택값
                        model = model_txt.strip() or model_sel
                        pn    = pn_txt.strip()    or pn_sel
                        if model.strip() or note.strip():
                            note_combined = " / ".join(filter(None, [note.strip(), etc.strip()]))
                            st.session_state["_sch_add_saving"] = True
                            with st.spinner(" 일정 등록 중..."):
                                result = insert_schedule({
                                    '날짜': selected_date, '반': ban,
                                    '카테고리': cat, 'pn': pn, '모델명': model,
                                    '조립수': qty, '출하계획': '',
                                    '특이사항': note_combined, '작성자': st.session_state.user_id
                                })
                            st.session_state.pop("_sch_add_saving", None)
                            if result:
                                _clear_schedule_cache()
                                st.session_state.schedule_db = load_schedule()
                                st.session_state.cal_action       = "view_day"
                                st.session_state.cal_action_data  = selected_date
                                st.session_state["_sch_add_toast"] = f" [{ban}] {selected_date} 일정 등록 완료"
                                _rerun(_dp_xp_key)
                            # 실패 시: insert_schedule() 내부에서 st.error() 호출됨
                        else:
                            st.warning("모델명 또는 특이사항을 입력해주세요.")
            return

        # ── 일정 목록 보기 (view_day) ─────────────────────────
        selected_date = action_data
        day_data = sch_df[sch_df['날짜'] == selected_date] if not sch_df.empty else pd.DataFrame()

        # rerun 후 toast 메시지 표시
        _add_toast = st.session_state.pop("_sch_add_toast", None)
        if _add_toast:
            st.success(_add_toast)
        _del_toast = st.session_state.pop("_sch_del_toast", None)
        if _del_toast:
            if "" in _del_toast:
                st.success(_del_toast)
            else:
                st.error(_del_toast)

        ph1, ph2 = st.columns([8, 1])
        ph1.markdown(
            f"###  {html_mod.escape(str(selected_date))} &nbsp;<span style='font-size:0.85rem;color:#8a7f72;font-weight:normal;'>총 {len(day_data)}건</span>",
            unsafe_allow_html=True
        )
        if ph2.button(" 닫기", key="inline_view_close"):
            st.session_state.cal_action = None; _rerun(_dp_xp_key)

        if not day_data.empty:
            BAN_COLORS = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}
            # 성능: HTML 이스케이프 헬퍼를 루프 밖으로 이동 (루프마다 재정의 방지)
            def _esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            for ban in PRODUCTION_GROUPS:
                ban_rows = day_data[day_data['반'] == ban]
                if ban_rows.empty:
                    continue
                ban_color = BAN_COLORS.get(ban, "#7a6f65")
                _ban_esc = html_mod.escape(str(ban))
                st.markdown(
                    f"<div style='background:{ban_color}12; border-left:4px solid {ban_color}; "
                    f"padding:7px 14px; border-radius:5px; margin:12px 0 4px 0;'>"
                    f"<span style='color:{ban_color}; font-weight:bold; font-size:0.92rem;'> {_ban_esc}</span>"
                    f"<span style='color:#8a7f72; font-size:0.8rem; margin-left:8px;'>{len(ban_rows)}건</span>"
                    f"</div>", unsafe_allow_html=True
                )
                col_w = [1.8, 2.8, 1.5, 1.2, 1.8, 0.9] if can_edit else [1.8, 2.8, 1.5, 1.2, 2.2]
                hdrs  = ["카테고리", "모델명", "P/N", "처리수", "출하계획"] + (["관리"] if can_edit else [])
                hcols = st.columns(col_w)
                for hc, hl in zip(hcols, hdrs):
                    hc.markdown(
                        f"<p style='color:#8a7f72;font-size:0.72rem;font-weight:bold;margin:0 0 2px;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{hl}</p>",
                        unsafe_allow_html=True
                    )
                # 성능: iterrows → to_dict('records') (_esc는 루프 밖에서 정의)
                for r in ban_rows.sort_values('카테고리').to_dict('records'):
                    row_id  = r.get('id', None)
                    cat_v   = _esc(r.get('카테고리', '기타'))
                    cat_color = SCHEDULE_COLORS.get(str(r.get('카테고리', '기타')), "#888")
                    model_v = _esc(r.get('모델명', ''))
                    pn_v    = _esc(r.get('pn', ''))
                    ship_v  = _esc(r.get('출하계획', ''))
                    note_v  = _esc(r.get('특이사항', ''))
                    try: qty_v = int(float(r.get('조립수', 0))) if r.get('조립수') not in (None,'','nan') else 0
                    except (ValueError, TypeError): qty_v = 0
                    qty_str  = f"{qty_v}대" if qty_v else "-"
                    ship_str = ship_v if ship_v and ship_v != 'nan' else "-"
                    note_str = f"  {note_v}" if note_v and note_v not in ('', 'nan') else ""

                    rcols = st.columns(col_w)
                    rcols[0].markdown(f"<span style='background:{cat_color}22;color:{cat_color};font-weight:bold;font-size:0.72rem;padding:1px 6px;border-radius:8px;'>{cat_v}</span>", unsafe_allow_html=True)
                    rcols[1].markdown(f"<p style='font-size:0.78rem;margin:2px 0;color:#2a2420;font-weight:bold;'>{model_v}{note_str}</p>", unsafe_allow_html=True)
                    rcols[2].markdown(f"<p style='font-size:0.75rem;margin:2px 0;color:#5a5048;'>{pn_v or '-'}</p>", unsafe_allow_html=True)
                    rcols[3].markdown(f"<p style='font-size:0.78rem;margin:2px 0;color:#2471a3;font-weight:bold;'>{qty_str}</p>", unsafe_allow_html=True)
                    rcols[4].markdown(f"<p style='font-size:0.75rem;margin:2px 0;color:#5a5048;'>{ship_str}</p>", unsafe_allow_html=True)

                    if can_edit and row_id:
                        confirm_key = f"del_confirm_{row_id}"
                        if not st.session_state.get(confirm_key, False):
                            bc1, bc2 = rcols[5].columns(2)
                            if bc1.button("수정", key=f"mod_{row_id}", help="수정"):
                                st.session_state.cal_action      = "edit"
                                st.session_state.cal_action_data = int(row_id)
                                st.session_state.cal_action_sub  = None
                                _rerun(_dp_xp_key)
                            if bc2.button("삭제", key=f"del_{row_id}", help="삭제"):
                                st.session_state[confirm_key] = True
                                _rerun(_dp_xp_key)
                        else:
                            st.warning(f" [{model_v}] 일정을 삭제하시겠습니까?")
                            y1, y2 = st.columns(2)
                            if y1.button(" 예, 삭제", key=f"del_yes_{row_id}", type="primary", use_container_width=True):
                                ok = delete_schedule(int(row_id))
                                st.session_state[confirm_key] = False
                                if ok:
                                    _clear_schedule_cache()
                                    st.session_state.schedule_db = load_schedule()
                                    st.session_state["_sch_del_toast"] = f" [{model_v}] 일정이 삭제되었습니다."
                                else:
                                    st.session_state["_sch_del_toast"] = " 삭제 실패 — DB 오류가 발생했습니다."
                                _rerun(_dp_xp_key)
                            if y2.button("취소", key=f"del_no_{row_id}", use_container_width=True):
                                st.session_state[confirm_key] = False
                                _rerun(_dp_xp_key)
        else:
            st.info("등록된 일정이 없습니다.")

        if can_edit:
            st.divider()
            _cal_btn_col, _ = st.columns([1, 2])
            if _cal_btn_col.button(" 이 날짜에 일정 추가", key="inline_add_btn", use_container_width=True, type="primary"):
                st.session_state.cal_action      = "add"
                st.session_state.cal_action_data = selected_date
                _rerun(_dp_xp_key)



def clear_cal() -> None:
    st.session_state.cal_action      = None
    st.session_state.cal_action_data = None

def _do_batch_entry(sn_list, curr_line):
    """sn_list의 시리얼들을 일괄 입고 처리"""
    _next_status = '검사중' if curr_line == '검사 라인' else '포장중'
    db = st.session_state.production_db
    for sn in sn_list:
        _row = db[db['시리얼'] == sn]
        _model    = _row.iloc[0]['모델'] if not _row.empty else ''
        _ban      = _row.iloc[0]['반']   if not _row.empty else ''
        _prev_status = _row.iloc[0]['상태'] if not _row.empty else ('검사대기' if curr_line == '검사 라인' else '출하승인')
        update_row(sn, {'시간': get_now_kst_str(), '라인': curr_line,
                        '상태': _next_status, '작업자': st.session_state.user_id})
        insert_audit_log(시리얼=sn, 모델=_model, 반=_ban,
            이전상태=_prev_status, 이후상태=_next_status, 작업자=st.session_state.user_id)
    _clear_production_cache()                              # ← 캐시 초기화 (누락 버그 수정)
    st.session_state.production_db = load_realtime_ledger()

# =================================================================
# 9. 캘린더 렌더링
# =================================================================

# 공통 셀 렌더링 헬퍼
def _render_cal_cells(sch_df, cal_year, cal_month, weeks_to_show, today, can_edit, key_prefix):
    days_kr  = ["일","월","화","수","목","금","토"]
    hdr_cols = st.columns(7)
    for i, d in enumerate(days_kr):
        color = "#e8908a" if i == 0 else "#7eb8e8" if i == 6 else "#7a6f65"
        hdr_cols[i].markdown(
            f"<div style='text-align:center; font-weight:bold; color:{color}; "
            f"padding:8px; background:#ede8de; border-radius:6px;'>{d}</div>",
            unsafe_allow_html=True)

    for week in weeks_to_show:
        week_cols = st.columns(7)
        for i, day in enumerate(week):
            with week_cols[i]:
                if day == 0:
                    st.markdown("<div style='min-height:100px;'></div>", unsafe_allow_html=True)
                    continue

                day_str   = f"{cal_year}-{cal_month:02d}-{day:02d}"
                day_data  = sch_df[sch_df['날짜'] == day_str] if not sch_df.empty else pd.DataFrame()
                is_today  = (today == date(cal_year, cal_month, day))
                bg        = "#d8ede2" if is_today else "#fffdf8"
                border    = "2px solid #7ec8a0" if is_today else "1px solid #e0d8c8"
                today_cls = " today" if is_today else ""

                # 카테고리별 건수 집계 (벡터화)
                cat_counts = {}
                event_count = 0
                if not day_data.empty:
                    _cat_col = day_data['카테고리'].fillna('기타').astype(str).replace({'': '기타', 'nan': '기타'})
                    cat_counts = _cat_col.value_counts().to_dict()
                    event_count = len(day_data)

                today_mark = " " if is_today else ""
                btn_label  = f"{day}{today_mark}"

                # ── 날짜 버튼
                _cal_xp_key = "cal_weekly" if key_prefix == "wk" else "cal_monthly"
                day_cls = "cal-today-btn" if is_today else "cal-day-btn"
                st.markdown(f"<div class='{day_cls}'>", unsafe_allow_html=True)
                if st.button(btn_label, key=f"{key_prefix}_{day_str}", use_container_width=True):
                    st.session_state.cal_action      = "view_day"
                    st.session_state.cal_action_data = day_str
                    st.session_state["_cal_active_xp"] = _cal_xp_key
                    _rerun(_cal_xp_key)
                st.markdown("</div>", unsafe_allow_html=True)

                # ── 카테고리별 뱃지 (건수만)
                if cat_counts:
                    badge_html = "<div style='margin-top:3px; display:flex; flex-direction:column; gap:2px;'>"
                    for cat, cnt in cat_counts.items():
                        color = SCHEDULE_COLORS.get(cat, "#888")
                        badge_html += (
                            f"<div style='background:{color}18; border-left:3px solid {color}; "
                            f"border-radius:3px; padding:2px 5px; font-size:0.65rem; line-height:1.4;'>"
                            f"<span style='color:{color}; font-weight:bold;'>{cat}</span> "
                            f"<span style='color:#5a5048; font-weight:bold;'>{cnt}건</span>"
                            f"</div>"
                        )
                    badge_html += "</div>"
                    st.markdown(badge_html, unsafe_allow_html=True)


# ── 범례 공통
def _render_legend():
    legend_html = "<div style='display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px;'>"
    for cat, color in SCHEDULE_COLORS.items():
        legend_html += f"<span style='background:{color}; color:#fff; padding:3px 10px; border-radius:12px; font-size:0.75rem; font-weight:bold;'>{cat}</span>"
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

# ── 주별 캘린더
def render_calendar_weekly():
    sch_df    = st.session_state.schedule_db
    cal_year  = st.session_state.cal_year
    cal_month = st.session_state.cal_month
    can_edit  = st.session_state.user_role in CALENDAR_EDIT_ROLES
    today     = date.today()
    cal_weeks = calendar.monthcalendar(cal_year, cal_month)

    # 현재 주 자동 탐색
    if cal_year == today.year and cal_month == today.month:
        for wi, week in enumerate(cal_weeks):
            if today.day in week:
                if st.session_state.get('cal_auto_week', True):
                    st.session_state.cal_week_idx  = wi
                    st.session_state.cal_auto_week = False
                break

    week_idx = min(st.session_state.cal_week_idx, len(cal_weeks)-1)
    exp_label = f" 주별 캘린더  —  {cal_year}년 {cal_month}월 {week_idx+1}주차"

    with st.expander(exp_label, expanded=_xp("cal_weekly"), key="_xp_cal_weekly"):
        # 월 네비게이션
        h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
        if h1.button("◀ 이전달", key="w_prev_month", use_container_width=True):
            clear_cal()
            if cal_month == 1: st.session_state.cal_year -= 1; st.session_state.cal_month = 12
            else: st.session_state.cal_month -= 1
            st.session_state.cal_week_idx = 0
            _rerun("cal_weekly")
        if h2.button("오늘", key="w_today", use_container_width=True):
            clear_cal()
            st.session_state.cal_year      = today.year
            st.session_state.cal_month     = today.month
            st.session_state.cal_auto_week = True
            _rerun("cal_weekly")
        h3.markdown(
            f"<p style='text-align:center; font-weight:bold; margin:8px 0; font-size:1rem;'>"
            f"{cal_year}년 {cal_month}월 {week_idx+1}주차</p>",
            unsafe_allow_html=True)
        if h4.button("다음달 ▶", key="w_next_month", use_container_width=True):
            clear_cal()
            if cal_month == 12: st.session_state.cal_year += 1; st.session_state.cal_month = 1
            else: st.session_state.cal_month += 1
            st.session_state.cal_week_idx = 0
            _rerun("cal_weekly")

        # 주 네비게이션
        w1, w2, w3 = st.columns([1, 4, 1])
        if w1.button("◀ 이전주", key="w_prev_week", use_container_width=True):
            clear_cal()
            if st.session_state.cal_week_idx > 0:
                st.session_state.cal_week_idx -= 1
            else:
                if cal_month == 1: st.session_state.cal_year -= 1; st.session_state.cal_month = 12
                else: st.session_state.cal_month -= 1
                prev_weeks = calendar.monthcalendar(st.session_state.cal_year, st.session_state.cal_month)
                st.session_state.cal_week_idx = len(prev_weeks) - 1
            _rerun("cal_weekly")
        w2.markdown(
            f"<p style='text-align:center; color:#8a7f72; margin:8px 0;'>"
            f"{cal_year}년 {cal_month}월 {week_idx+1}주차</p>",
            unsafe_allow_html=True)
        if w3.button("다음주 ▶", key="w_next_week", use_container_width=True):
            clear_cal()
            if st.session_state.cal_week_idx < len(cal_weeks) - 1:
                st.session_state.cal_week_idx += 1
            else:
                if cal_month == 12: st.session_state.cal_year += 1; st.session_state.cal_month = 1
                else: st.session_state.cal_month += 1
                st.session_state.cal_week_idx = 0
            _rerun("cal_weekly")

        _render_legend()
        _render_cal_cells(sch_df, cal_year, cal_month,
                          [cal_weeks[week_idx]], today, can_edit, "wk")

# ── 월별 캘린더
def render_calendar_monthly(
    #  리팩토링 권장: 이 함수는 390+ 라인으로 다음과 같이 분리 권장:
    # - render_calendar_header(): 헤더 렌더링
    # - render_calendar_cells(): 셀 렌더링
    # - handle_calendar_events(): 이벤트 처리
    # - save_calendar_changes(): 변경사항 저장
    ):
    sch_df    = st.session_state.schedule_db
    cal_year  = st.session_state.cal_month_year  if 'cal_month_year'  in st.session_state else st.session_state.cal_year
    cal_month = st.session_state.cal_month_month if 'cal_month_month' in st.session_state else st.session_state.cal_month
    can_edit  = st.session_state.user_role in CALENDAR_EDIT_ROLES
    today     = date.today()
    cal_weeks = calendar.monthcalendar(cal_year, cal_month)

    exp_label = f" 월별 캘린더  —  {cal_year}년 {cal_month}월 전체"

    with st.expander(exp_label, expanded=_xp("cal_monthly"), key="_xp_cal_monthly"):
        h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
        if h1.button("◀ 이전달", key="m_prev_month", use_container_width=True):
            clear_cal()
            if cal_month == 1: st.session_state.cal_month_year = cal_year - 1; st.session_state.cal_month_month = 12
            else: st.session_state.cal_month_year = cal_year; st.session_state.cal_month_month = cal_month - 1
            _rerun("cal_monthly")
        if h2.button("오늘", key="m_today", use_container_width=True):
            clear_cal()
            st.session_state.cal_month_year  = today.year
            st.session_state.cal_month_month = today.month
            _rerun("cal_monthly")
        h3.markdown(
            f"<p style='text-align:center; font-weight:bold; margin:8px 0; font-size:1rem;'>"
            f"{cal_year}년 {cal_month}월 전체</p>",
            unsafe_allow_html=True)
        if h4.button("다음달 ▶", key="m_next_month", use_container_width=True):
            clear_cal()
            if cal_month == 12: st.session_state.cal_month_year = cal_year + 1; st.session_state.cal_month_month = 1
            else: st.session_state.cal_month_year = cal_year; st.session_state.cal_month_month = cal_month + 1
            _rerun("cal_monthly")

        _render_legend()
        _render_cal_cells(sch_df, cal_year, cal_month,
                          cal_weeks, today, can_edit, "mo")


