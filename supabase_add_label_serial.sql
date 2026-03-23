-- ============================================================
-- 라벨 시리얼 컬럼 추가 마이그레이션
-- 실행 위치: Supabase 대시보드 > SQL Editor
-- 목적: 포장 라인에서 제품 라벨 바코드(시리얼)를 기록
-- ============================================================

-- 1) production 테이블에 라벨시리얼 컬럼 추가
ALTER TABLE production
    ADD COLUMN IF NOT EXISTS "라벨시리얼" TEXT DEFAULT NULL;

-- 2) production_history 테이블에도 동일하게 추가
ALTER TABLE production_history
    ADD COLUMN IF NOT EXISTS "라벨시리얼" TEXT DEFAULT NULL;

-- 3) 조회 속도용 인덱스 (라벨시리얼로 역추적 시 유용)
CREATE INDEX IF NOT EXISTS idx_prod_label ON production ("라벨시리얼");
CREATE INDEX IF NOT EXISTS idx_ph_label   ON production_history ("라벨시리얼");

-- ============================================================
-- 확인 쿼리
-- ============================================================
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'production' AND column_name = '라벨시리얼';
