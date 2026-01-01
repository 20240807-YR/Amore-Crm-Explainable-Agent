# agent10/product_selector.py
import re
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


class ProductSelector:
    def __init__(self):
        csv_path = DATA_DIR / "amore_with_category.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"데이터 파일 없음: {csv_path}")

        df = pd.read_csv(csv_path)
        df.columns = [str(c).strip() for c in df.columns]

        if "상품명" not in df.columns:
            raise RuntimeError(
                f"[ProductSelector] '상품명' 컬럼 없음: {df.columns.tolist()}"
            )

        self.df = df
        self.name_col = "상품명"
        self.brand_col = "brand" if "brand" in df.columns else None

        self.df[self.name_col] = (
            self.df[self.name_col].astype(str).fillna("").str.strip()
        )
        if self.brand_col:
            self.df[self.brand_col] = (
                self.df[self.brand_col].astype(str).fillna("").str.strip()
            )

        # ❌ 도구 / 잡화
        self.banned_nouns = [
            "뷰러", "퍼프", "브러시", "스펀지", "집게",
            "케이스", "용기", "파우치",
            "샘플", "증정", "기획",
        ]

        # ❌ 메이크업 도메인(1차 필터에서만 사용, 후보가 0이면 완화 모드에서 해제)
        self.banned_makeup_terms = [
            "아이", "립", "립스틱", "틴트",
            "마스카라", "아이라이너", "라이너",
            "섀도우", "섀도", "글리터",
            "컬픽스", "픽서", "마스카라픽서",
            "애교살",
            "리무버",
        ]

        # ❌ 설명형 문구
        self.banned_phrases = [
            "용량 넉넉",
            "흡수 빠름", "흡수 빨라",
            "촉촉", "산뜻", "부드러움", "가벼움",
            "순해요", "편안해요",
        ]

        # ✂️ 옵션 / 코드 제거
        self.cut_patterns = [
            r"\s*\(\s*\d+.*?\)",            # (3개입*8) 등
            r"\s*\d+\s*(ml|mL|g|kg|ea)\b",  # 25ml, 8g, 1ea
            r"\s*/\s*\d+.*$",               # 1매/25ml 같은 꼬리
            r"\s*:\s*[\d\.]+",              # : 0. 같은 코드 제거
        ]

        # ❌ 수량 단독
        self.only_quantity_pattern = re.compile(r"^\d+\s*(개입|입|매|팩|세트|ea)$")

        # ❌ 단독이면 절대 제품명이 될 수 없는 토큰
        self.banned_singletons = {
            "미니", "본품", "리필", "세트", "팩", "키트",
            "기획", "증정", "샘플", "구성", "사은품",
        }

    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _strip_wrappers(self, s: str) -> str:
        t = (s or "").strip()
        while True:
            new_t = re.sub(r'^[\s\(\[\{\'"“”‘’]+', "", t)
            new_t = re.sub(r'[\s\)\]\}\'"“”‘’]+$', "", new_t)
            new_t = new_t.strip()
            if new_t == t:
                break
            t = new_t
        return t

    def _normalize(self, text: str) -> str:
        s = (text or "").strip()
        s = self._strip_wrappers(s)
        for p in self.cut_patterns:
            s = re.sub(p, "", s)
        s = s.strip()
        s = self._strip_wrappers(s)
        return s.strip()

    def _has_meaningful_token(self, text: str) -> bool:
        return bool(
            re.search(r"[가-힣]{2,}", text) or re.search(r"[A-Za-z]{3,}", text)
        )

    def _score_fragment(self, frag: str) -> int:
        score = 0
        score += len(re.findall(r"[가-힣]{2,}", frag)) * 2
        score += len(re.findall(r"[A-Za-z]{3,}", frag))
        score -= len(re.findall(r"[\d\.]", frag))
        return score

    def _is_bad_singleton(self, s: str) -> bool:
        t = self._strip_wrappers(s).strip()
        if not t:
            return True
        if t.lower() == "nan":
            return True
        if t in self.banned_singletons:
            return True
        if self.only_quantity_pattern.fullmatch(t):
            return True
        if re.fullmatch(r"(본품|리필)\s*[\+\&]\s*(본품|리필)", t):
            return True
        return False

    def _collect_candidates(self, raw_name: str, strict_makeup: bool = True) -> list[str]:
        parts = re.split(r"\s*(\+|/|\||,)\s*", raw_name)
        candidates: list[str] = []

        for p in parts:
            p = self._normalize(p)
            if not p:
                continue

            # (미니) 같은 껍데기 제거 후 빈 값이면 버림
            if not p or p.lower() == "nan":
                continue

            # 단독 토큰/수량 토큰 버림
            if self._is_bad_singleton(p):
                continue

            # 잡화/도구 제거
            if any(b in p for b in self.banned_nouns):
                continue

            # 설명형 문구 제거
            if any(b in p for b in self.banned_phrases):
                continue

            # 메이크업 도메인 제거(엄격 모드에서만)
            if strict_makeup and any(b in p for b in self.banned_makeup_terms):
                continue

            # 숫자/기호 위주
            if re.fullmatch(r"[\d\s\W_]+", p):
                continue

            # 의미 토큰(한글2+ or 영문3+) 없으면 버림
            if not self._has_meaningful_token(p):
                continue

            # 너무 짧은 단일 키워드(미니 같은 것) 방지: 의미 토큰이 있어도 3자 이하면 버림
            if len(p) <= 3:
                continue

            candidates.append(p)

        return candidates

    def _pick_best(self, candidates: list[str]) -> str | None:
        if not candidates:
            return None
        candidates = [c for c in candidates if c and c.strip() and c.lower() != "nan"]
        if not candidates:
            return None
        candidates.sort(key=self._score_fragment, reverse=True)
        best = candidates[0].strip()
        return best if best else None

    def _extract_best_fragment(self, raw_name: str) -> str | None:
        # 1) 엄격 모드(메이크업 제거)
        c1 = self._collect_candidates(raw_name, strict_makeup=True)
        best = self._pick_best(c1)
        if best:
            return best

        # 2) 완화 모드(메이크업 제거 해제) — 그래도 절대 빈 문자열은 반환하지 않음
        c2 = self._collect_candidates(raw_name, strict_makeup=False)
        best2 = self._pick_best(c2)
        if best2:
            return best2

        return None

    def select_one(self, row: dict):
        brand = self._s(row.get("brand", ""))

        df = self.df
        if self.brand_col and brand:
            sub = df[df[self.brand_col] == brand]
            if sub.empty:
                sub = df
        else:
            sub = df

        results: list[str] = []
        for raw in sub[self.name_col]:
            raw_s = self._s(raw)
            if not raw_s or raw_s.lower() == "nan":
                continue
            best = self._extract_best_fragment(raw_s)
            if best and best.strip() and best.lower() != "nan":
                results.append(best.strip())

        # ✅ 여기서 실패하면 controller가 빈 상품명으로 흘릴 가능성이 있어서,
        #    "빈 값"만은 절대 반환하지 않도록 마지막 안전장치(완화)를 한 번 더 건다.
        if not results:
            for raw in sub[self.name_col]:
                raw_s = self._normalize(self._s(raw))
                if not raw_s:
                    continue
                if self._is_bad_singleton(raw_s):
                    continue
                if any(b in raw_s for b in self.banned_nouns):
                    continue
                if re.fullmatch(r"[\d\s\W_]+", raw_s):
                    continue
                if not self._has_meaningful_token(raw_s):
                    continue
                results.append(raw_s)
                break

        if not results:
            raise RuntimeError(
                f"[ProductSelector] 유효한 '실제 제품명' 후보 없음 (brand={brand})"
            )

        # 첫 후보 고정
        return {"상품명": results[0]}