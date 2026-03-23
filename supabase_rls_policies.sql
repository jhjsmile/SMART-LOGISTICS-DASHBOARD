-- =================================================================
-- Supabase Row Level Security (RLS) 정책
-- 적용 방법: Supabase Dashboard > SQL Editor에서 실행
-- 또는: supabase db push (CLI 사용 시)
--
-- 보안 모델:
--   - anon 역할: 읽기/쓰기 모두 차단 (앱은 service_role 키 사용)
--   - authenticated 역할: 필요 시 테이블별 허용 (현재 앱은 서버사이드 전용)
--
-- 주의: 현재 앱은 서버사이드에서 supabase-py (service_role 키)로
--       모든 DB 작업을 수행하므로, RLS는 외부 직접 접근 차단이 목적입니다.
-- =================================================================


-- ── 1. 모든 테이블에 RLS 활성화 ─────────────────────────────────

ALTER TABLE production          ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_history  ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_backup   ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log           ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_serial     ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_plan     ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_change_log     ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedule_change_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_master        ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE help_requests       ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_requests     ENABLE ROW LEVEL SECURITY;


-- ── 2. 기존 정책 초기화 (재실행 안전성 확보) ─────────────────────

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I',
                   r.policyname, r.schemaname, r.tablename);
  END LOOP;
END $$;


-- ── 3. anon 역할 완전 차단 정책 ─────────────────────────────────
--
-- Streamlit 앱은 service_role 키를 사용하므로 RLS를 우회합니다.
-- anon/authenticated 역할로는 어떤 접근도 허용하지 않습니다.

-- production 테이블
CREATE POLICY "deny_anon_production"
  ON production
  FOR ALL
  TO anon
  USING (false);

-- production_history 테이블
CREATE POLICY "deny_anon_production_history"
  ON production_history
  FOR ALL
  TO anon
  USING (false);

-- production_backup 테이블
CREATE POLICY "deny_anon_production_backup"
  ON production_backup
  FOR ALL
  TO anon
  USING (false);

-- audit_log 테이블
CREATE POLICY "deny_anon_audit_log"
  ON audit_log
  FOR ALL
  TO anon
  USING (false);

-- material_serial 테이블
CREATE POLICY "deny_anon_material_serial"
  ON material_serial
  FOR ALL
  TO anon
  USING (false);

-- production_schedule 테이블
CREATE POLICY "deny_anon_production_schedule"
  ON production_schedule
  FOR ALL
  TO anon
  USING (false);

-- production_plan 테이블
CREATE POLICY "deny_anon_production_plan"
  ON production_plan
  FOR ALL
  TO anon
  USING (false);

-- plan_change_log 테이블
CREATE POLICY "deny_anon_plan_change_log"
  ON plan_change_log
  FOR ALL
  TO anon
  USING (false);

-- schedule_change_log 테이블
CREATE POLICY "deny_anon_schedule_change_log"
  ON schedule_change_log
  FOR ALL
  TO anon
  USING (false);

-- model_master 테이블
CREATE POLICY "deny_anon_model_master"
  ON model_master
  FOR ALL
  TO anon
  USING (false);

-- app_settings 테이블
CREATE POLICY "deny_anon_app_settings"
  ON app_settings
  FOR ALL
  TO anon
  USING (false);

-- help_requests 테이블
CREATE POLICY "deny_anon_help_requests"
  ON help_requests
  FOR ALL
  TO anon
  USING (false);

-- access_requests 테이블
CREATE POLICY "deny_anon_access_requests"
  ON access_requests
  FOR ALL
  TO anon
  USING (false);


-- ── 4. authenticated 역할도 차단 (앱은 service_role만 사용) ───────

CREATE POLICY "deny_authenticated_production"
  ON production FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_production_history"
  ON production_history FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_production_backup"
  ON production_backup FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_audit_log"
  ON audit_log FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_material_serial"
  ON material_serial FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_production_schedule"
  ON production_schedule FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_production_plan"
  ON production_plan FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_plan_change_log"
  ON plan_change_log FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_schedule_change_log"
  ON schedule_change_log FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_model_master"
  ON model_master FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_app_settings"
  ON app_settings FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_help_requests"
  ON help_requests FOR ALL TO authenticated USING (false);

CREATE POLICY "deny_authenticated_access_requests"
  ON access_requests FOR ALL TO authenticated USING (false);


-- ── 5. 적용 확인 쿼리 ────────────────────────────────────────────
--
-- 아래 쿼리로 RLS 적용 여부와 정책 목록 확인:
--
-- SELECT tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- ORDER BY tablename;
--
-- SELECT schemaname, tablename, policyname, roles, cmd
-- FROM pg_policies
-- WHERE schemaname = 'public'
-- ORDER BY tablename, policyname;
