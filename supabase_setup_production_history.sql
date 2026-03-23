-- ============================================================
-- production_history 테이블 생성 스크립트
-- 실행 위치: Supabase 대시보드 > SQL Editor
-- 목적: production 테이블의 완료 레코드를 30일 후 이 테이블로 이동
--       → production 테이블을 항상 가볍게 유지 (대역폭·속도 최적화)
-- ============================================================

-- 1) 테이블 생성 (production과 동일한 컬럼 구조)
CREATE TABLE IF NOT EXISTS production_history (
    LIKE production INCLUDING DEFAULTS INCLUDING CONSTRAINTS
);

-- 2) 시리얼 중복 방지 (upsert on_conflict 기준)
ALTER TABLE production_history
    DROP CONSTRAINT IF EXISTS production_history_pkey;
ALTER TABLE production_history
    ADD PRIMARY KEY ("시리얼");

-- 3) 조회 속도용 인덱스
CREATE INDEX IF NOT EXISTS idx_ph_time  ON production_history ("시간");
CREATE INDEX IF NOT EXISTS idx_ph_state ON production_history ("상태");
CREATE INDEX IF NOT EXISTS idx_ph_ban   ON production_history ("반");

-- ※ production 테이블에도 인덱스 추가 (아직 없는 경우)
CREATE INDEX IF NOT EXISTS idx_prod_time  ON production ("시간");
CREATE INDEX IF NOT EXISTS idx_prod_state ON production ("상태");
CREATE INDEX IF NOT EXISTS idx_prod_ban   ON production ("반");

-- ============================================================
-- 확인 쿼리 (실행 후 테이블 생성 여부 확인용)
-- ============================================================
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public'
--   AND table_name IN ('production', 'production_history');
